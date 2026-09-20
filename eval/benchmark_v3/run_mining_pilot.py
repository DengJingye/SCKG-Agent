#!/usr/bin/env python3
"""Run the bounded scKG V3 real-question mining pilot.

The collector performs exactly one unauthenticated GitHub REST request for each
allowlisted repository. It stores title-level issue metadata only. It never
requests issue bodies, comments, forum posts, replies, or downstream agent
outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer


RUN_ID = "pilot-20260920-v1"
COLLECTOR_ID = "sckg-benchmark-v3-github-title-pilot"
COLLECTOR_VERSION = "1.0.0"
API_VERSION = "2026-03-10"
SELECTION_SALT = "sckg-v3-pilot-20260920"
PER_REPOSITORY_QUOTA = 20
CLUSTER_COUNT = 8

GITHUB_SOURCES = (
    {
        "owner": "scverse",
        "repo": "scanpy",
        "collection_name": "scverse/scanpy issues",
        "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms",
    },
    {
        "owner": "satijalab",
        "repo": "seurat",
        "collection_name": "satijalab/seurat issues",
        "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms",
    },
)

CONTROLLED_PROBES = (
    (
        "state-layer-selection",
        "A Scanpy object has counts in layers['counts'], normalized values in X, and an old raw snapshot. What state must be inspected before choosing the matrix for differential expression?",
        "state-and-representation",
    ),
    (
        "state-partial-notebook",
        "A notebook stopped after neighbors were recomputed but before UMAP and clustering were rerun. How should an agent determine which artifacts are stale before resuming?",
        "state-and-representation",
    ),
    (
        "scope-species-mismatch",
        "A marker list is documented for mouse, while the loaded AnnData uses human gene symbols. What scope checks are required before cell-type annotation?",
        "scope-and-evidence",
    ),
    (
        "evidence-version-conflict",
        "The installed Scanpy version and the latest online documentation describe different function parameters. Which evidence should govern an executable recommendation?",
        "scope-and-evidence",
    ),
    (
        "retrieval-out-of-knowledge",
        "A user asks about a method released after every frozen benchmark corpus snapshot. How should retrieval report the knowledge boundary without inventing support?",
        "retrieval-boundary",
    ),
    (
        "planning-authorization",
        "An analysis plan would overwrite an existing h5ad file. What approval and artifact-preservation steps are required before execution?",
        "planning-and-authorization",
    ),
    (
        "execution-package-drift",
        "A saved workflow requires a package version incompatible with the current environment. How should the agent separate plan validity from execution failure?",
        "execution-and-validation",
    ),
    (
        "validation-empty-artifact",
        "A command exits with status zero but produces an empty result table. What validation evidence is needed before reporting task completion?",
        "execution-and-validation",
    ),
)

POLICY_BLOCKED_SOURCES = (
    {
        "source": "scverse Discourse",
        "status": "prohibited",
        "reason": "Current forum Terms of Service prohibit automated access except public-search-engine indexing; no content endpoint was called.",
        "policy_url": "https://discourse.scverse.org/tos",
    },
    {
        "source": "Biostars",
        "status": "pending",
        "reason": "Access, storage, PII, and removal policy review is not complete; no endpoint was called.",
        "policy_url": "https://www.biostars.org/",
    },
    {
        "source": "Bioconductor Support",
        "status": "pending",
        "reason": "User-agreement and reuse/storage policy review is not complete; no endpoint was called.",
        "policy_url": "https://support.bioconductor.org/",
    },
)

PII_PATTERNS = (
    ("email", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[REDACTED_EMAIL]"),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
    ("home_path", re.compile(r"(?<![A-Za-z0-9])(?:/Users/|/home/)[^\s,;:'\"]+"), "[REDACTED_HOME_PATH]"),
    ("phone", re.compile(r"(?<!\w)(?:\+?\d[\d .()-]{7,}\d)(?!\w)"), "[REDACTED_PHONE]"),
    (
        "secret",
        re.compile(r"(?i)\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})\b"),
        "[REDACTED_SECRET]",
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git_output(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True
    ).stdout.strip()


def redact_title(title: str) -> tuple[str, list[str]]:
    value = unicodedata.normalize("NFC", title)
    value = re.sub(r"\s+", " ", value).strip()
    matches: list[str] = []
    for name, pattern, replacement in PII_PATTERNS:
        value, count = pattern.subn(replacement, value)
        matches.extend([name] * count)
    return value, matches


def comparison_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"\d+(?:\.\d+)*", " <number> ", normalized)
    normalized = re.sub(r"[^\w<>+.-]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def fetch_github_issues(source: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    owner = source["owner"]
    repo = source["repo"]
    params = urllib.parse.urlencode(
        {
            "state": "all",
            "sort": "created",
            "direction": "desc",
            "per_page": 100,
            "page": 1,
        }
    )
    endpoint = f"https://api.github.com/repos/{owner}/{repo}/issues?{params}"
    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "scKG-Agent-evaluation-pilot",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
        headers = {key.lower(): value for key, value in response.headers.items()}
        status = response.status
    data = json.loads(payload)
    if status != 200 or not isinstance(data, list):
        raise RuntimeError(f"GitHub endpoint failed for {owner}/{repo}: HTTP {status}")
    metadata = {
        "endpoint": endpoint,
        "http_status": status,
        "api_version": API_VERSION,
        "etag": headers.get("etag", ""),
        "last_modified": headers.get("last-modified", ""),
        "rate_limit_limit": headers.get("x-ratelimit-limit", ""),
        "rate_limit_remaining": headers.get("x-ratelimit-remaining", ""),
        "rate_limit_reset": headers.get("x-ratelimit-reset", ""),
        "response_sha256": sha256_bytes(payload),
        "response_items": len(data),
    }
    return data, metadata


def eligible_issue(item: dict[str, Any]) -> bool:
    if "pull_request" in item or not str(item.get("title", "")).strip():
        return False
    user = item.get("user") or {}
    login = str(user.get("login", "")).casefold()
    return user.get("type") != "Bot" and not login.endswith("[bot]")


def rank_issue(source: dict[str, str], item: dict[str, Any]) -> str:
    stable_key = f"{SELECTION_SALT}|{source['owner']}/{source['repo']}|{item['number']}"
    return sha256_text(stable_key)


def github_seed(
    source: dict[str, str], item: dict[str, Any], collection: dict[str, Any], collected_at: str
) -> dict[str, Any]:
    owner, repo = source["owner"], source["repo"]
    raw_title = str(item["title"])
    redacted_title, pii_matches = redact_title(raw_title)
    if not redacted_title:
        raise ValueError(f"Issue {owner}/{repo}#{item['number']} has an empty title after redaction")
    minimal_projection = {
        "number": item["number"],
        "title": raw_title,
        "html_url": item["html_url"],
        "state": item["state"],
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
        "labels": sorted(str(label.get("name", "")) for label in item.get("labels", [])),
    }
    raw_record_sha = sha256_bytes(canonical_json_bytes(minimal_projection))
    raw_title_sha = sha256_text(raw_title)
    normalized_title = re.sub(r"\s+", " ", unicodedata.normalize("NFC", raw_title)).strip()
    normalized_title_sha = sha256_text(normalized_title)
    final_sha = sha256_text(redacted_title)
    history = [
        {
            "sequence": 1,
            "operation": "title_extraction",
            "performed_at": collected_at,
            "tool_id": COLLECTOR_ID,
            "tool_version": COLLECTOR_VERSION,
            "input_sha256": raw_record_sha,
            "output_sha256": raw_title_sha,
            "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.",
        },
        {
            "sequence": 2,
            "operation": "whitespace_normalization",
            "performed_at": collected_at,
            "tool_id": COLLECTOR_ID,
            "tool_version": COLLECTOR_VERSION,
            "input_sha256": raw_title_sha,
            "output_sha256": normalized_title_sha,
            "notes": "Applied NFC normalization and folded whitespace without changing case or wording.",
        },
    ]
    if pii_matches:
        history.append(
            {
                "sequence": 3,
                "operation": "pii_redaction",
                "performed_at": collected_at,
                "tool_id": COLLECTOR_ID,
                "tool_version": COLLECTOR_VERSION,
                "input_sha256": normalized_title_sha,
                "output_sha256": final_sha,
                "notes": f"Replaced {len(pii_matches)} pattern match(es): {', '.join(sorted(pii_matches))}.",
            }
        )
    labels = sorted(str(label.get("name", "")) for label in item.get("labels", []))
    return {
        "schema_version": "sckg-raw-question-seed-v1",
        "record_type": "raw_seed",
        "seed_id": f"github:{owner}_{repo}:{item['number']}",
        "question_text": redacted_title,
        "language": "und",
        "question_origin": "real-user",
        "source_kind": "official_issue",
        "source": {
            "platform": "github",
            "collection_name": source["collection_name"],
            "external_id": str(item["number"]),
            "canonical_url": item["html_url"],
            "source_title": redacted_title,
            "published_at": item["created_at"],
            "updated_at": item["updated_at"],
            "version_context": {
                "repository": f"{owner}/{repo}",
                "issue_state": item["state"],
                "labels_csv": ",".join(labels),
            },
        },
        "provenance": {
            "collected_at": collected_at,
            "collection_method": "official_api",
            "collector_id": COLLECTOR_ID,
            "collector_version": COLLECTOR_VERSION,
            "endpoint_or_query": collection["endpoint"],
            "source_snapshot_at": collected_at,
            "http_etag": collection["etag"],
            "raw_record_sha256": raw_record_sha,
        },
        "license_or_access_policy": {
            "access_mode": "official_api",
            "storage_permission": "title_only",
            "policy_review_status": "reviewed",
            "policy_url": source["policy_url"],
            "license_identifier": "GitHub-user-content-site-terms",
            "reviewed_at": "2026-09-20T00:00:00Z",
            "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.",
        },
        "pii_redaction_status": {
            "status": "redacted" if pii_matches else "no_pii_detected",
            "reviewed_at": collected_at,
            "redaction_count": len(pii_matches),
            "notes": "Automated title-only pattern review; author identifiers, body, and comments were not collected.",
        },
        "thread_context": {
            "mode": "references_only",
            "thread_external_id": f"{owner}/{repo}#{item['number']}",
            "parent_external_id": "",
            "context_refs": [],
        },
        "transformation_history": history,
        "content_sha256": final_sha,
        "gold_eligible": False,
        "quality_flags": ["empty_context"],
    }


def controlled_seed(probe: tuple[str, str, str], collected_at: str) -> dict[str, Any]:
    probe_id, text, family = probe
    content_sha = sha256_text(text)
    raw_projection = {"probe_id": probe_id, "text": text, "family": family, "version": "v1"}
    return {
        "schema_version": "sckg-raw-question-seed-v1",
        "record_type": "raw_seed",
        "seed_id": f"controlled:{probe_id}",
        "question_text": text,
        "language": "en",
        "question_origin": "controlled-probe",
        "source_kind": "controlled_probe",
        "source": {
            "platform": "sckg-project",
            "collection_name": "benchmark-v3-controlled-probes",
            "external_id": probe_id,
            "canonical_url": f"urn:sckg:benchmark-v3:controlled-probe:{probe_id}",
            "source_title": text,
            "published_at": collected_at,
            "updated_at": collected_at,
            "version_context": {"generator_version": "v1", "probe_family": family},
        },
        "provenance": {
            "collected_at": collected_at,
            "collection_method": "controlled_generation",
            "collector_id": COLLECTOR_ID,
            "collector_version": COLLECTOR_VERSION,
            "endpoint_or_query": "controlled-probes:v1",
            "source_snapshot_at": collected_at,
            "http_etag": "",
            "raw_record_sha256": sha256_bytes(canonical_json_bytes(raw_projection)),
        },
        "license_or_access_policy": {
            "access_mode": "controlled_generated",
            "storage_permission": "full_text",
            "policy_review_status": "reviewed",
            "policy_url": "urn:sckg:policy:project-owned-controlled-probes-v1",
            "license_identifier": "project-owned",
            "reviewed_at": "2026-09-20T00:00:00Z",
            "notes": "Project-authored probe; no external user content.",
        },
        "pii_redaction_status": {
            "status": "no_pii_detected",
            "reviewed_at": collected_at,
            "redaction_count": 0,
            "notes": "Project-authored text reviewed by deterministic PII patterns.",
        },
        "thread_context": {
            "mode": "none",
            "thread_external_id": "",
            "parent_external_id": "",
            "context_refs": [],
        },
        "transformation_history": [],
        "content_sha256": content_sha,
        "gold_eligible": False,
        "quality_flags": [],
    }


def find_exact_groups(seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    key_maps: dict[str, dict[str, list[str]]] = {
        "source_identity": defaultdict(list),
        "canonical_url": defaultdict(list),
        "raw_record_sha256": defaultdict(list),
        "content_sha256": defaultdict(list),
    }
    for seed in seeds:
        key_maps["source_identity"][
            "|".join(
                (
                    seed["source"]["platform"],
                    seed["source"]["collection_name"],
                    seed["source"]["external_id"],
                )
            )
        ].append(seed["seed_id"])
        key_maps["canonical_url"][seed["source"]["canonical_url"]].append(seed["seed_id"])
        key_maps["raw_record_sha256"][seed["provenance"]["raw_record_sha256"]].append(
            seed["seed_id"]
        )
        key_maps["content_sha256"][seed["content_sha256"]].append(seed["seed_id"])

    merged: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for reason, mapping in key_maps.items():
        for members in mapping.values():
            if len(members) > 1:
                merged[tuple(sorted(members))].add(reason)
    return [
        {
            "group_id": f"exact-{index:03d}",
            "seed_ids": list(members),
            "reasons": sorted(reasons),
            "review_status": "needs_adjudication",
        }
        for index, (members, reasons) in enumerate(sorted(merged.items()), start=1)
    ]


def near_duplicate_candidates(
    seeds: list[dict[str, Any]], exact_groups: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    exact_pairs = {
        tuple(sorted((left, right)))
        for group in exact_groups
        for pos, left in enumerate(group["seed_ids"])
        for right in group["seed_ids"][pos + 1 :]
    }
    normalized = {seed["seed_id"]: comparison_text(seed["question_text"]) for seed in seeds}
    output: list[dict[str, Any]] = []
    ordered = sorted(normalized)
    for pos, left in enumerate(ordered):
        left_tokens = set(normalized[left].split())
        for right in ordered[pos + 1 :]:
            if (left, right) in exact_pairs:
                continue
            right_tokens = set(normalized[right].split())
            union = left_tokens | right_tokens
            jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
            sequence = SequenceMatcher(None, normalized[left], normalized[right]).ratio()
            if sequence >= 0.88 or (min(len(left_tokens), len(right_tokens)) >= 3 and jaccard >= 0.75):
                output.append(
                    {
                        "left_seed_id": left,
                        "right_seed_id": right,
                        "token_jaccard": round(jaccard, 6),
                        "sequence_ratio": round(sequence, 6),
                        "reason": "paraphrase_candidate",
                        "review_status": "needs_adjudication",
                    }
                )
    return sorted(output, key=lambda row: (-max(row["token_jaccard"], row["sequence_ratio"]), row["left_seed_id"], row["right_seed_id"]))


def cluster_seeds(seeds: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    ordered = sorted(seeds, key=lambda seed: seed["seed_id"])
    documents = [comparison_text(seed["question_text"]) for seed in ordered]
    vectorizer = TfidfVectorizer(
        lowercase=False,
        ngram_range=(1, 2),
        min_df=1,
        max_features=512,
        stop_words="english",
        token_pattern=r"(?u)\b[\w<>+.-]{2,}\b",
    )
    matrix = vectorizer.fit_transform(documents)
    labels = AgglomerativeClustering(
        n_clusters=CLUSTER_COUNT, metric="cosine", linkage="average"
    ).fit_predict(matrix.toarray())
    raw_members: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        raw_members[int(label)].append(index)
    label_order = sorted(raw_members, key=lambda label: min(ordered[index]["seed_id"] for index in raw_members[label]))
    stable_id = {label: f"cluster-{index:02d}" for index, label in enumerate(label_order, start=1)}
    features = vectorizer.get_feature_names_out()
    clusters: list[dict[str, Any]] = []
    seed_to_cluster: dict[str, str] = {}
    for label in label_order:
        indexes = raw_members[label]
        cluster_id = stable_id[label]
        for index in indexes:
            seed_to_cluster[ordered[index]["seed_id"]] = cluster_id
        centroid = matrix[indexes].mean(axis=0).A1
        top_indexes = centroid.argsort()[::-1][:6]
        terms = [str(features[index]) for index in top_indexes if centroid[index] > 0]
        member_seeds = [ordered[index] for index in indexes]
        clusters.append(
            {
                "cluster_id": cluster_id,
                "provisional_label": " / ".join(terms[:3]) or "unlabeled",
                "top_terms": terms,
                "seed_ids": sorted(seed["seed_id"] for seed in member_seeds),
                "origin_counts": dict(sorted(Counter(seed["question_origin"] for seed in member_seeds).items())),
                "source_counts": dict(sorted(Counter(seed["source"]["collection_name"] for seed in member_seeds).items())),
                "review_status": "needs_adjudication",
            }
        )
    return clusters, seed_to_cluster


def build_candidates(
    seeds: list[dict[str, Any]], seed_to_cluster: dict[str, str]
) -> list[dict[str, Any]]:
    by_origin: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for seed in seeds:
        by_origin[seed["question_origin"]].append(seed)

    def candidate_rank(seed: dict[str, Any]) -> str:
        return sha256_text(f"{SELECTION_SALT}|candidate|{seed['seed_id']}")

    selected = sorted(by_origin["real-user"], key=candidate_rank)[:3]
    selected += sorted(by_origin["controlled-probe"], key=candidate_rank)[:3]
    candidates: list[dict[str, Any]] = []
    for index, seed in enumerate(selected, start=1):
        is_public = seed["question_origin"] == "real-user"
        candidates.append(
            {
                "schema_version": "sckg-candidate-scenario-pilot-v1",
                "candidate_id": f"candidate-pilot-{index:02d}",
                "source_seed_ids": [seed["seed_id"]],
                "question_origin": seed["question_origin"],
                "draft_query": seed["question_text"],
                "context_requirements": [
                    "Adjudicator must recover missing package, data, and version context before promotion."
                    if is_public
                    else "Adjudicator must verify answerability and required trace evidence before promotion."
                ],
                "task_family_candidate": seed_to_cluster[seed["seed_id"]],
                "ambiguities_and_missing_facts": [
                    "Title-only public seed may omit reproduction details and intended outcome."
                    if is_public
                    else "Controlled probe has no expected answer or evidence bundle in this pilot."
                ],
                "transformation_history": [
                    {
                        "operation": "identity_draft",
                        "source_seed_id": seed["seed_id"],
                        "notes": "Identity transformation used only to validate candidate plumbing and contamination fields.",
                    }
                ],
                "coverage_vector": {
                    "scientific_kg_v2": "unknown",
                    "legacy_kg": "unknown",
                    "ordinary_rag": "unknown",
                    "exact_signature": None,
                    "coarse_label": None,
                    "snapshot_digests": {},
                },
                "public_exposure": "public-source" if is_public else "project-controlled-not-public",
                "verbatim_overlap": 1.0,
                "transformation_distance": 0.0,
                "contamination_measurement": "normalized-identity-v1",
                "memorization_risk": "high" if is_public else "low",
                "review_status": "needs_adjudication",
                "gold_status": "none",
            }
        )
    return candidates


def validate_records(
    seeds: list[dict[str, Any]], candidates: list[dict[str, Any]], schema_path: Path
) -> dict[str, Any]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[dict[str, Any]] = []
    for seed in seeds:
        for error in validator.iter_errors(seed):
            errors.append(
                {
                    "seed_id": seed.get("seed_id", "unknown"),
                    "path": "/".join(str(part) for part in error.absolute_path),
                    "message": error.message,
                }
            )
        if seed["content_sha256"] != sha256_text(seed["question_text"]):
            errors.append({"seed_id": seed["seed_id"], "path": "content_sha256", "message": "hash mismatch"})
    negative = json.loads(json.dumps(seeds[0]))
    negative["gold_eligible"] = True
    negative_rejected = not validator.is_valid(negative)
    candidate_errors: list[str] = []
    for candidate in candidates:
        if candidate.get("review_status") != "needs_adjudication":
            candidate_errors.append(f"{candidate['candidate_id']}: review_status")
        if candidate.get("gold_status") != "none":
            candidate_errors.append(f"{candidate['candidate_id']}: gold_status")
        for field in (
            "public_exposure",
            "verbatim_overlap",
            "transformation_distance",
            "memorization_risk",
        ):
            if field not in candidate:
                candidate_errors.append(f"{candidate['candidate_id']}: missing {field}")
    return {
        "schema_draft": "2020-12",
        "schema_valid": not errors,
        "records_checked": len(seeds),
        "record_errors": errors,
        "gold_eligible_true_rejected": negative_rejected,
        "candidate_records_checked": len(candidates),
        "candidate_invariant_errors": candidate_errors,
        "candidate_invariants_valid": not candidate_errors,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )


def render_cluster_report(clusters: list[dict[str, Any]], seed_lookup: dict[str, dict[str, Any]]) -> str:
    lines = [
        "# Phase 2 Pilot Cluster Report",
        "",
        f"Run: `{RUN_ID}`",
        f"Records: {sum(len(cluster['seed_ids']) for cluster in clusters)}",
        f"Provisional clusters: {len(clusters)}",
        "",
        "This is a deterministic lexical inventory smoke test, not a task taxonomy or Gold label.",
        "TF-IDF unigrams/bigrams (512-feature cap) feed average-linkage agglomerative",
        f"clustering with cosine distance and `n_clusters={CLUSTER_COUNT}`. Cluster names are",
        "top-term summaries and every cluster remains `needs_adjudication`.",
        "",
    ]
    for cluster in clusters:
        lines.extend(
            [
                f"## {cluster['cluster_id']}: {cluster['provisional_label']}",
                "",
                f"- Size: {len(cluster['seed_ids'])}",
                f"- Origins: `{json.dumps(cluster['origin_counts'], sort_keys=True)}`",
                f"- Sources: `{json.dumps(cluster['source_counts'], sort_keys=True)}`",
                f"- Top terms: {', '.join(f'`{term}`' for term in cluster['top_terms'])}",
                "- Example seeds:",
                "",
            ]
        )
        for seed_id in cluster["seed_ids"][:3]:
            text = seed_lookup[seed_id]["question_text"].replace("\n", " ")
            lines.append(f"  - `{seed_id}` — {text}")
        lines.extend(["", "Review status: `needs_adjudication`.", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_pilot_report(
    seeds: list[dict[str, Any]],
    exact_groups: list[dict[str, Any]],
    near_duplicates: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    validation: dict[str, Any],
    collections: list[dict[str, Any]],
) -> str:
    source_counts = Counter(seed["source"]["collection_name"] for seed in seeds)
    redacted = sum(seed["pii_redaction_status"]["redaction_count"] for seed in seeds)
    largest_cluster = max(len(cluster["seed_ids"]) for cluster in clusters)
    return f"""# Phase 2 Real-world Question Mining Pilot Report

