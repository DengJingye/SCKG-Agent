"""Read-only development snapshots from the isolated, governed knowledge store.

These snapshots are development material, never independent held-out gold. The
source database is opened in SQLite read-only mode; no service initializer, model
connection, credential record, approval, or publication is created or changed.
"""
from __future__ import annotations

from contextlib import contextmanager
import sqlite3

from sckg_workbench.catalog import Catalog
from sckg_workbench.knowledge import KnowledgeService
from sckg_workbench.storage import Ledger, Workspace, content_hash, utcnow


class _ReadOnlyLedger(Ledger):
    def __init__(self, workspace: Workspace, connection: sqlite3.Connection):
        # Deliberately bypass Ledger.__init__: it creates schema and state.
        self.workspace = workspace
        self.connection = connection

    @contextmanager
    def connect(self):
        # Nested service reads share the same SQLite snapshot. The caller owns
        # transaction cleanup, so KnowledgeService.resolve leaves it pinned.
        yield self.connection


class _ReadOnlyKnowledge(KnowledgeService):
    def __init__(self, ledger):
        # Exact resolution does not require creating the derived FTS table.
        self.ledger = ledger


def _public_source(source: dict) -> dict:
    public = {key: source[key] for key in (
        "id", "source_revision_id", "snapshot_id", "blob_sha256", "filename",
        "media_type", "size_bytes", "created_at",
    ) if key in source}
    metadata = source.get("metadata", {})
    # Arbitrary upload metadata can contain private notes or credentials.
    for key in ("title", "doi", "manifest_id", "batch_id", "capture_scope",
                "material_gaps", "evaluation_exposure"):
        if key in metadata:
            public[key] = metadata[key]
    return public


def freeze_workbench_snapshot(workspace: Workspace, purpose="explanation") -> dict:
    """Freeze currently eligible, explicitly development-exposed knowledge.

    All governance and source decisions use one read transaction. If publication
    changes between discovering its IDs and beginning resolution, fail instead
    of returning a partial mix; callers may explicitly start a new snapshot.
    The returned hash excludes only its capture timestamp and the hash itself.
    """
    if purpose not in {"explanation", "recommendation"}:
        raise ValueError("Snapshot purpose must be explanation or recommendation")
    for path in (workspace.db_path, workspace.root / "workspace.json",
                 workspace.root / "ledger.sqlite3-wal", workspace.root / "ledger.sqlite3-shm"):
        if path.is_symlink():
            raise ValueError("Snapshot ledger and identity paths must not be symlinks")
    if not workspace.db_path.is_file():
        raise ValueError("Snapshot requires an existing knowledge ledger")
    namespace = workspace.namespace
    conn = sqlite3.connect(workspace.db_path.as_uri() + "?mode=ro", uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        ledger = _ReadOnlyLedger(workspace, conn)
        row = conn.execute("SELECT value FROM metadata WHERE key='namespace'").fetchone()
        if row is None or row[0] != namespace:
            raise ValueError("Ledger belongs to a different workspace")
        initial_release_id = ledger.get_state("current_release")
        release = ledger.get_record("release", initial_release_id) if initial_release_id else None
        if initial_release_id and release is None:
            raise ValueError("Current release has no immutable manifest")
        candidate_ids = [row["candidate_id"] for row in (release or {}).get("units", [])]
        # Uses the production eligibility gates, including live suspension,
        # latest review/use, assessment revision, and exact original integrity.
        package = _ReadOnlyKnowledge(ledger).resolve(candidate_ids, purpose=purpose)
        if package.release_id != initial_release_id:
            raise ValueError("Release changed during snapshot preparation; retry explicitly")
        catalog = Catalog(ledger)
        uses = ledger.list_records("development_use")
        gaps = list(package.gaps)
        allowed_sources, rejected_sources = {}, set()
        all_source_ids = sorted({e["source_id"] for unit in package.units for e in unit["evidence"]})
        for source_id in all_source_ids:
            source = ledger.get_record("source", source_id)
            if source is None:
                raise ValueError("Resolved evidence references a missing source")
            exposure = source.get("metadata", {}).get("evaluation_exposure")
            recorded_use = any(
                use.get("source_id") == source_id
                and use.get("source_revision_id") == source["source_revision_id"]
                and use.get("blob_sha256") == source["blob_sha256"]
                for use in uses
            )
            if exposure in {"holdout", "calibration"}:
                rejected_sources.add(source_id)
                gaps.append(f"{source_id}: declared sealed evaluation material excluded")
                continue
            if exposure != "development" and not recorded_use:
                rejected_sources.add(source_id)
                gaps.append(f"{source_id}: development exposure unknown; excluded")
                continue
            try:
                catalog._assert_development_allowed(source, conn=conn)
                catalog._material(source_id, conn=conn)
            except (ValueError, OSError) as exc:
                rejected_sources.add(source_id)
                gaps.append(f"{source_id}: development/source gate excluded material ({exc})")
                continue
            allowed_sources[source_id] = source
        # A multi-source unit is indivisible here: dropping one of its evidence
        # anchors would silently change the approved assertion and its support.
        units = [unit for unit in package.units
                 if not any(e["source_id"] in rejected_sources for e in unit["evidence"])]
        used_source_ids = sorted({e["source_id"] for unit in units for e in unit["evidence"]})
        snapshot = {
            "schema_version": "workbench-evaluation-snapshot-v1",
            "namespace": namespace, "release_id": package.release_id,
            "governance_version": package.governance_version, "purpose": purpose,
            "units": units, "sources": [_public_source(allowed_sources[sid]) for sid in used_source_ids],
            "gaps": list(dict.fromkeys(gaps)), "split": "development",
        }
        snapshot["snapshot_hash"] = content_hash(snapshot)
        snapshot["captured_at"] = utcnow()
        return snapshot
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()
