"""Local workbench CLI. No model or network use unless explicitly selected."""
from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys
import time

from .catalog import Catalog
from .external_evidence import ExternalEvidenceService, SourceExportRights
from .knowledge import KnowledgeService
from .sources import MAX_SOURCE_BYTES, SourceService
from .source_watch import SourceUpdateService
from .storage import Ledger, Workspace
from .tasks import TaskQueue


def emit(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser():
    root = argparse.ArgumentParser(description="scKG isolated local knowledge workbench")
    root.add_argument("--home", type=Path, help="Independent empty/new workbench directory; never a legacy data directory")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "catalog", "sources", "profiles", "tasks"):
        commands.add_parser(name)
    command = commands.add_parser("import", help="Register immutable local source bytes; no extraction")
    command.add_argument("path", type=Path)
    command.add_argument("--request-id")
    command = commands.add_parser("parse")
    command.add_argument("source_id")
    command.add_argument("--max-pages", type=int, default=50)
    command.add_argument("--max-chars", type=int, default=12000)
    command = commands.add_parser("check-source-update", help="Run one bounded URL byte check; changed material stays candidate-only")
    command.add_argument("source_id")
    command.add_argument("--allow-network", action="store_true", help="Explicitly permit one bounded remote fetch")
    command = commands.add_parser("stage-source-update", help="Register checked candidate bytes as a new provisional source")
    command.add_argument("candidate_id")
    command.add_argument("--actor", required=True)
    command.add_argument("--reason", required=True)
    command = commands.add_parser("search")
    command.add_argument("query")
    command.add_argument("--purpose", choices=["explanation", "recommendation"], default="explanation")
    commands.add_parser("evidence-version", help="Read the current external evidence version without changing the ledger")
    command = commands.add_parser("evidence-search", help="Search only currently approved, reusable evidence")
    command.add_argument("query")
    command.add_argument("--purpose", choices=["explanation", "recommendation"], default="explanation")
    command.add_argument("--limit", type=int, default=10)
    command = commands.add_parser("evidence-resolve", help="Resolve exact IDs through current governance and source rights")
    command.add_argument("candidate_ids", nargs="+")
    command.add_argument("--purpose", choices=["explanation", "recommendation"], default="explanation")
    command = commands.add_parser("export-knowledge", help="Print a versioned portable evidence package; redirect stdout to save")
    command.add_argument("--purpose", choices=["explanation", "recommendation"], default="explanation")
    command = commands.add_parser("review-export-rights", help="Record human-reviewed source reuse permission")
    command.add_argument("source_id")
    command.add_argument("--source-revision-id", required=True)
    command.add_argument("--blob-sha256", required=True)
    command.add_argument("--decision", choices=["claims", "claims-and-quotes", "revoke"], required=True)
    command.add_argument("--license-ref", required=True)
    command.add_argument("--reviewer", required=True)
    command.add_argument("--reason", required=True)
    command = commands.add_parser("freeze-split", help="Freeze reviewed source/work-family assignments from a JSON file")
    command.add_argument("path", type=Path)
    command.add_argument("--reviewer", required=True)
    command = commands.add_parser("ingest", help="Queue a bounded extraction/assessment job; does not send data")
    command.add_argument("source_id")
    command.add_argument("--extraction-profile", required=True)
    command.add_argument("--assessment-profile", required=True)
    command.add_argument("--request-id", required=True)
    command.add_argument("--max-calls", type=int, default=8)
    command.add_argument("--max-tokens", type=int, default=256000)
    command.add_argument("--max-cost", type=float, required=True, help="USD at configured profile rates")
    command.add_argument("--input-tokens", type=int, default=64000)
    command.add_argument("--output-tokens", type=int, default=4000)
    command.add_argument("--timeout", type=int, default=60)
    command = commands.add_parser("worker", help="Process one job by default; password is entered securely at the terminal")
    command.add_argument("--allow-model-outbound", action="store_true", help="Authorize sending queued source text to the frozen model connections")
    command.add_argument("--watch", action="store_true", help="Keep waiting for new jobs until interrupted")
    command.add_argument("--max-jobs", type=int, default=1, help="Bound processed jobs; with --watch use 0 for explicit indefinite service")
    command.add_argument("--poll-seconds", type=float, default=2)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        workspace = Workspace(args.home) if args.home else Workspace.default()
        if args.command in {"evidence-version", "evidence-search", "evidence-resolve", "export-knowledge"}:
            external = ExternalEvidenceService(workspace)
            if args.command == "evidence-version":
                emit(external.current_version())
            elif args.command == "evidence-search":
                emit(external.search_evidence(args.query, purpose=args.purpose, limit=args.limit))
            elif args.command == "evidence-resolve":
                emit(external.resolve_evidence(args.candidate_ids, purpose=args.purpose))
            else:
                emit(external.export_knowledge(purpose=args.purpose))
            return 0
        ledger = Ledger(workspace)
        if args.command in {"init", "status"}:
            release = KnowledgeService(ledger).current_release()
            emit({"namespace": workspace.namespace, "workspace": str(workspace.root), "legacy_import": False,
                  "sources": len(ledger.list_records("source")), "candidates": len(ledger.list_records("candidate")),
                  "current_release": release["id"] if release else None,
                  "split": ledger.get_state("evaluation_split"), "gold_status": "not_created",
                  "tasks": len(TaskQueue(workspace).list()), "stage": "M0 and bounded single-source pipeline"})
        elif args.command == "catalog":
            emit(Catalog(ledger).seeds())
        elif args.command == "sources":
            emit(ledger.list_records("source"))
        elif args.command == "profiles":
            emit(ledger.list_records("model_profile"))
        elif args.command == "tasks":
            emit(TaskQueue(workspace).list())
        elif args.command == "import":
            if args.path.stat().st_size > MAX_SOURCE_BYTES:
                raise ValueError("Source exceeds bounded upload size")
            emit(SourceService(ledger).register_bytes(args.path.name, args.path.read_bytes(), request_id=args.request_id))
        elif args.command == "parse":
            emit(SourceService(ledger).parse(args.source_id, max_pages=args.max_pages, max_chars=args.max_chars))
        elif args.command == "check-source-update":
            emit(SourceUpdateService(ledger).check(args.source_id, allow_network=args.allow_network))
        elif args.command == "stage-source-update":
            emit(SourceUpdateService(ledger).stage_candidate(args.candidate_id, actor=args.actor, reason=args.reason))
        elif args.command == "search":
            emit(KnowledgeService(ledger).search(args.query, purpose=args.purpose))
        elif args.command == "review-export-rights":
            emit(SourceExportRights(ledger).review(args.source_id, reviewer=args.reviewer,
                 license_ref=args.license_ref, claims_allowed=args.decision != "revoke",
                 quotes_allowed=args.decision == "claims-and-quotes", reason=args.reason,
                 expected_source_revision_id=args.source_revision_id, expected_blob_sha256=args.blob_sha256))
        elif args.command == "freeze-split":
            emit(Catalog(ledger).freeze_split(json.loads(args.path.read_text()), reviewer=args.reviewer))
        elif args.command == "ingest":
            from .worker import Worker
            emit(Worker(ledger).submit_ingestion(args.source_id, args.extraction_profile, args.assessment_profile,
                 budget={"max_calls": args.max_calls, "max_tokens": args.max_tokens, "max_cost": args.max_cost},
                 request_budget={"max_input_tokens": args.input_tokens, "max_output_tokens": args.output_tokens,
                                 "timeout_seconds": args.timeout}, idempotency_key=args.request_id))
        elif args.command == "worker":
            if not args.allow_model_outbound:
                raise ValueError("Pass --allow-model-outbound to explicitly authorize model submission")
            if args.max_jobs < 0 or not 0 < args.poll_seconds <= 60 or (args.max_jobs == 0 and not args.watch):
                raise ValueError("Invalid worker limits")
            from .worker import Worker
            worker = Worker(ledger)
            passphrase = ""
            completed = 0
            while True:
                if worker.requires_passphrase() and not passphrase:
                    passphrase = getpass.getpass("Vault passphrase: ")
                task = worker.run_once(passphrase=passphrase, outbound_authorized=True)
                if task:
                    emit(task)
                    completed += 1
                if args.max_jobs and completed >= args.max_jobs:
                    break
                if not args.watch:
                    if task is None:
                        emit({"status": "idle", "processed": completed})
                    break
                if task is None:
                    time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        print("Worker stopped; interrupted leased jobs remain recoverable as result_unknown.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
