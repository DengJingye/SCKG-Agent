"""Four-scenario, evaluation-only ablation of the existing planner's KG adapter.

prepare freezes inputs without calling compile; run requires passing test XMLs,
proves historical/no-op equivalence, and only then runs the four KG cases once.
Subprocess workers import all production modules from their selected checkout.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "eval/specs/scientific_kg_contribution_v1.expected.json"
SPEC_SHA256 = "6a7027c60b2cf493415f371d7ec0754e56ae480e42db86c97021cfcb8842f290"
CANDIDATE = "data/evidence_candidates/scientific_kg_v1_uat_decision_rules"
EVALUATION_LEDGER_CREATED_AT = "2000-01-01T00:00:00Z"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def load_spec():
    if file_hash(SPEC_PATH) != SPEC_SHA256:
        raise ValueError("frozen_expected_spec_digest_mismatch")
    return read(SPEC_PATH)


class NoOpApplicability:
    """A truthy explicit injected adapter, not None (which enables the default)."""

    def __init__(self):
        self.calls = []

    def assess(self, *, action_id, ledger):
        self.calls.append(action_id)
        return None


def first_difference(left, right, path="$"):
    """No list sorting, deduplication, type coercion or semantic normalization."""
    if type(left) is not type(right):
        return {"path": path, "left": left, "right": right}
    if isinstance(left, dict):
        for key in left:
            if key not in right:
                return {"path": f"{path}.{key}", "left": left[key], "right_missing": True}
            mismatch = first_difference(left[key], right[key], f"{path}.{key}")
            if mismatch:
                return mismatch
        for key in right:
            if key not in left:
                return {"path": f"{path}.{key}", "left_missing": True, "right": right[key]}
    elif isinstance(left, list):
        if len(left) != len(right):
            return {"path": path + ".length", "left": len(left), "right": len(right)}
        for index, (a, b) in enumerate(zip(left, right)):
            mismatch = first_difference(a, b, f"{path}[{index}]")
            if mismatch:
                return mismatch
    elif left != right:
        return {"path": path, "left": left, "right": right}
    return None


def normalize(raw):
    value = copy.deepcopy(raw["planner_outputs"])
    value["result"].pop("scientific_applicability_results", None)
    # IDs in these planners are deterministic. No ID or timing exclusions needed.
    return value


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def requests_for(spec):
    from eval.scientific_action_space_demo_v1 import demo_scenarios
    fixtures = {key: ledger for key, _, ledger in demo_scenarios()}
    if list(fixtures) != [row["scenario_id"] for row in spec["scenarios"]]:
        raise ValueError("four_frozen_scenarios_required")
    return [{
        "scenario_id": row["scenario_id"],
        "kwargs": {
            "pack_id": spec["pack_id"], "pack_version": spec["pack_version"],
            "target_representations": [row["target"]],
            "requirement_id": "kg-contribution-v1:" + row["scenario_id"],
            "options": copy.deepcopy(spec["options"]), "data_profile": spec["data_profile"],
            "ledger": fixtures[row["scenario_id"]].model_dump(mode="json"),
        },
    } for row in spec["scenarios"]]


def frozen_requests(spec):
    """Materialize one deterministic request set for every checkout/lane.

    ``RepresentationLedger.created_at`` is operational creation metadata, not
    scientific fixture state. The production model keeps its dynamic default;
    only the serialized evaluation input receives this fixed value.
    """
    requests = requests_for(spec)
    for request in requests:
        request["kwargs"]["ledger"]["created_at"] = EVALUATION_LEDGER_CREATED_AT
    return requests


def snapshot(root, spec, requests):
    from core.capability_pack_registry import CapabilityPackRegistry
    from core.tool_contract_registry import ToolContractRegistry
    registry = CapabilityPackRegistry()
    tool_registry = ToolContractRegistry()
    manifest = registry.load(spec["pack_id"], spec["pack_version"])
    contracts = registry.load_step_contracts(manifest)
    pack = root / "capability_packs" / spec["pack_id"] / spec["pack_version"]
    files = {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(pack.rglob("*")) if p.is_file()}
    tools = {}
    for contract_id in sorted({s.tool_contract_id for s in contracts.values()}):
        if ":" not in contract_id or contract_id.startswith(("human-review:", "method-family:", "action:")):
            tools[contract_id] = {"load_status": "not_a_tool_contract"}
            continue
        name, version = contract_id.split(":", 1)
        p = root / "contracts/tools" / name.casefold() / f"{version}.json"
        files[p.relative_to(root).as_posix()] = file_hash(p)
        tools[contract_id] = tool_registry.load(name, version).model_dump(mode="json")
    # Freeze the source-bound candidate and relevant shared implementation inputs.
    for folder in (root / CANDIDATE,):
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                files[p.relative_to(root).as_posix()] = file_hash(p)
    for name in ("eval/scientific_action_space_demo_v1.py", "core/capability_pack_models.py",
                 "core/capability_pack_registry.py", "core/tool_contract_registry.py",
                 "core/execution_models.py", "core/research_workspace_models.py"):
        files[name] = file_hash(root / name)
    return {
        "requests": copy.deepcopy(requests), "file_sha256": files,
        "manifest": manifest.model_dump(mode="json"),
        "step_contracts": {key: value.model_dump(mode="json") for key, value in contracts.items()},
        "tool_contracts": tools,
        "environment": {"python": sys.version, "pydantic": importlib.metadata.version("pydantic"),
                        "execution_policy": os.environ.get("SCKG_EXECUTION_POLICY"),
                        "external_network_allowed": os.environ.get("SCKG_EXTERNAL_NETWORK_ALLOWED")},
    }


def compile_request(request, lane):
    from core.representation_models import RepresentationLedger
    from engine.capability_planner import CapabilityPlanCompiler
    kwargs = copy.deepcopy(request["kwargs"])
    kwargs["ledger"] = RepresentationLedger.model_validate(kwargs["ledger"])
    before = kwargs["ledger"].model_dump(mode="json")
    adapter = NoOpApplicability() if lane == "noop" else None
    planner = CapabilityPlanCompiler(scientific_applicability=adapter) if adapter is not None else CapabilityPlanCompiler()
    plan, result = planner.compile(**kwargs)
    after = kwargs["ledger"].model_dump(mode="json")
    if first_difference(before, after):
        raise ValueError("planner_mutated_ledger")
    # Resolve exactly the records used by the compiler's current-record mapping.
    current = {r["representation_id"]: r for r in before["records"] if r["status"] == "current" and r["validated"]}
    reused = [current[key] for key in result.reused_representation_ids]
    return {
        "scenario_id": request["scenario_id"],
        "planner_outputs": {"plan": plan.model_dump(mode="json"), "result": result.model_dump(mode="json"),
                            "resolved_reused_ledger_records": reused},
        "ledger_before_sha256": digest(before), "ledger_after_sha256": digest(after),
        "noop_assess_calls": adapter.calls if adapter is not None else None,
    }


def worker(root, command, payload):
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
    env.update({"SCKG_ENV_FILE": "/dev/null", "SCKG_EXECUTION_POLICY": "disabled",
                "SCKG_EXTERNAL_NETWORK_ALLOWED": "false", "SCKG_OFFLINE_LLM": "true",
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"})
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "worker", "--root", str(root),
                           "--command", command], cwd=root, env=env, text=True,
                          input=json.dumps(payload), capture_output=True, check=True)
    return json.loads(proc.stdout)


def validate_tests(out):
    counts = {}
    for name, minimum in (("harness-tests.xml", 1), ("integration-tests.xml", 5)):
        tree = ET.parse(out / name)
        cases = tree.findall(".//testcase")
        if len(cases) < minimum or any(c.find(tag) is not None for c in cases for tag in ("failure", "error", "skipped")):
            raise ValueError("required_tests_not_passed:" + name)
        if name == "integration-tests.xml" and len(cases) != 5:
            raise ValueError("expected_exactly_five_integration_tests")
        counts[name] = {"passed": len(cases), "sha256": file_hash(out / name)}
    return counts


def prepare(out, pre):
    spec = load_spec()
    if git(ROOT, "rev-parse", "HEAD") != spec["current_commit"] or git(pre, "rev-parse", "HEAD") != spec["pre_kg_commit"]:
        raise ValueError("baseline_commit_mismatch")
    if git(ROOT, "diff", "--name-only", "HEAD") or git(pre, "status", "--porcelain"):
        raise ValueError("tracked_baseline_or_precheckout_dirty")
    out.mkdir(parents=True, exist_ok=False)
    canonical_requests = frozen_requests(spec)
    repeated_requests = frozen_requests(spec)
    dynamic_mismatch = first_difference(canonical_requests, repeated_requests)
    if dynamic_mismatch:
        raise ValueError(f"evaluation_fixture_not_deterministic:{dynamic_mismatch['path']}")
    write_new(out / "frozen_requests.json", canonical_requests)
    write_new(out / "freeze.json", {"expected_spec_sha256": SPEC_SHA256, "frozen_at": datetime.now(timezone.utc).isoformat(),
                                   "current_commit": spec["current_commit"], "pre_kg_commit": spec["pre_kg_commit"],
                                   "frozen_requests_sha256": digest(canonical_requests),
                                   "repeat_generation_sha256": digest(repeated_requests),
                                   "dynamic_metadata_remaining": dynamic_mismatch})
    snapshots = {}
    for label, root in (("pre_kg", pre), ("current", ROOT)):
        snapshots[label] = worker(
            root,
            "snapshot",
            {"spec": spec, "requests": canonical_requests},
        )
        write_new(out / f"{label}_inputs.json", snapshots[label])
    mismatch = first_difference(snapshots["pre_kg"], snapshots["current"])
    report = {"passed": mismatch is None, "first_mismatch": mismatch,
              "pre_kg_input_sha256": digest(snapshots["pre_kg"]), "current_input_sha256": digest(snapshots["current"]),
              "contract_and_evidence_file_count": len(snapshots["current"]["file_sha256"]),
              "request_sha256": {r["scenario_id"]: digest(r) for r in snapshots["current"]["requests"]}}
    write_new(out / "input_equivalence.json", report)
    if mismatch:
        write_new(out / "report.json", {"status": "NO-GO", "paired_status": "not_run", "first_mismatch": mismatch})
    return report


def measure(value, denominator=1):
    return {"numerator": int(value), "denominator": denominator} if denominator else "not_applicable"


def behavior(raw, expected):
    outputs = raw["planner_outputs"]
    methods = outputs["result"]["planned_method_ids"]
    reused = [r["representation_record_id"] for r in outputs["resolved_reused_ledger_records"]]
    unnecessary = [m for m in methods if m in expected["forbidden_methods"]]
    invalid = [r for r in reused if r in expected["invalid_reuse_records"]]
    inappropriate = [m for m in methods if m not in expected["expected_methods"]]
    obligations = {
        "correct_allow_block": outputs["result"]["blocked"] == expected["expected_blocked"],
        "correct_methods_and_order": methods == expected["expected_methods"],
        "correct_reuse_records": reused == expected["expected_reused_records"],
    }
    return {"obligations": obligations, "unnecessary_steps": measure(bool(unnecessary), int(bool(expected["forbidden_methods"]))),
            "invalid_reuse": measure(bool(invalid), int(bool(expected["invalid_reuse_records"]))),
            "inappropriate_scheduling": measure(bool(inappropriate)), "correct_allow_block": measure(obligations["correct_allow_block"]),
            "offending_steps": inappropriate, "unnecessary_step_count": len(unnecessary), "invalid_reused_records": invalid}


def evidence_checks(refs, root):
    bindings = {r["claim_revision_id"]: r for r in map(json.loads, (root / CANDIDATE / "exact_evidence_bindings.jsonl").read_text().splitlines())}
    spans = {r["evidence_span_id"]: r for r in map(json.loads, (root / CANDIDATE / "authoritative_evidence_spans.jsonl").read_text().splitlines())}
    checks = []
    for ref in refs:
        binding = bindings.get(ref["claim_revision_id"], {})
        span = spans.get(ref["evidence_span_id"], {})
        resolvable = bool(span and binding and span.get("source_bound") and
                          ref["evidence_span_id"] in binding.get("evidence_span_ids", []) and
                          all(ref.get(k) == span.get(k) for k in ("source_revision_id", "locator", "content_hash")) and
                          span.get("content_hash") in binding.get("evidence_excerpt_sha256", []))
        supporting = resolvable and binding.get("assessment") == "supports"
        checks.append({"reference": ref, "resolvable": resolvable, "supporting_frozen_assessment": supporting,
                       "assessment": binding.get("assessment", "missing")})
    return checks


def explanation(raw, expected, root):
    outputs = raw["planner_outputs"]
    decisions = [d for d in outputs["result"].get("scientific_applicability_results", []) if d["action_id"] == expected["action_id"]]
    reasons = list(outputs["result"]["blocking_reasons"]) + list(outputs["plan"]["blocking_conditions"])
    for d in decisions:
        reasons.extend(d["incompatibility_reasons"])
    reason_hits = [any(r == code or r.endswith(":" + code) for r in reasons for code in group) for group in expected["reason_groups"]]
    missing = [m for d in decisions for m in d["missing_requirements"]]
    missing_types = {t for m in missing for t in m["required_representation_type_ids"]}
    legacy_missing = any(r == code or r.endswith(":" + code) for r in reasons for code in expected.get("equivalent_legacy_missing_codes", []))
    missing_ok = set(expected["missing_representation_types"]) <= missing_types or legacy_missing
    linked = {r["representation_id"] for r in outputs["resolved_reused_ledger_records"]}
    linked.update(r for d in decisions for r in d["assessed_representation_ids"])
    ref_checks = evidence_checks([r for d in decisions for r in d["evidence_references"]], root)
    supported_ids = {c["reference"]["claim_revision_id"] for c in ref_checks if c["supporting_frozen_assessment"]}
    evidence_ok = set(expected["support_claim_ids"]) <= supported_ids
    metrics = {
        "specific_incompatibility_reason": measure(all(reason_hits), int(bool(reason_hits))),
        "correct_missing_requirement": measure(missing_ok, int(bool(expected["missing_representation_types"]))),
        "evaluated_representation_linkage": measure(set(expected["required_explanation_representation_ids"]) <= linked),
        "resolvable_supporting_evidence": measure(evidence_ok),
        "explicit_candidate_status": measure(bool(decisions) and all(d["knowledge_status"] == "candidate" for d in decisions)),
    }
    return {"metrics": metrics, "reason_group_results": reason_hits, "missing_requirements": missing,
            "legacy_missing_requirement_recognized": legacy_missing, "reference_checks": ref_checks,
            "evidence_interpretation": "Verifies references against previously frozen exact bindings and support assessments; not new independent scientific adjudication."}


def classify(before_b, after_b, before_e, after_e):
    pairs = list(zip(before_b["obligations"].values(), after_b["obligations"].values()))
    epairs = [(b["numerator"], after_e["metrics"][k]["numerator"]) for k, b in before_e["metrics"].items() if b != "not_applicable"]
    if any(b and not a for b, a in pairs + epairs):
        return "regression"
    if any(not b and a for b, a in pairs):
        return "behavioral improvement"
    if any(not b and a for b, a in epairs):
        return "same behavior, explanation/provenance improvement"
    return "no observed incremental contribution"


def formal_run(out, pre):
    spec = load_spec()
    if read(out / "freeze.json")["expected_spec_sha256"] != SPEC_SHA256:
        raise ValueError("freeze_mismatch")
    tests = validate_tests(out)
    if not read(out / "input_equivalence.json")["passed"]:
        raise ValueError("input_equivalence_failed")
    canonical_requests = read(out / "frozen_requests.json")
    # Exclusive claim prevents retries/overwrites after any formal invocation.
    write_new(out / "run_started.json", {"started_at": datetime.now(timezone.utc).isoformat(), "tests": tests})
    for label, root, commit in (("pre_kg", pre, spec["pre_kg_commit"]), ("current", ROOT, spec["current_commit"])):
        if git(root, "rev-parse", "HEAD") != commit or git(root, "diff", "--name-only", "HEAD"):
            raise ValueError("baseline_changed")
        mismatch = first_difference(
            read(out / f"{label}_inputs.json"),
            worker(
                root,
                "snapshot",
                {"spec": spec, "requests": canonical_requests},
            ),
        )
        if mismatch:
            report = {"status": "NO-GO", "paired_status": "not_run", "first_mismatch": mismatch}
            write_new(out / "report.json", report)
            return report
    requests = canonical_requests
    rows, baseline = [], {}
    for request in requests:
        key = request["scenario_id"]
        raws = {}
        for lane, root in (("pre_kg", pre), ("noop", ROOT)):
            raw = worker(root, "compile", {"request": request, "lane": lane})
            write_new(out / "raw" / lane / f"{key}.json", raw)
            write_new(out / "normalized" / lane / f"{key}.json", normalize(raw))
            raws[lane] = raw
        baseline[key] = raws["noop"]
        mismatch = first_difference(normalize(raws["pre_kg"]), normalize(raws["noop"]))
        rows.append({"scenario_id": key, "equivalent": mismatch is None, "first_mismatch": mismatch})
        if mismatch:
            report = {"status": "NO-GO", "paired_status": "not_run", "equivalence": rows, "first_mismatch": mismatch}
            write_new(out / "equivalence.json", rows)
            write_new(out / "report.json", report)
            return report
    write_new(out / "equivalence.json", rows)
    paired = []
    for request, expected in zip(requests, spec["scenarios"]):
        key = request["scenario_id"]
        kg = worker(ROOT, "compile", {"request": request, "lane": "kg"})
        write_new(out / "raw/kg" / f"{key}.json", kg)
        write_new(out / "normalized/kg" / f"{key}.json", normalize(kg))
        b0, b1 = behavior(baseline[key], expected), behavior(kg, expected)
        e0, e1 = explanation(baseline[key], expected, ROOT), explanation(kg, expected, ROOT)
        paired.append({"scenario_id": key, "classification": classify(b0, b1, e0, e1),
                       "baseline": {"behavior": b0, "explanation": e0}, "kg_enabled": {"behavior": b1, "explanation": e1},
                       "previously_correct_behavior_regressions": [k for k, v in b0["obligations"].items() if v and not b1["obligations"][k]]})
    unchanged = {}
    for label, root in (("pre_kg", pre), ("current", ROOT)):
        unchanged[label] = first_difference(
            read(out / f"{label}_inputs.json"),
            worker(
                root,
                "snapshot",
                {"spec": spec, "requests": canonical_requests},
            ),
        ) is None
    success = all(unchanged.values()) and all(r["classification"] != "regression" and all(r["kg_enabled"]["behavior"]["obligations"].values()) for r in paired)
    report = {"schema_version": "scientific-kg-contribution-report-v1", "status": "GO" if success else "NO-GO",
              "expected_spec_sha256": SPEC_SHA256, "paired_status": "completed", "equivalence": rows,
              "input_integrity_after": unchanged, "paired": paired, "tests": tests,
              "limitations": ["Four unchanged synthetic fixtures; no population-level statistical inference.",
                              "Scientific knowledge remains candidate; supporting-reference metric uses frozen evidence assessments."]}
    write_new(out / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run", "worker"))
    parser.add_argument("--pre-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--command", choices=("snapshot", "compile"))
    args = parser.parse_args()
    if args.mode == "worker":
        root = args.root.resolve()
        sys.path.insert(0, str(root))
        payload = json.load(sys.stdin)
        result = (
            snapshot(root, payload["spec"], payload["requests"])
            if args.command == "snapshot"
            else compile_request(payload["request"], payload["lane"])
        )
    else:
        if args.output is None or args.pre_root is None:
            parser.error("--output and --pre-root are required")
        result = (prepare if args.mode == "prepare" else formal_run)(args.output.resolve(), args.pre_root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result.get("status") == "NO-GO" or result.get("passed") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
