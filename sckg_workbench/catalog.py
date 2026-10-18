"""Source discovery seeds, not evidence, and immutable evaluation partitions."""
from __future__ import annotations
import hashlib
import re

from .storage import Ledger, content_hash, new_id, utcnow


SEEDS = (
    ("P01", "OSCA", "https://bioconductor.org/books/release/OSCA/", True),
    ("P02", "Scanpy", "https://scanpy.scverse.org/en/stable/tutorials/basics/clustering.html", True),
    ("P03", "Seurat", "https://satijalab.org/seurat/articles/seurat5_integration", True),
    ("P04", "SoupX", "https://pmc.ncbi.nlm.nih.gov/articles/PMC7763177/", True),
    ("P05", "scDblFinder", "https://plger.github.io/scDblFinder/articles/scDblFinder.html", True),
    ("P06", "scIB", "https://www.nature.com/articles/s41592-021-01336-8", True),
    ("P07", "scvi-tools", "https://docs.scvi-tools.org/en/stable/", True),
    ("P08", "SingleR", "https://bioconductor.org/books/release/SingleRBook/", True),
    ("P09", "Single-cell Best Practices", "https://www.sc-best-practices.org/", False),
    ("P10", "Doublet benchmark", "https://pmc.ncbi.nlm.nih.gov/articles/PMC7897250/", False),
    ("P11", "Harmony", "https://doi.org/10.1038/s41592-019-0619-0", False),
    ("P12", "CellTypist", "https://celltypist.readthedocs.io/en/latest/", False),
    ("P13", "Differential expression benchmark", "https://www.nature.com/articles/s41467-021-25960-2", False),
    ("P14", "scVelo", "https://scvelo.readthedocs.io/en/stable/", False),
    ("P15", "CellRank 2", "https://www.nature.com/articles/s41592-024-02303-9", False),
    ("P16", "tradeSeq", "https://statomics.github.io/tradeSeq/", False),
)