Run: `{RUN_ID}`
Date: 2026-09-20
Status: complete bounded pilot; no DEV/Gold or Agent Gain

## Outcome

- Raw seeds: {len(seeds)} ({sum(seed['question_origin'] == 'real-user' for seed in seeds)} real-user, {sum(seed['question_origin'] == 'controlled-probe' for seed in seeds)} controlled probes).
- Source counts: `{json.dumps(dict(sorted(source_counts.items())), sort_keys=True)}`.
- Official API calls: {len(collections)} serial GitHub REST GETs; bodies/comments/replies were never requested.
- Automated PII replacements in stored titles: {redacted}.
- Exact duplicate groups: {len(exact_groups)}; near-duplicate candidates: {len(near_duplicates)}.
- Provisional clusters: {len(clusters)}; candidate-scenario plumbing records: {len(candidates)}.
- Raw schema: {validation['records_checked']} checked, {len(validation['record_errors'])} errors; negative `gold_eligible=true` test rejected: {str(validation['gold_eligible_true_rejected']).lower()}.
- Candidate invariants: `review_status=needs_adjudication`, `gold_status=none`, and contamination fields valid for all {validation['candidate_records_checked']} records.

## Selection and leakage controls

Each GitHub source was limited to page 1 (100 API items maximum). Pull requests,
bot-authored items, and empty titles were excluded. Twenty issues per repository
were selected by a fixed SHA-256 rank over repository plus issue number, without
looking at issue text, replies, or any 07 Research Chat result. Eight project-owned
controlled probes were appended and are reported separately.

