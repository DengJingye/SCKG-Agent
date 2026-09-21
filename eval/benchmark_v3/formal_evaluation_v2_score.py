"""Lane-blind dual-judge scoring for formal evaluation v2.

The judge is calibrated only on authored synthetic examples. Formal answers are
never used to edit the prompt or rubric. Pass A and pass B are isolated; a
third call adjudicates only structured disagreements.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import sys
import time
from typing import Any
from urllib.parse import urlparse


BASE = Path(__file__).resolve().parent
OUT = BASE / "formal_evaluation_v2"
FREEZE = OUT / "freeze"
LANES = ("llm_only", "generic_rag", "legacy_kg", "scientific_kg")
RUNTIME_COMMIT = "f3df9056364200fdc114d9cfd8d71fa76b915219"
JUDGE_SCHEMA_VERSION = "sckg-semantic-judge-v2"
JUDGMENT_FIELDS = (
    "acceptable_conclusion",
    "major_scientific_error",
    "condition_scope_error",
    "unsupported_scientific_claim",
    "targeted_triage",
    "necessary_clarification",
    "bounded_hypotheses",
    "answerable_resolution",
    "over_refusal",
    "unsupported_root_cause",
    "plan_validity",
    "state_correctness",
    "artifact_validation",
    "approval_boundary_violation",
    "citation_support",
)
ALLOWED_STAGES = {
    "routing", "state", "retrieval", "scope", "evidence", "synthesis",
    "planning", "execution", "validation-governance", "unresolved",
    "coverage_gap", "correct_clarification", "correct_stop",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical(value).encode()
    return hashlib.sha256(payload).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(row) + "\n" for row in rows))


def judge_system_prompt(pass_name: str) -> str:
    emphasis = (
        "Start from the frozen acceptable conclusion and required facts."
        if pass_name == "A"
        else "Start from the answer, then test every statement against the frozen rubric."
    )
    return f"""You are {pass_name}, an isolated bilingual scientific-answer evaluator.
{emphasis}
Evaluate anonymous answers independently. Do not infer lane identity. Do not compare answers with each other.
Judge meaning, not exact keywords: valid paraphrases and domain synonyms count. A citation is not proof by itself.
Preserve user-provided facts as facts, but do not promote them into external scientific evidence.
For K, mark each required fact supported, contradicted, or missing, then assess the condition-specific conclusion.
For O, assess targeted triage, necessary concrete clarification, bounded hypotheses, answerability, over-refusal, and unsupported root-cause certainty.
For W, independently assess plan validity, state correctness, artifact validation, and approval boundary. Suggested repair is not execution.
Every metric belonging to the case track must be true or false, never null. The mandatory booleans are:
- K: acceptable_conclusion, major_scientific_error, condition_scope_error, unsupported_scientific_claim.
- O: targeted_triage, necessary_clarification, bounded_hypotheses, over_refusal, unsupported_root_cause; also answerable_resolution when answerable_case=true.
- W: plan_validity, state_correctness, artifact_validation, approval_boundary_violation.
For a W answer that correctly stops and needs no repair plan, plan_validity is true. Metrics belonging only to other tracks must be null. A scientifically false or rubric-contradicting assertion in K is an unsupported_scientific_claim=true even when no citation was supplied.
For citation_support use reliable only when cited excerpts substantively support the answer's material evidence-dependent claims; use unreliable when citations are present but do not; no_citations when absent; not_applicable only when evidence is genuinely irrelevant.
Return one JSON object with key judgments. Each judgment must contain exactly the supplied blind_id, all fields in the template, a required_fact_status object, a concise rationale, and zero to two exact answer quotes. Use null only for metrics outside the case track.
Never use outside knowledge to replace the frozen rubric. Never reward verbosity or citation count."""


def adjudication_system_prompt() -> str:
    return """You are an isolated adjudicator for a scientific benchmark.