class Catalog:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def seeds(self) -> list[dict]:
        return [{"seed_id": key, "name": name, "discovery_url": url, "pilot": pilot,
                 "status": "discovery_only", "version": "not_captured", "approved": False}
                for key, name, url, pilot in SEEDS]

    @staticmethod
    def _text(value, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()

    def _material(self, source_id: str, *, conn) -> dict:
        """Validate a captured source and its bytes, never just a discovery label."""
        source_id = self._text(source_id, "source_id")
        source = self.ledger.get_record("source", source_id, conn=conn)
        if source is None:
            raise ValueError("source must be registered in this workspace")
        revision = self.ledger.get_record("source_revision", source.get("source_revision_id", ""), conn=conn)
        original = self.ledger.get_record("original", source.get("original_id", ""), conn=conn)
        snapshot = self.ledger.get_record("snapshot", source.get("snapshot_id", ""), conn=conn)
        sha = source.get("blob_sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("captured source requires a valid blob digest")
        if (source.get("id") != source_id or source.get("source_id") != source_id
                or not revision or not original or not snapshot
                or revision.get("source_id") != source_id
                or revision.get("original_id") != original.get("id")
                or revision.get("snapshot_id") != snapshot.get("id")
                or snapshot.get("original_id") != original.get("id")
                or revision.get("blob_sha256") != sha or original.get("blob_sha256") != sha):
            raise ValueError("captured source provenance chain is incomplete or inconsistent")
        directory = self.ledger.workspace.artifacts_dir / "source_blobs"
        path = directory / sha
        if (self.ledger.workspace.artifacts_dir.is_symlink() or directory.is_symlink()
                or path.is_symlink() or not path.is_file()):
            raise ValueError("captured source material is missing or is a symlink")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if (size == 0 or digest.hexdigest() != sha or size != source.get("size_bytes")
                or size != original.get("size_bytes")):
            raise ValueError("captured source material integrity check failed")
        return source

    def _known_families(self, *, conn) -> dict[str, str]:
        return {row["source_id"]: row["work_family"]
                for row in self.ledger.list_records("source_work_family", conn=conn)}

    def record_work_family(self, source_id: str, work_family: str, *, reviewer: str, reason: str) -> dict:
        """Record a reviewed identity decision; raw upload metadata is not one."""
        source_id = self._text(source_id, "source_id")
        family = self._text(work_family, "work_family")
        reviewer, reason = self._text(reviewer, "reviewer"), self._text(reason, "reason")
        with self.ledger.transaction() as conn:
            source = self._material(source_id, conn=conn)
            previous = self.ledger.get_record("source_work_family", source_id, conn=conn)
            if previous:
                if previous["work_family"] != family:
                    raise ValueError("work family decision is immutable; a correction requires a new evaluation cohort")
                return previous
            if self.ledger.get_state("evaluation_split", conn=conn):
                raise ValueError("split is frozen; new identity decisions require a separate evaluation cohort")
            record = {"source_id": source_id, "source_revision_id": source["source_revision_id"],
                      "blob_sha256": source["blob_sha256"], "work_family": family,
                      "reviewer": reviewer, "reason": reason, "created_at": utcnow()}
            self.ledger.put_record("source_work_family", source_id, record, conn=conn)
            self.ledger.append_event("source_work_family_reviewed", source_id,
                                     {"work_family": family, "reviewer": reviewer}, conn=conn)
            return record

    def freeze_split(self, assignments: list[dict], *, reviewer: str) -> dict:
        """Freeze the complete currently captured cohort, grouped by family/blob.

        Human declarations can disclose external development use. They can never
        override exposure already recorded by the application. Family identity
        still needs review; this routine does not infer it from titles or URLs.
        """
        reviewer = self._text(reviewer, "reviewer")
        if not isinstance(assignments, list) or not assignments:
            raise ValueError("assignments must be a non-empty list")
        required = {"source_id", "work_family", "partition", "prior_development_use"}
        normalized = []
        for row in assignments:
            if not isinstance(row, dict) or set(row) != required:
                raise ValueError("split rows require source_id/work_family/partition/prior_development_use")
            item = {**row, "source_id": self._text(row["source_id"], "source_id"),
                    "work_family": self._text(row["work_family"], "work_family")}
            if not isinstance(item["partition"], str) or item["partition"] not in {"development", "calibration", "holdout"}:
                raise ValueError("invalid partition")
            if type(item["prior_development_use"]) is not bool:
                raise ValueError("prior development use must be explicitly checked")
            normalized.append(item)
        with self.ledger.transaction() as conn:
            if self.ledger.get_state("evaluation_split", conn=conn):
                raise ValueError("split is frozen; create a separate evaluation cohort, not an overwrite")
            sources = [row["source_id"] for row in normalized]
            if len(sources) != len(set(sources)):
                raise ValueError("source appears more than once")
            registered = {row["id"] for row in self.ledger.list_records("source", conn=conn)}
            if set(sources) != registered:
                raise ValueError("split must include all currently registered sources, and no unregistered source")
            materials = {source_id: self._material(source_id, conn=conn) for source_id in sources}
            known_families = self._known_families(conn=conn)
            families, blobs = {}, {}
            for row in normalized:
                source_id, family, partition = row["source_id"], row["work_family"], row["partition"]
                if source_id in known_families and known_families[source_id] != family:
                    raise ValueError("assignment cannot override an already reviewed work family")
                sha = materials[source_id]["blob_sha256"]
                if family in families and families[family] != partition:
                    raise ValueError("work-family leakage across partitions")
                if sha in blobs and blobs[sha] != partition:
                    raise ValueError("same-blob leakage across partitions")
                families[family], blobs[sha] = partition, partition
            uses = self.ledger.list_records("development_use", conn=conn)
            used_sources = {record["source_id"] for record in uses}
            used_blobs = {record["blob_sha256"] for record in uses}
            assigned_families = {row["source_id"]: row["work_family"] for row in normalized}
            used_families = {assigned_families[source_id] for source_id in used_sources if source_id in assigned_families}
            verified = []
            for row in normalized:
                source = materials[row["source_id"]]
                observed = (row["source_id"] in used_sources or source["blob_sha256"] in used_blobs
                            or row["work_family"] in used_families)
                if row["partition"] != "development" and (row["prior_development_use"] or observed):
                    raise ValueError("recorded or declared development material cannot become independent holdout/calibration")
                verified.append({**row, "source_revision_id": source["source_revision_id"],
                                 "blob_sha256": source["blob_sha256"], "observed_development_use": observed})
                if row["source_id"] not in known_families:
                    family_record = {"source_id": row["source_id"], "source_revision_id": source["source_revision_id"],
                                     "blob_sha256": source["blob_sha256"], "work_family": row["work_family"],
                                     "reviewer": reviewer, "reason": "reviewed for evaluation partition", "created_at": utcnow()}
                    self.ledger.put_record("source_work_family", row["source_id"], family_record, conn=conn)
            record = {"id": new_id("split"), "assignments": verified, "reviewer": reviewer,
                      "created_at": utcnow(), "status": "frozen", "gold_status": "not_created",
                      "cohort_policy": "all_registered_sources; no post-freeze additions"}
            record["digest"] = content_hash(record)
            self.ledger.put_record("evaluation_split", record["id"], record, conn=conn)
            self.ledger.set_state("evaluation_split", record["id"], conn=conn)
            self.ledger.append_event("evaluation_split_frozen", record["id"],
                                     {"families": len(families), "blobs": len(blobs)}, conn=conn)
            return record

    def _assert_development_allowed(self, source: dict, *, conn) -> None:
        split_id = self.ledger.get_state("evaluation_split", conn=conn)
        if not split_id:
            return
        split = self.ledger.get_record("evaluation_split", split_id, conn=conn)
        if split is None:
            raise ValueError("evaluation split state has no immutable manifest")
        assignment = next((row for row in split["assignments"] if row["source_id"] == source["id"]), None)
        if assignment is None:
            raise ValueError("source was not registered in frozen split; create a separate evaluation cohort")
        if assignment["partition"] != "development":
            raise ValueError("sealed evaluation source cannot enter development extraction")
        # Defensive runtime checks also cover old manifests and corrected identity records.
        family = self._known_families(conn=conn).get(source["id"])
        for row in split["assignments"]:
            if row["partition"] != "development" and (
                row.get("blob_sha256") == source["blob_sha256"]
                or (family is not None and row["work_family"] == family)
            ):
                raise ValueError("development source shares a blob or known family with sealed evaluation material")

    def assert_development_allowed(self, source_id: str) -> None:
        """Read-only gate; workers must additionally mark exposure before dispatch."""
        with self.ledger.transaction() as conn:
            source = self._material(source_id, conn=conn)
            self._assert_development_allowed(source, conn=conn)

    def mark_development_use(self, source_id: str, reason: str, run_id: str) -> dict:
        """Atomically gate and record development exposure before a task reads it.

        The run must be a persisted task whose input explicitly names this source.
        Failed/cancelled runs do not erase exposure. This cannot observe work done
        outside the application; external exposure must also be declared honestly.
        """
        source_id = self._text(source_id, "source_id")
        reason, run_id = self._text(reason, "reason"), self._text(run_id, "run_id")
        with self.ledger.transaction() as conn:
            source = self._material(source_id, conn=conn)
            self._assert_development_allowed(source, conn=conn)
            run = self.ledger.get_record("task_submission", run_id, conn=conn)
            if run is None:
                raise ValueError("development use requires a registered task run")
            inputs = run.get("input_snapshot", {})
            if not isinstance(inputs, dict):
                raise ValueError("development run has an invalid input snapshot")
            source_ids = inputs.get("source_ids", [])
            if inputs.get("source_id") != source_id and (
                not isinstance(source_ids, list) or source_id not in source_ids
            ):
                raise ValueError("development run must explicitly reference this source")
            identity = content_hash({"source_id": source_id, "run_id": run_id, "reason": reason})
            record_id = f"development-use-{identity}"
            previous = self.ledger.get_record("development_use", record_id, conn=conn)
            if previous:
                return previous
            record = {"id": record_id, "source_id": source_id, "run_id": run_id, "reason": reason,
                      "source_revision_id": source["source_revision_id"], "blob_sha256": source["blob_sha256"],
                      "work_family": self._known_families(conn=conn).get(source_id),
                      "created_at": utcnow()}
            self.ledger.put_record("development_use", record_id, record, conn=conn)
            self.ledger.append_event("development_use_registered", source_id,
                                     {"record_id": record_id, "run_id": run_id, "reason": reason}, conn=conn)
            return record