The dedup thresholds are provisional and not yet calibrated by human pair
review. Zero near-duplicate candidates therefore means “none crossed the pilot
threshold,” not that the sample contains no semantic duplicates. The lexical
clustering smoke test placed {largest_cluster}/{len(seeds)} records in its largest cluster;
that imbalance is evidence that title-only TF-IDF clusters are not yet suitable
for balanced scenario sampling. Cluster labels and memberships remain review
queues only.

No public answer, accepted answer, maintainer reply, issue state, or label became
Gold. Candidate drafts are identity transformations used to exercise the
transformation and contamination fields; public candidates are deliberately
flagged `memorization_risk=high`. No coverage signature was assigned because no
frozen V2/Legacy/RAG coverage audit was run.

## Policy outcomes

Scanpy and Seurat were collected only through the official GitHub REST API under
the title-only profile in `policy_decisions.md`. scverse Discourse was not
contacted because its Terms of Service prohibit this automation. Biostars and
Bioconductor Support remained policy-pending and were not contacted.

## Interpretation limits

This pilot validates engineering flow and provenance retention, not population
representativeness. The one-page GitHub frame, title-only questions, fixed eight
clusters, automated PII patterns, and unadjudicated duplicate candidates are
deliberate pilot constraints. It generated no development/evaluation/hidden
split, no expected answer, no scientific Gold, and no Agent Gain result. It did
not modify Viewer, Scientific KG, or Research Chat.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory for pilot artifacts (default: script directory).",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = output_dir / "raw_seed_schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(schema_path)

    collected_at = utc_now()
    head_commit = git_output(repo_root, "rev-parse", "HEAD")
    branch = git_output(repo_root, "branch", "--show-current")
    preexisting_status = git_output(repo_root, "status", "--short")
    collections: list[dict[str, Any]] = []
    seeds: list[dict[str, Any]] = []

    for source in GITHUB_SOURCES:
        items, collection = fetch_github_issues(source)
        eligible = [item for item in items if eligible_issue(item)]
        if len(eligible) < PER_REPOSITORY_QUOTA:
            raise RuntimeError(
                f"{source['owner']}/{source['repo']} has only {len(eligible)} eligible issues on page 1; "
                f"refusing to expand beyond the reviewed endpoint bound"
            )
        selected = sorted(eligible, key=lambda item: rank_issue(source, item))[:PER_REPOSITORY_QUOTA]
        collection.update(
            {
                "source": f"{source['owner']}/{source['repo']}",
                "eligible_items": len(eligible),
                "excluded_pull_requests_or_bots_or_empty": len(items) - len(eligible),
                "selection_algorithm": "lowest_sha256(selection_salt|repository|issue_number)",
                "selection_salt_sha256": sha256_text(SELECTION_SALT),
                "selected_count": len(selected),
                "selected_external_ids": sorted(str(item["number"]) for item in selected),
            }
        )
        collections.append(collection)
        seeds.extend(github_seed(source, item, collection, collected_at) for item in selected)

    seeds.extend(controlled_seed(probe, collected_at) for probe in CONTROLLED_PROBES)
    seeds.sort(key=lambda seed: seed["seed_id"])
    exact_groups = find_exact_groups(seeds)
    exact_member_ids = {seed_id for group in exact_groups for seed_id in group["seed_ids"]}
    near_duplicates = near_duplicate_candidates(seeds, exact_groups)
    near_member_ids = {
        seed_id
        for pair in near_duplicates
        for seed_id in (pair["left_seed_id"], pair["right_seed_id"])
    }
    for seed in seeds:
        if seed["seed_id"] in exact_member_ids | near_member_ids:
            seed["quality_flags"] = sorted(set(seed["quality_flags"] + ["possible_duplicate"]))

    clusters, seed_to_cluster = cluster_seeds(seeds)
    candidates = build_candidates(seeds, seed_to_cluster)
    validation = validate_records(seeds, candidates, schema_path)
    if not validation["schema_valid"] or not validation["gold_eligible_true_rejected"]:
        raise RuntimeError(f"Raw-seed validation failed: {validation}")
    if not validation["candidate_invariants_valid"]:
        raise RuntimeError(f"Candidate validation failed: {validation}")

    raw_path = output_dir / "raw_seeds_pilot.jsonl"
    candidate_path = output_dir / "candidate_scenarios_pilot.jsonl"
    dedup_path = output_dir / "dedup_report.json"
    cluster_path = output_dir / "cluster_report.md"
    pilot_path = output_dir / "pilot_report.md"
    manifest_path = output_dir / "collection_manifest.json"

    write_jsonl(raw_path, seeds)
    write_jsonl(candidate_path, candidates)
    write_json(
        dedup_path,
        {
            "schema_version": "sckg-dedup-report-v1",
            "run_id": RUN_ID,
            "normalizer": "unicode-nfkc-number-placeholder-token-v1",
            "exact_match_keys": [
                "platform+collection+external_id",
                "canonical_url",
                "raw_record_sha256",
                "content_sha256",
            ],
            "exact_duplicate_group_count": len(exact_groups),
            "exact_duplicate_groups": exact_groups,
            "near_duplicate_rule": "sequence_ratio>=0.88 OR token_jaccard>=0.75 with >=3 tokens on each side",
            "near_duplicate_threshold_status": "provisional_unvalidated",
            "human_pair_reviews_completed": 0,
            "near_duplicate_candidate_count": len(near_duplicates),
            "near_duplicate_candidates": near_duplicates,
            "records_deleted": 0,
        },
    )
    seed_lookup = {seed["seed_id"]: seed for seed in seeds}
    cluster_path.write_text(render_cluster_report(clusters, seed_lookup), encoding="utf-8")
    pilot_path.write_text(
        render_pilot_report(
            seeds, exact_groups, near_duplicates, clusters, candidates, validation, collections
        ),
        encoding="utf-8",
    )

    artifact_paths = (raw_path, candidate_path, dedup_path, cluster_path, pilot_path)
    manifest = {
        "schema_version": "sckg-collection-manifest-v1",
        "run_id": RUN_ID,
        "started_and_completed_at": collected_at,
        "collector": {
            "id": COLLECTOR_ID,
            "version": COLLECTOR_VERSION,
            "source_path": str(Path(__file__).resolve().relative_to(repo_root)),
            "source_sha256": file_sha256(Path(__file__).resolve()),
        },
        "repository": {
            "branch": branch,
            "head_before_collection": head_commit,
            "dirty_before_collection": bool(preexisting_status),
            "dirty_paths_before_collection": preexisting_status.splitlines(),
        },
        "bounds": {
            "target_raw_seed_range": [40, 60],
            "github_requests": len(collections),
            "github_pages_per_repository": 1,
            "github_per_page": 100,
            "github_selected_per_repository": PER_REPOSITORY_QUOTA,
            "controlled_probe_count": len(CONTROLLED_PROBES),
            "bulk_collection": False,
        },
        "sources_used": [
            "Scanpy GitHub issues",
            "Seurat GitHub issues",
            "project-owned controlled probes",
        ],
        "policy_blocked_sources": list(POLICY_BLOCKED_SOURCES),
        "collections": collections,
        "counts": {
            "raw_seeds": len(seeds),
            "real_user_seeds": sum(seed["question_origin"] == "real-user" for seed in seeds),
            "controlled_probes": sum(seed["question_origin"] == "controlled-probe" for seed in seeds),
            "exact_duplicate_groups": len(exact_groups),
            "near_duplicate_candidates": len(near_duplicates),
            "clusters": len(clusters),
            "candidate_scenarios": len(candidates),
        },
        "schema": {
            "path": str(schema_path.relative_to(repo_root)),
            "sha256": file_sha256(schema_path),
            "validation": validation,
        },
        "input_digests": {
            str(path.relative_to(repo_root)): file_sha256(path)
            for path in (
                output_dir / "benchmark_sources.md",
                output_dir / "benchmark_taxonomy.md",
                output_dir / "mining_plan.md",
                output_dir / "policy_decisions.md",
                schema_path,
            )
        },
        "pipeline_versions": {
            "selection": "sha256-rank-v1",
            "pii_redactor": "title-pattern-redactor-v1",
            "dedup_normalizer": "unicode-nfkc-number-placeholder-token-v1",
            "near_duplicate_threshold": "provisional-v1",
            "clustering": "tfidf-512-average-linkage-cosine-v1",
            "clustering_random_seed": "not_applicable_deterministic_algorithm",
            "candidate_transformation": "identity-draft-v1",
        },
        "analysis": {
            "selection_used_downstream_agent_results": False,
            "forum_or_issue_replies_collected": False,
            "dev_or_gold_created": False,
            "agent_gain_run": False,
            "coverage_audit_run": False,
            "cluster_method": "TF-IDF + average-linkage agglomerative cosine clustering",
            "cluster_count_fixed_for_pilot": CLUSTER_COUNT,
        },
        "artifacts": {
            str(path.relative_to(repo_root)): {
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in artifact_paths
        },
    }
    write_json(manifest_path, manifest)
    print(json.dumps(manifest["counts"], sort_keys=True))
    print(f"schema_valid={validation['schema_valid']} candidate_invariants_valid={validation['candidate_invariants_valid']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