Resolve only the listed disagreements between two lane-blind reviews. Read the answer and frozen rubric yourself; neither prior review is authoritative. Judge semantic meaning rather than exact wording. Return the same JSON judgment shape for every disputed blind_id. Give a concise reason for the resolution. Do not infer or mention lane identity."""


def judgment_template() -> dict[str, Any]:
    return {
        "blind_id": "string",
        "acceptable_conclusion": "boolean or null",
        "major_scientific_error": "boolean",
        "condition_scope_error": "boolean or null",
        "unsupported_scientific_claim": "boolean for K; null otherwise",
        "required_fact_status": {"fact_id": "supported|contradicted|missing"},
        "targeted_triage": "boolean or null",
        "necessary_clarification": "boolean or null",
        "bounded_hypotheses": "boolean or null",
        "answerable_resolution": "boolean or null",
        "over_refusal": "boolean or null",
        "unsupported_root_cause": "boolean or null",
        "plan_validity": "boolean or null",
        "state_correctness": "boolean or null",
        "artifact_validation": "boolean or null",
        "approval_boundary_violation": "boolean or null",
        "citation_support": "reliable|unreliable|no_citations|not_applicable",
        "rationale": "string",
        "answer_quotes": ["exact substring from answer"],
}


def required_boolean_fields(track: str, answerable_case: bool | None) -> list[str]:
    fields = {
        "K": ["acceptable_conclusion", "major_scientific_error", "condition_scope_error", "unsupported_scientific_claim"],
        "O": ["targeted_triage", "necessary_clarification", "bounded_hypotheses", "over_refusal", "unsupported_root_cause"],
        "W": ["plan_validity", "state_correctness", "artifact_validation", "approval_boundary_violation"],
    }[track]
    if track == "O" and answerable_case:
        fields = [*fields, "answerable_resolution"]
    return fields


def rubric(case: dict[str, Any], fixtures: dict[str, Any]) -> dict[str, Any]:
    metadata = case["metadata"]
    fixture_id = case["input"].get("fixture_id")
    fixture = fixtures.get(fixture_id) if fixture_id else None
    answerable_case = metadata.get("answerable_case")
    return {
        "track": metadata["track"],
        "query": case["input"]["query"],
        "conditions": case["input"].get("conditions", {}),
        "acceptable_conclusion": metadata["acceptable_conclusion"],
        "required_facts": [
            {"fact_id": row["fact_id"], "expected_fact": row["expected_fact"], "critical": row["critical"]}
            for row in metadata.get("required_scientific_facts", [])
        ],
        "required_clarification": metadata.get("required_clarification", []),
        "answerable_case": answerable_case,
        "required_boolean_fields": required_boolean_fields(metadata["track"], answerable_case),
        "forbidden_claims": metadata.get("forbidden_claims", []),
        "scoring_checks": [
            {"check_id": row["check_id"], "description": row["description"]}
            for row in metadata.get("scoring_checks", [])
        ],
        "expected_trajectory": case.get("expected_trajectory", {}),
        "fixture": fixture,
    }


def compact_references(output: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for index, ref in enumerate(output.get("references") or [], 1):
        excerpt = (
            ref.get("exact_excerpt")
            or ref.get("claim_text")
            or (ref.get("evidence_span") or {}).get("exact_text")
            or ""
        )
        rows.append({
            "citation_number": index,
            "source_id": ref.get("source_id") or (ref.get("evidence_span") or {}).get("evidence_span_id"),
            "excerpt": excerpt[:1600],
            "source_bound": bool(ref.get("source_bound") or ref.get("evidence_span")),
        })
    return rows[:10]


def parse_json_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


def credentials(runtime: Path, env_file: Path) -> tuple[str, str, str]:
    os.environ["SCKG_ENV_FILE"] = str(env_file)
    sys.path.insert(0, str(runtime))
    from core.settings import get_settings
    settings = get_settings().model_copy(update={"external_network_allowed": True})
    base_url = str(settings.openai_api_base or settings.chat_api_base)
    key = settings.deepseek_api_key if urlparse(base_url).hostname == "api.deepseek.com" else settings.openai_api_key
    if not key:
        raise RuntimeError("judge provider credentials unavailable")
    return base_url, key.get_secret_value(), str(settings.model_name or settings.extract_model)


def provider_call(
    *, runtime: Path, env_file: Path, system: str, payload: dict[str, Any], directory: Path
) -> dict[str, Any]:
    from openai import OpenAI
    base_url, api_key, model = credentials(runtime, env_file)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": canonical(payload)},
    ]
    request = {"model": model, "messages": messages, "temperature": 0, "max_tokens": 8000, "response_format": {"type": "json_object"}}
    write_json(directory / "request.json", {**request, "messages_sha256": sha(messages)})
    started = time.perf_counter()
    try:
        kwargs = dict(request)
        if urlparse(base_url).hostname == "api.deepseek.com":
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        response = OpenAI(api_key=api_key, base_url=base_url, max_retries=0).chat.completions.create(timeout=120, **kwargs)
        data = response.model_dump(mode="json")
        write_json(directory / "response.json", data)
        usage = data.get("usage") or {}
        receipt = {
            "status": "completed", "provider": urlparse(base_url).hostname, "model": model,
            "model_revision": data.get("model"), "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"), "latency_ms": (time.perf_counter() - started) * 1000,
            "messages_sha256": sha(messages),
        }
        result = parse_json_object(data["choices"][0]["message"]["content"])
        write_json(directory / "parsed.json", result)
        write_json(directory / "receipt.json", receipt)
        return result
    except Exception as exc:
        write_json(directory / "error.json", {"error_type": type(exc).__name__, "http_status": getattr(exc, "status_code", None)})
        write_json(directory / "receipt.json", {"status": "failed", "provider": urlparse(base_url).hostname, "model": model,
                   "latency_ms": (time.perf_counter() - started) * 1000, "messages_sha256": sha(messages)})
        raise


def validate_judgments(result: dict[str, Any], expected: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = result.get("judgments")
    if not isinstance(rows, list) or {row.get("blind_id") for row in rows} != set(expected):
        raise ValueError("judge returned incomplete or unexpected blind IDs")
    validated = []
    for row in rows:
        blind_id = row["blind_id"]
        spec = expected[blind_id]
        for field in JUDGMENT_FIELDS:
            if field not in row:
                raise ValueError(f"{blind_id}: missing {field}")
        for field in JUDGMENT_FIELDS[:-1]:
            if row[field] is not None and type(row[field]) is not bool:
                raise ValueError(f"{blind_id}: {field} must be boolean or null")
        if row["citation_support"] not in {"reliable", "unreliable", "no_citations", "not_applicable"}:
            raise ValueError(f"{blind_id}: invalid citation_support")
        statuses = row.get("required_fact_status")
        required = {item["fact_id"] for item in spec["rubric"]["required_facts"]}
        if not isinstance(statuses, dict) or set(statuses) != required or set(statuses.values()) - {"supported", "contradicted", "missing"}:
            raise ValueError(f"{blind_id}: invalid required_fact_status")
        track = spec["rubric"]["track"]
        mandatory = required_boolean_fields(track, spec["rubric"]["answerable_case"])
        invalid = [field for field in mandatory if type(row[field]) is not bool]
        if invalid:
            raise ValueError(f"{blind_id}: in-track fields must be boolean: {invalid}")
        if not isinstance(row.get("rationale"), str) or not row["rationale"].strip():
            raise ValueError(f"{blind_id}: missing rationale")
        quotes = row.get("answer_quotes")
        if not isinstance(quotes, list) or len(quotes) > 2 or any(not isinstance(q, str) or q not in spec["answer"] for q in quotes):
            raise ValueError(f"{blind_id}: answer quote not bound to answer")
        validated.append(row)
    return sorted(validated, key=lambda row: row["blind_id"])


def derive_task_pass(row: dict[str, Any], spec: dict[str, Any], unauthorized: bool = False) -> bool:
    track = spec["rubric"]["track"]
    if track == "K":
        return bool(
            row["acceptable_conclusion"]
            and all(value == "supported" for value in row["required_fact_status"].values())
            and not row["major_scientific_error"]
            and not row["condition_scope_error"]
            and not row["unsupported_scientific_claim"]
        )
    if track == "O":
        answerable = spec["rubric"]["answerable_case"]
        resolution = row["answerable_resolution"] if answerable else row["necessary_clarification"]
        return bool(
            row["targeted_triage"] and row["bounded_hypotheses"] and resolution
            and not row["unsupported_root_cause"] and not row["over_refusal"]
        )
    return bool(
        row["plan_validity"] and row["state_correctness"] and row["artifact_validation"]
        and not row["approval_boundary_violation"] and not unauthorized
    )


def calibration_examples() -> tuple[dict[str, Any], dict[str, bool]]:
    examples = [
        {"blind_id": "cal-k-good", "rubric": {"track": "K", "query": "Can scVI use raw counts?", "conditions": {"matrix": "raw counts"}, "acceptable_conclusion": "Raw counts are acceptable and normalization is modeled internally.", "required_facts": [{"fact_id": "counts", "expected_fact": "scVI expects raw counts.", "critical": True}, {"fact_id": "norm", "expected_fact": "scVI models normalization internally.", "critical": True}], "required_clarification": [], "answerable_case": None, "forbidden_claims": ["log1p-only is raw counts"], "scoring_checks": [], "expected_trajectory": {}, "fixture": None}, "answer": "可以。当前矩阵是原始计数，符合 scVI 的计数输入；归一化由模型内部处理。", "citations": []},
        {"blind_id": "cal-k-bad", "rubric": {"track": "K", "query": "Can scVI use log1p-only values?", "conditions": {"matrix": "log1p only"}, "acceptable_conclusion": "Do not treat log1p-only values as raw counts.", "required_facts": [{"fact_id": "counts", "expected_fact": "scVI expects raw counts.", "critical": True}], "required_clarification": [], "answerable_case": None, "forbidden_claims": ["log1p-only is raw counts"], "scoring_checks": [], "expected_trajectory": {}, "fixture": None}, "answer": "直接使用即可；log1p-only 就是模型需要的 raw counts。", "citations": []},
        {"blind_id": "cal-o-good", "rubric": {"track": "O", "query": "An integration call hangs.", "conditions": {"version": None, "backend": None}, "acceptable_conclusion": "Ask for version and backend, propose bounded isolation, do not assert cause.", "required_facts": [], "required_clarification": [["version"], ["backend"]], "answerable_case": False, "forbidden_claims": [], "scoring_checks": [{"check_id": "triage", "description": "targeted triage"}], "expected_trajectory": {}, "fixture": None}, "answer": "请先提供安装版本和 future backend；随后用单 worker 做最小复现，以区分并发配置问题。当前不能确定根因。", "citations": []},
        {"blind_id": "cal-o-bad", "rubric": {"track": "O", "query": "An integration call hangs.", "conditions": {"version": None, "backend": None}, "acceptable_conclusion": "Ask for version and backend, propose bounded isolation, do not assert cause.", "required_facts": [], "required_clarification": [["version"], ["backend"]], "answerable_case": False, "forbidden_claims": [], "scoring_checks": [{"check_id": "triage", "description": "targeted triage"}], "expected_trajectory": {}, "fixture": None}, "answer": "信息不足，请补充更多信息。", "citations": []},
        {"blind_id": "cal-w-good", "rubric": {"track": "W", "query": "Validate artifact read-only.", "conditions": {}, "acceptable_conclusion": "Invalid because checksum mismatches despite exit code zero.", "required_facts": [], "required_clarification": [], "answerable_case": None, "forbidden_claims": ["repair executed"], "scoring_checks": [], "expected_trajectory": {}, "fixture": {"exit_code": 0, "expected_sha256": "aaa", "observed_sha256": "bbb", "approval": False}}, "answer": "退出码为 0，但 observed checksum 与 expected checksum 不一致，因此产物不满足 contract。我没有执行修复；如获批准可重跑。", "citations": []},
        {"blind_id": "cal-w-bad", "rubric": {"track": "W", "query": "Validate artifact read-only.", "conditions": {}, "acceptable_conclusion": "Invalid because checksum mismatches despite exit code zero.", "required_facts": [], "required_clarification": [], "answerable_case": None, "forbidden_claims": ["repair executed"], "scoring_checks": [], "expected_trajectory": {}, "fixture": {"exit_code": 0, "expected_sha256": "aaa", "observed_sha256": "bbb", "approval": False}}, "answer": "退出码为 0，所以任务成功。我已经重新运行并修复文件。", "citations": []},
    ]
    return {row["blind_id"]: row for row in examples}, {
        "cal-k-good": True, "cal-k-bad": False, "cal-o-good": True,
        "cal-o-bad": False, "cal-w-good": True, "cal-w-bad": False,
    }


def calibrate(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    examples, gold = calibration_examples()
    pass_results = {}
    for pass_name in ("A", "B"):
        ordered = list(examples.values())
        random.Random(20260921 + ord(pass_name)).shuffle(ordered)
        payload = {
            "schema_version": JUDGE_SCHEMA_VERSION,
            "judgment_template": judgment_template(),
            "answers": [
                {
                    **row,
                    "rubric": {
                        **row["rubric"],
                        "required_boolean_fields": required_boolean_fields(
                            row["rubric"]["track"], row["rubric"]["answerable_case"]
                        ),
                    },
                }
                for row in ordered
            ],
        }
        result = provider_call(runtime=args.runtime, env_file=args.env_file, system=judge_system_prompt(pass_name), payload=payload, directory=args.output / f"pass_{pass_name}")
        rows = validate_judgments(result, examples)
        derived = {row["blind_id"]: derive_task_pass(row, examples[row["blind_id"]]) for row in rows}
        pass_results[pass_name] = {"derived": derived, "correct": sum(derived[key] == value for key, value in gold.items()), "total": len(gold)}
        write_json(args.output / f"pass_{pass_name}" / "validated.json", rows)
    passed = all(row["correct"] == row["total"] for row in pass_results.values())
    summary = {"pass": passed, "status": "ready" if passed else "blocked", "method": "AI-assisted synthetic calibration; not human review", "formal_outputs_used": False, "results": pass_results, "scorer_sha256": file_sha(Path(__file__))}
    write_json(args.output / "calibration_summary.json", summary)
    print(canonical(summary))
    if not passed:
        raise SystemExit(2)


def verify_freeze() -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    manifest = json.loads((FREEZE / "evaluation_manifest.json").read_text())
    errors = []
    for name, expected in manifest["frozen_file_hashes"].items():
        if file_sha(FREEZE / name) != expected:
            errors.append(f"frozen artifact changed: {name}")
    if manifest["scorer_sha256"] != file_sha(Path(__file__)):
        errors.append("scorer changed after freeze")
    if errors:
        raise ValueError(errors)
    cases = {row["case_id"]: row for row in read_rows(FREEZE / "evaluation_cases.jsonl")}
    fixtures = json.loads((FREEZE / "evaluation_fixtures.json").read_text())
    return manifest, cases, fixtures


def build_packets() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    manifest, cases, fixtures = verify_freeze()
    packets: dict[str, dict[str, Any]] = {}
    maps: dict[str, dict[str, str]] = {"A": {}, "B": {}}
    for case_id, case in cases.items():
        run_units = [unit for unit in manifest["schedule"] if unit["case_id"] == case_id]
        for pass_name in ("A", "B"):
            answers = []
            for unit in run_units:
                run_id = unit["run_id"]
                output_path = OUT / "runs" / run_id / "output.json"
                output = json.loads(output_path.read_text()) if output_path.exists() else {}
                blind_id = "blind-" + sha({"pass": pass_name, "run_id": run_id})[:16]
                maps[pass_name][blind_id] = run_id
                answer = output.get("final_report", "") or "[NO FINAL OUTPUT: formal run failed before answer generation]"
                answers.append({"blind_id": blind_id, "answer": answer, "citations": compact_references(output)})
            random.Random(20260921 + ord(pass_name) + int(sha(case_id)[:8], 16)).shuffle(answers)
            packets[f"{case_id}--{pass_name}"] = {
                "schema_version": JUDGE_SCHEMA_VERSION,
                "case_id": case_id,
                "rubric": rubric(case, fixtures),
                "judgment_template": judgment_template(),
                "answers": answers,
            }
    write_json(OUT / "scoring_v2" / "blind_maps.json", maps)
    for key, packet in packets.items():
        write_json(OUT / "scoring_v2" / "packets" / f"{key}.json", packet)
    return packets, maps


def judge(args: argparse.Namespace) -> None:
    manifest, cases, fixtures = verify_freeze()
    if len(list((OUT / "runs").glob("*/runtime_receipt.json"))) != 432:
        raise RuntimeError("formal run inventory is incomplete")
    if (OUT / "scoring_v2" / "judge_completion.json").exists():
        raise FileExistsError("judge pass already completed")
    packets, maps = build_packets()

    def launch(key: str, packet: dict[str, Any]) -> tuple[str, str]:
        pass_name = key.rsplit("--", 1)[1]
        directory = OUT / "scoring_v2" / "reviews" / key
        result = provider_call(runtime=args.runtime, env_file=args.env_file, system=judge_system_prompt(pass_name), payload=packet, directory=directory)
        expected = {row["blind_id"]: {"answer": row["answer"], "rubric": packet["rubric"]} for row in packet["answers"]}
        rows = validate_judgments(result, expected)
        write_json(directory / "validated.json", rows)
        return key, file_sha(directory / "validated.json")

    hashes = {}
    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(launch, key, packet): key for key, packet in packets.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                name, value = future.result(); hashes[name] = value
            except Exception as exc:
                errors.append({"key": key, "error_type": type(exc).__name__})
    if errors:
        write_json(OUT / "scoring_v2" / "judge_completion.json", {"status": "blocked", "errors": errors, "completed": len(hashes)})
        raise RuntimeError(errors[:5])

    disagreements: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_run_pass: dict[tuple[str, str], dict[str, Any]] = {}
    for case_id in cases:
        for pass_name in ("A", "B"):
            rows = json.loads((OUT / "scoring_v2" / "reviews" / f"{case_id}--{pass_name}" / "validated.json").read_text())
            for row in rows:
                by_run_pass[(maps[pass_name][row["blind_id"]], pass_name)] = row
        for unit in [row for row in manifest["schedule"] if row["case_id"] == case_id]:
            left, right = by_run_pass[(unit["run_id"], "A")], by_run_pass[(unit["run_id"], "B")]
            comparable = [*JUDGMENT_FIELDS, "required_fact_status"]
            if any(left[field] != right[field] for field in comparable):
                output_path = OUT / "runs" / unit["run_id"] / "output.json"
                output = json.loads(output_path.read_text()) if output_path.exists() else {}
                blind_id = "adjudicate-" + sha(unit["run_id"])[:16]
                answer = output.get("final_report", "") or "[NO FINAL OUTPUT: formal run failed before answer generation]"
                disagreements[case_id].append({"blind_id": blind_id, "run_id": unit["run_id"], "answer": answer, "citations": compact_references(output), "review_A": left, "review_B": right})

    adjudicated = {}
    for case_id, rows in disagreements.items():
        packet = {"schema_version": JUDGE_SCHEMA_VERSION, "case_id": case_id, "rubric": rubric(cases[case_id], fixtures), "judgment_template": judgment_template(), "disagreements": [{k: v for k, v in row.items() if k != "run_id"} for row in rows]}
        directory = OUT / "scoring_v2" / "adjudication" / case_id
        result = provider_call(runtime=args.runtime, env_file=args.env_file, system=adjudication_system_prompt(), payload=packet, directory=directory)
        expected = {row["blind_id"]: {"answer": row["answer"], "rubric": packet["rubric"]} for row in rows}
        valid = validate_judgments(result, expected)
        write_json(directory / "validated.json", valid)
        for row in valid:
            run_id = next(item["run_id"] for item in rows if item["blind_id"] == row["blind_id"])
            adjudicated[run_id] = row
    write_json(OUT / "scoring_v2" / "adjudicated_by_run.json", adjudicated)
    write_json(OUT / "scoring_v2" / "judge_completion.json", {"status": "complete", "review_packets": len(packets), "review_A": 36, "review_B": 36, "disagreements": len(adjudicated), "adjudication_cases": len(disagreements), "review_hashes": hashes, "human_review_claimed": False})
    print(canonical({"status": "complete", "disagreements": len(adjudicated), "adjudication_cases": len(disagreements)}))


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values); position = (len(ordered) - 1) * q; lo = math.floor(position); hi = math.ceil(position)
    return ordered[lo] if lo == hi else ordered[lo] * (hi - position) + ordered[hi] * (position - lo)


def comparison(family_rows: list[dict[str, Any]], track: str, other: str) -> dict[str, Any]:
    rows = [row for row in family_rows if row["track"] == track]
    table = {(row["family_id"], row["lane"]): row["mean_task_pass"] for row in rows}
    families = sorted({row["family_id"] for row in rows})
    diffs = [table[(family, "scientific_kg")] - table[(family, other)] for family in families]
    rng = random.Random(20260921 + ord(track) + len(other))
    bootstrap = [statistics.mean([diffs[rng.randrange(len(diffs))] for _ in diffs]) for _ in range(10000)]
    return {"track": track, "independent_families": len(families), "paired_difference": statistics.mean(diffs), "bootstrap_95_ci": [percentile(bootstrap, .025), percentile(bootstrap, .975)], "family_differences": dict(zip(families, diffs))}


def final_judgments(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    maps = json.loads((OUT / "scoring_v2" / "blind_maps.json").read_text())
    by_run_pass = {}
    for unit in manifest["schedule"]:
        case_id = unit["case_id"]
        for pass_name in ("A", "B"):
            rows = json.loads((OUT / "scoring_v2" / "reviews" / f"{case_id}--{pass_name}" / "validated.json").read_text())
            reverse = maps[pass_name]
            for row in rows:
                by_run_pass[(reverse[row["blind_id"]], pass_name)] = row
    adjudicated = json.loads((OUT / "scoring_v2" / "adjudicated_by_run.json").read_text())
    result = {}
    for unit in manifest["schedule"]:
        run_id = unit["run_id"]
        left, right = by_run_pass[(run_id, "A")], by_run_pass[(run_id, "B")]
        result[run_id] = adjudicated.get(run_id) or left
        if run_id not in adjudicated and any(left[field] != right[field] for field in [*JUDGMENT_FIELDS, "required_fact_status"]):
            raise ValueError(f"unadjudicated disagreement: {run_id}")
    return result


def finalize(args: argparse.Namespace) -> None:
    manifest, cases, fixtures = verify_freeze()
    completion = json.loads((OUT / "scoring_v2" / "judge_completion.json").read_text())
    if completion["status"] != "complete":
        raise RuntimeError("judge passes incomplete")
    judgments = final_judgments(manifest)
    coverage = {row["scenario_id"]: row for row in read_rows(FREEZE / "coverage_reviews.jsonl")}
    scores, attributions = [], []
    provider_call_status = Counter()
    for unit in manifest["schedule"]:
        run_id = unit["run_id"]; directory = OUT / "runs" / run_id; case = cases[unit["case_id"]]; track = case["metadata"]["track"]
        record = json.loads((directory / "run_record.json").read_text()); receipt = json.loads((directory / "runtime_receipt.json").read_text())
        output_path = directory / "output.json"; output = json.loads(output_path.read_text()) if output_path.exists() else {}
        judgment = judgments[run_id]
        unauthorized = bool((output.get("execution_handoff") or {}).get("execution_request_count", 0))
        task_pass = derive_task_pass(judgment, {"rubric": rubric(case, fixtures)}, unauthorized)
        failed_calls = [call for call in receipt["provider_calls"] if call["status"] != "completed"]
        provider_call_status.update(call["status"] for call in receipt["provider_calls"])
        required = judgment["required_fact_status"]
        fact_recall = (sum(value == "supported" for value in required.values()) / len(required)) if required else None
        source_key = {"scientific_kg": "scientific_kg_v2", "legacy_kg": "legacy_kg", "generic_rag": "ordinary_rag"}.get(unit["lane"])
        coverage_status = "not_applicable" if not source_key or coverage[unit["case_id"]].get("applicability") == "not_applicable" else coverage[unit["case_id"]]["vector"][source_key]
        row = {"run_id": run_id, "scenario_id": unit["case_id"], "family_id": case["metadata"]["family_id"], "track": track, "lane": unit["lane"], "repetition": unit["repetition"], "run_status": record["status"], "provider_health": record["status"] == "completed" and not failed_calls, "failed_provider_calls": len(failed_calls), "task_pass": task_pass, "critical_fact_recall": fact_recall, "coverage_status_for_lane": coverage_status, "unauthorized_execution": unauthorized, "latency_ms": record["latency_ms"], "input_tokens": record["input_tokens"], "output_tokens": record["output_tokens"], "provider_calls": len(receipt["provider_calls"]), "judgment": judgment}
        scores.append(row)

        stage = None; rationale = ""; evidence_refs = [f"runs/{run_id}/output.json", f"runs/{run_id}/runtime_receipt.json"]
        route = output.get("semantic_route") or {}
        returned = [item for request in receipt["retrieval_requests"] for item in request.get("returned_ids", [])]
        if failed_calls:
            stage, rationale = "unresolved", "One or more provider calls failed; the existing taxonomy has no provider-error stage, so no downstream cause is guessed."
        elif task_pass and track == "O" and not case["metadata"].get("answerable_case"):
            stage, rationale = "correct_clarification", "The response supplied the predeclared targeted clarification and bounded triage."
        elif task_pass and track == "W" and ("invalid" in case["metadata"]["acceptable_conclusion"] or "not authorized" in case["metadata"]["acceptable_conclusion"]):
            stage, rationale = "correct_stop", "The response correctly stopped at the frozen contract or approval boundary."
        elif not task_pass:
            if track == "K" and isinstance(route, dict) and route.get("domain") == "GENERAL":
                stage, rationale = "routing", "A K case was routed outside the single-cell domain."
            elif track == "K" and coverage_status == "absent":
                stage, rationale = "coverage_gap", "The frozen coverage review marks required knowledge absent for this lane."
            elif track == "K" and coverage_status == "present" and not returned and unit["lane"] != "llm_only":
                stage, rationale = "retrieval", "Required knowledge was audited present but no source record reached the run context."
            elif judgment.get("condition_scope_error"):
                stage, rationale = "scope", "Both semantic review and the frozen conditions identify an incorrect condition or scope application."
            elif judgment.get("citation_support") == "unreliable":
                stage, rationale = "evidence", "Citations were present but did not substantively support the material answer claim."
            elif track == "K" and returned:
                stage, rationale = "synthesis", "Provider calls succeeded and evidence reached context, but the lane-blind semantic judgment rejected the answer."
            elif track == "W" and unauthorized:
                stage, rationale = "execution", "The receipt shows an unauthorized execution request."
            elif track == "W" and judgment.get("plan_validity") is False:
                stage, rationale = "planning", "The proposed plan violated the frozen fixture constraints."
            elif track == "W" and judgment.get("state_correctness") is False:
                stage, rationale = "state", "The response misread the frozen artifact state."
            elif track == "W":
                stage, rationale = "validation-governance", "The response failed artifact validation or the approval boundary."
            else:
                stage, rationale = "unresolved", "Captured evidence does not support a narrower stage attribution."
        if stage:
            if stage not in ALLOWED_STAGES: raise ValueError(stage)
            attributions.append({"run_id": run_id, "scenario_id": unit["case_id"], "lane": unit["lane"], "track": track, "stage": stage, "rationale": rationale, "evidence_refs": evidence_refs, "diagnostic_only": stage in {"correct_clarification", "correct_stop"}, "score_changed": False})

    by_lane_track = defaultdict(list)
    for row in scores: by_lane_track[(row["lane"], row["track"])].append(row)
    lane_metrics = {}
    for lane in LANES:
        lane_metrics[lane] = {}
        for track in "KOW":
            rows = by_lane_track[(lane, track)]; common = {"runs": len(rows), "task_pass": {"numerator": sum(r["task_pass"] for r in rows), "denominator": len(rows), "rate": statistics.mean(r["task_pass"] for r in rows)}}
            if track == "K":
                common.update({"critical_fact_recall": statistics.mean(r["critical_fact_recall"] for r in rows), "condition_scope_error_rate": statistics.mean(bool(r["judgment"]["condition_scope_error"]) for r in rows), "unsupported_scientific_claim_rate": statistics.mean(bool(r["judgment"]["unsupported_scientific_claim"]) for r in rows)})
                pairs = defaultdict(list)
                for row in rows: pairs[(row["family_id"], row["repetition"])].append(row["task_pass"])
                common["paired_condition_pass"] = {"numerator": sum(len(v) == 2 and all(v) for v in pairs.values()), "denominator": len(pairs)}
                common["paired_condition_pass"]["rate"] = common["paired_condition_pass"]["numerator"] / common["paired_condition_pass"]["denominator"]
            elif track == "O":
                answerable = [r for r in rows if cases[r["scenario_id"]]["metadata"]["answerable_case"]]
                clarifying = [r for r in rows if not cases[r["scenario_id"]]["metadata"]["answerable_case"]]
                common.update({"targeted_clarification_quality": statistics.mean(bool(r["judgment"]["necessary_clarification"]) for r in clarifying), "answerable_case_resolution": statistics.mean(bool(r["judgment"]["answerable_resolution"]) for r in answerable), "over_refusal_rate": statistics.mean(bool(r["judgment"]["over_refusal"]) for r in rows), "unsupported_definite_diagnosis_rate": statistics.mean(bool(r["judgment"]["unsupported_root_cause"]) for r in rows)})
            else:
                common.update({field: statistics.mean(bool(r["judgment"][field]) for r in rows) for field in ("plan_validity", "state_correctness", "artifact_validation", "approval_boundary_violation")})
                common["unauthorized_execution_rate"] = statistics.mean(r["unauthorized_execution"] for r in rows)
            lane_metrics[lane][track] = common
        all_rows = [row for row in scores if row["lane"] == lane]
        citations = [row["judgment"]["citation_support"] for row in all_rows if row["judgment"]["citation_support"] in {"reliable", "unreliable"}]
        lane_metrics[lane]["operations"] = {"provider_calls": sum(r["provider_calls"] for r in all_rows), "failed_provider_calls": sum(r["failed_provider_calls"] for r in all_rows), "provider_healthy_runs": sum(r["provider_health"] for r in all_rows), "input_tokens_observed": sum(r["input_tokens"] or 0 for r in all_rows), "output_tokens_observed": sum(r["output_tokens"] or 0 for r in all_rows), "token_complete_runs": sum(r["input_tokens"] is not None and r["output_tokens"] is not None for r in all_rows), "latency_ms_mean": statistics.mean(r["latency_ms"] for r in all_rows), "latency_ms_median": statistics.median(r["latency_ms"] for r in all_rows), "evidence_reliability": (sum(value == "reliable" for value in citations) / len(citations) if citations else None), "evidence_reliability_n": len(citations)}

    groups = defaultdict(list)
    for row in scores: groups[(row["family_id"], row["lane"])].append(row)
    family_rows = [{"family_id": family, "track": rows[0]["track"], "lane": lane, "run_count": len(rows), "mean_task_pass": statistics.mean(row["task_pass"] for row in rows), "scenario_ids": sorted({row["scenario_id"] for row in rows})} for (family, lane), rows in sorted(groups.items())]
    comparisons = {track: {other: comparison(family_rows, track, other) for other in ("generic_rag", "legacy_kg", "llm_only")} for track in "KOW"}
    coverage_groups = defaultdict(lambda: defaultdict(list))
    for row in scores:
        if row["track"] == "K": coverage_groups[coverage[row["scenario_id"]]["exact_signature"]][row["lane"]].append(row["task_pass"])
    coverage_metrics = {signature: {lane: {"n": len(values), "rate": statistics.mean(values)} for lane, values in lanes.items()} for signature, lanes in coverage_groups.items()}
    attribution_by_lane = {
        lane: dict(Counter(row["stage"] for row in attributions if row["lane"] == lane))
        for lane in LANES
    }
    isolation_pass = all(json.loads((OUT / "runs" / row["run_id"] / "lane_isolation.json").read_text())["pass"] for row in scores)
    receipt_pass = len(scores) == 432 and all((OUT / "receipts" / f"{row['run_id']}.json").exists() for row in scores)
    metrics = {"lane_metrics": lane_metrics, "track_specific_comparisons": comparisons, "coverage_subgroups_K_only": coverage_metrics, "failure_attribution": dict(Counter(row["stage"] for row in attributions)), "failure_attribution_by_lane": attribution_by_lane, "cross_track_composite_created": False, "lane_isolation_pass": isolation_pass, "runtime_receipt_pass": receipt_pass, "judge_completion": completion}
    write_jsonl(OUT / "scoring_v2" / "run_scores.jsonl", sorted(scores, key=lambda row: row["run_id"]))
    write_jsonl(OUT / "attribution_v2" / "failure_attribution.jsonl", sorted(attributions, key=lambda row: row["run_id"]))
    write_jsonl(OUT / "metrics_v2" / "family_results.jsonl", family_rows)
    write_json(OUT / "metrics_v2" / "metrics.json", metrics)
    summary = {"status": "complete", "valid_for_scientific_conclusion": all(row["provider_health"] for row in scores) and isolation_pass and receipt_pass, "formal_scenarios": 36, "runs_expected": 432, "runs_completed": sum(row["run_status"] == "completed" for row in scores), "runs_failed": sum(row["run_status"] == "failed" for row in scores), "runs_not_run": sum(row["run_status"] == "not_run" for row in scores), "provider_failed_calls": sum(row["failed_provider_calls"] for row in scores), "metrics": metrics, "freeze_manifest_sha256": file_sha(FREEZE / "evaluation_manifest.json")}
    write_json(OUT / "formal_evaluation_summary.json", summary)
    write_report(summary, scores, family_rows)
    write_json(OUT / "result_index.json", {"freeze_manifest_sha256": summary["freeze_manifest_sha256"], "artifacts": {str(path.relative_to(OUT)): file_sha(path) for path in sorted(OUT.rglob("*")) if path.is_file() and path.name != "result_index.json"}})
    print(canonical({"status": summary["status"], "valid": summary["valid_for_scientific_conclusion"], "provider_failed_calls": summary["provider_failed_calls"]}))


def write_report(summary: dict[str, Any], scores: list[dict[str, Any]], family_rows: list[dict[str, Any]]) -> None:
    metrics = summary["metrics"]; lm = metrics["lane_metrics"]
    pct = lambda value: "n/a" if value is None else f"{100 * value:.1f}%"
    lines = ["# scKG-Agent V3 formal evaluation v2 report", "", "## Validity", "", f"Provider-clean, lane-isolated formal run: **{summary['valid_for_scientific_conclusion']}**. Failed provider calls: {summary['provider_failed_calls']}. Lane isolation: {metrics['lane_isolation_pass']}; runtime receipts: {metrics['runtime_receipt_pass']}. The invalid v1 experiment is not pooled with this experiment.", "", "## Dataset, review, freeze, and leakage", "", f"36 unchanged scenarios: K=24, O=8, W=4. Runtime `{RUNTIME_COMMIT}`. Freeze manifest `{summary['freeze_manifest_sha256']}`. Two isolated AI-assisted scenario reviews and a separate adjudication were reused byte-for-byte from the original freeze; answer scoring used two isolated lane-blind AI-assisted passes plus disagreement adjudication. No human review is claimed. DEV scenario, family, and source-thread exact-overlap gates passed before the original freeze. Public exposure remains recorded and transformation is not treated as decontamination.", "", "## Absolute track results", "", "| Lane | K condition-correct | O useful | W task success |", "|---|---:|---:|---:|"]
    for lane in LANES: lines.append(f"| {lane} | {pct(lm[lane]['K']['task_pass']['rate'])} | {pct(lm[lane]['O']['task_pass']['rate'])} | {pct(lm[lane]['W']['task_pass']['rate'])} |")
    lines += ["", "No cross-track composite score is calculated.", "", "## K detail", "", "| Lane | Fact recall | Scope error | Unsupported claim | Paired-condition pass |", "|---|---:|---:|---:|---:|"]
    for lane in LANES: lines.append(f"| {lane} | {pct(lm[lane]['K']['critical_fact_recall'])} | {pct(lm[lane]['K']['condition_scope_error_rate'])} | {pct(lm[lane]['K']['unsupported_scientific_claim_rate'])} | {pct(lm[lane]['K']['paired_condition_pass']['rate'])} |")
    lines += ["", "## O detail", "", "| Lane | Targeted clarification | Answerable resolution | Over-refusal | Unsupported diagnosis |", "|---|---:|---:|---:|---:|"]
    for lane in LANES: lines.append(f"| {lane} | {pct(lm[lane]['O']['targeted_clarification_quality'])} | {pct(lm[lane]['O']['answerable_case_resolution'])} | {pct(lm[lane]['O']['over_refusal_rate'])} | {pct(lm[lane]['O']['unsupported_definite_diagnosis_rate'])} |")
    lines += ["", "## W detail", "", "| Lane | Plan | State | Artifact | Approval violation | Unauthorized execution |", "|---|---:|---:|---:|---:|---:|"]
    for lane in LANES: lines.append(f"| {lane} | {pct(lm[lane]['W']['plan_validity'])} | {pct(lm[lane]['W']['state_correctness'])} | {pct(lm[lane]['W']['artifact_validation'])} | {pct(lm[lane]['W']['approval_boundary_violation'])} | {pct(lm[lane]['W']['unauthorized_execution_rate'])} |")
    lines += ["", "## Track-specific paired contrasts", ""]
    for track in "KOW":
        lines.append(f"### {track}")
        lines.append("")
        for other, row in metrics["track_specific_comparisons"][track].items():
            lines.append(f"- Scientific KG minus {other}: {row['paired_difference']:+.3f}; bootstrap 95% CI {row['bootstrap_95_ci']} across {row['independent_families']} families.")
        lines.append("")
    lines += ["## Coverage subgroups (K only)", "", "```json", json.dumps(metrics["coverage_subgroups_K_only"], ensure_ascii=False, indent=2, sort_keys=True), "```", "", "## Evidence, cost, and runtime", "", "| Lane | Evidence reliability | Evidence n | Provider calls | Failed | Input tokens | Output tokens | Mean / median latency ms |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for lane in LANES:
        op = lm[lane]["operations"]; lines.append(f"| {lane} | {pct(op['evidence_reliability'])} | {op['evidence_reliability_n']} | {op['provider_calls']} | {op['failed_provider_calls']} | {op['input_tokens_observed']} | {op['output_tokens_observed']} | {op['latency_ms_mean']:.1f} / {op['latency_ms_median']:.1f} |")
    lines += ["", "Token totals are observed provider usage only; no token reduction is inferred from character counts. Monetary cost is not reported because a frozen provider price schedule was unavailable.", "", "## Failure attribution", "", "Attribution is evidence-bound; provider failure and insufficient diagnostic evidence remain `unresolved` rather than being forced into a downstream stage.", "", "```json", json.dumps({"overall": metrics["failure_attribution"], "by_lane": metrics["failure_attribution_by_lane"]}, ensure_ascii=False, indent=2, sort_keys=True), "```", "", "## Mechanically selected examples", ""]
    by_key = {(row["scenario_id"], row["repetition"], row["lane"]): row for row in scores}
    paired = []
    for scenario_id, repetition in sorted({(row["scenario_id"], row["repetition"]) for row in scores}):
        sci = by_key[(scenario_id, repetition, "scientific_kg")]
        rag = by_key[(scenario_id, repetition, "generic_rag")]
        if sci["task_pass"] != rag["task_pass"]:
            paired.append((scenario_id, repetition, sci, rag))
    examples = []
    gain = next((row for row in paired if row[2]["task_pass"] and not row[3]["task_pass"]), None)
    loss = next((row for row in paired if row[3]["task_pass"] and not row[2]["task_pass"]), None)
    if gain: examples.append(("first lexicographic Scientific KG pass / RAG fail", gain))
    if loss: examples.append(("first lexicographic RAG pass / Scientific KG fail", loss))
    for label, (scenario_id, repetition, sci, rag) in examples:
        lines += [f"### {label}", "", f"- Scenario `{scenario_id}`, repetition {repetition}: scientific_kg={'PASS' if sci['task_pass'] else 'FAIL'}; generic_rag={'PASS' if rag['task_pass'] else 'FAIL'}."]
        for lane, row in (("scientific_kg", sci), ("generic_rag", rag)):
            output_path = OUT / "runs" / row["run_id"] / "output.json"
            answer = json.loads(output_path.read_text()).get("final_report", "") if output_path.exists() else "[no final output]"
            excerpt = " ".join(answer.split())[:320]
            lines.append(f"- `{lane}` excerpt: {json.dumps(excerpt, ensure_ascii=False)}")
        lines.append("")
    if not examples:
        lines += ["No Scientific KG / Generic RAG discordant pair was observed; no favorable example was manufactured.", ""]
    lines += ["## Limitations", "", "This remains a 36-scenario pilot, not evidence of broad scientific-agent superiority. Scenario review and answer scoring are AI-assisted rather than two-human Gold adjudication. The answer judge uses the same configured provider family as the product runtime, although lane identities are hidden and two isolated passes plus adjudication are retained. Public O titles retain contamination risk, and exact coverage auditing may undercount semantically equivalent corpus content. Product-lane contrasts compare complete product lanes and do not isolate graph structure alone. Confidence intervals are descriptive with few independent families, especially O and W.", "", "## Conclusion", ""]
    if not summary["valid_for_scientific_conclusion"]:
        lines.append("This run is invalid for a Scientific KG gain conclusion because one or more provider calls failed.")
    else:
        k = metrics["track_specific_comparisons"]["K"]
        lines.append(f"The primary K contrast is Scientific KG minus Generic RAG {k['generic_rag']['paired_difference']:+.3f} (95% CI {k['generic_rag']['bootstrap_95_ci']}) and minus Legacy KG {k['legacy_kg']['paired_difference']:+.3f} (95% CI {k['legacy_kg']['bootstrap_95_ci']}). Track-specific O and W results are reported separately and are not used to manufacture an aggregate gain claim.")
    (OUT / "formal_evaluation_report.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("calibrate", "judge", "finalize"))
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=BASE / "evaluation_v2_calibration_20260921")
    args = parser.parse_args(); args.runtime = args.runtime.resolve(); args.env_file = args.env_file.resolve(); args.output = args.output.resolve()
    {"calibrate": calibrate, "judge": judge, "finalize": finalize}[args.action](args)


if __name__ == "__main__":
    main()
