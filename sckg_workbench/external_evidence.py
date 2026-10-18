"""Read-only, versioned evidence for other local agents.

Scientific approval and permission to redistribute source-derived text are
separate decisions. This boundary never promotes a candidate or assumes that
an uploaded source's license permits external use.
"""
from __future__ import annotations

from contextlib import contextmanager
import re
import sqlite3

from .catalog import Catalog
from .knowledge import KnowledgeService
from .storage import Ledger, Workspace, content_hash, new_id, utcnow


class ExternalEvidenceError(ValueError):
    pass


def _copies_source_expression(fields: list[str], quote: str) -> bool:
    """Conservative guard for claims-only reuse; no legal judgment is inferred."""
    original = " ".join(quote.split()).casefold()
    if not original:
        return False
    if len(original) > 100_000:
        # Do not allocate a huge overlap index for an oversized parser block.
        return True
    character_windows = {original[i:i + 20] for i in range(len(original) - 19)}
    source_words = re.findall(r"[a-z0-9_]+", original)
    source_cjk = re.findall(r"[\u3400-\u9fff]+", original)
    for field in fields:
        text = " ".join(field.split()).casefold()
        if len(original) >= 12 and original in text:
            return True
        if any(text[i:i + 20] in character_windows for i in range(len(text) - 19)):
            return True
        words = re.findall(r"[a-z0-9_]+", text)
        if len(source_words) >= 6 and len(words) >= 6:
            windows = {tuple(source_words[i:i + 6]) for i in range(len(source_words) - 5)}
            if any(tuple(words[i:i + 6]) in windows for i in range(len(words) - 5)):
                return True
        text_cjk = "".join(re.findall(r"[\u3400-\u9fff]+", text))
        if len(text_cjk) >= 12 and any(run[index:index + 12] in text_cjk
                                       for run in source_cjk for index in range(len(run) - 11)):
            return True
    return False


class SourceExportRights:
    """Record an explicit human decision about one immutable source revision."""

    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def review(self, source_id: str, *, reviewer: str, license_ref: str,
               claims_allowed: bool, quotes_allowed: bool, reason: str,
               expected_source_revision_id: str, expected_blob_sha256: str) -> dict:
        if any(not isinstance(value, str) or not value.strip() for value in
               (source_id, reviewer, license_ref, reason, expected_source_revision_id, expected_blob_sha256)):
            raise ExternalEvidenceError("Source, reviewer, license reference, reason and exact revision are required")
        if type(claims_allowed) is not bool or type(quotes_allowed) is not bool or (quotes_allowed and not claims_allowed):
            raise ExternalEvidenceError("Quote reuse requires claim reuse; decisions must be explicit booleans")
        with self.ledger.transaction() as conn:
            source = self.ledger.get_record("source", source_id, conn=conn)
            if source is None or source["source_revision_id"] != expected_source_revision_id or source["blob_sha256"] != expected_blob_sha256:
                raise ExternalEvidenceError("Source revision changed or does not exist; inspect the exact original")
            record = {"id": new_id("source-export-review"), "source_id": source_id,
                      "source_revision_id": expected_source_revision_id, "blob_sha256": expected_blob_sha256,
                      "reviewer": reviewer.strip(), "license_ref": license_ref.strip(), "reason": reason.strip(),
                      "claims_allowed": claims_allowed, "quotes_allowed": quotes_allowed,
                      "authority": "explicit_local_human_action", "created_at": utcnow()}
            self.ledger.put_record("source_export_review", record["id"], record, conn=conn)
            self.ledger.set_state("source_export_review:" + source_id, record["id"], conn=conn)
            version = self.ledger.get_state("source_export_rights_version", 0, conn=conn) + 1
            self.ledger.set_state("source_export_rights_version", version, conn=conn)
            self.ledger.append_event("source_export_rights_reviewed", source_id,
                                     {"review_id": record["id"], "rights_version": version}, conn=conn)
        return record


class _ReadOnlyLedger(Ledger):
    def __init__(self, workspace: Workspace, connection: sqlite3.Connection):
        # Ledger.__init__ creates schema. An external read must never do that.
        self.workspace = workspace
        self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection


class _ReadOnlyKnowledge(KnowledgeService):
    def __init__(self, ledger: Ledger):
        # KnowledgeService.__init__ creates the FTS projection.
        self.ledger = ledger


class ExternalEvidenceService:
    """A single local application service; adapters must only call these methods."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    @contextmanager
    def _session(self):
        workspace = self.workspace
        for path in (workspace.db_path, workspace.root / "workspace.json",
                     workspace.root / "ledger.sqlite3-wal", workspace.root / "ledger.sqlite3-shm"):
            if path.is_symlink():
                raise ExternalEvidenceError("Workspace identity and ledger must not be symlinks")
        if not workspace.db_path.is_file():
            raise ExternalEvidenceError("An initialized workbench is required")
        namespace = workspace.namespace
        conn = sqlite3.connect(workspace.db_path.as_uri() + "?mode=ro", uri=True, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        try:
            ledger = _ReadOnlyLedger(workspace, conn)
            row = conn.execute("SELECT value FROM metadata WHERE key='namespace'").fetchone()
            if row is None or row[0] != namespace:
                raise ExternalEvidenceError("Ledger belongs to another workspace")
            yield ledger, _ReadOnlyKnowledge(ledger), conn
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()

    @staticmethod
    def _version(ledger: Ledger, conn) -> dict:
        release_id = ledger.get_state("current_release", conn=conn)
        release = ledger.get_record("release", release_id, conn=conn) if release_id else None
        if release_id and release is None:
            raise ExternalEvidenceError("Current release manifest is missing")
        return {"namespace": ledger.workspace.namespace, "release_id": release_id,
                "manifest_hash": release.get("manifest_hash") if release else None,
                "ontology_version": release.get("ontology_version") if release else None,
                "manifest_unit_count": len(release["units"]) if release else 0,
                "governance_version": ledger.get_state("governance_version", 0, conn=conn),
                "source_export_rights_version": ledger.get_state("source_export_rights_version", 0, conn=conn),
                "status": "current_at_read", "offline_export_requires_refresh": True}

    def current_version(self) -> dict:
        with self._session() as (ledger, _, conn):
            conn.execute("BEGIN")
            return self._version(ledger, conn)

    @staticmethod
    def _right_for_source(ledger: Ledger, source_id: str, conn, catalog: Catalog) -> tuple[dict | None, dict | None]:
        source = ledger.get_record("source", source_id, conn=conn)
        if source is None:
            return None, None
        if source.get("metadata", {}).get("evaluation_exposure") in {"holdout", "calibration"}:
            return source, None
        # Frozen evaluation sources must not leak through an external adapter.
        try:
            catalog._assert_development_allowed(source, conn=conn)
        except ValueError:
            return source, None
        review_id = ledger.get_state("source_export_review:" + source_id, conn=conn)
        review = ledger.get_record("source_export_review", review_id, conn=conn) if review_id else None
        if (not review or review.get("source_id") != source_id
                or review.get("source_revision_id") != source["source_revision_id"]
                or review.get("blob_sha256") != source["blob_sha256"]
                or review.get("authority") != "explicit_local_human_action"
                or type(review.get("claims_allowed")) is not bool
                or type(review.get("quotes_allowed")) is not bool):
            return source, None
        return source, review

    @classmethod
    def _portable_unit(cls, unit: dict, ledger: Ledger, conn, catalog: Catalog) -> tuple[dict | None, list[dict]]:
        rights = {}
        sources = {}
        for anchor in unit["evidence"]:
            source_id = anchor["source_id"]
            if source_id in rights:
                continue
            source, review = cls._right_for_source(ledger, source_id, conn, catalog)
            if source is None or review is None or not review["claims_allowed"]:
                return None, []
            rights[source_id] = review
            metadata = source.get("metadata", {})
            sources[source_id] = {"source_id": source_id, "source_revision_id": source["source_revision_id"],
                                  "blob_sha256": source["blob_sha256"],
                                  "doi": metadata.get("doi") if isinstance(metadata.get("doi"), str) else None,
                                  "license_ref": review["license_ref"], "rights_review_id": review["id"],
                                  "claims_allowed": True, "quotes_allowed": review["quotes_allowed"]}
            if review["quotes_allowed"]:
                sources[source_id]["filename"] = source["filename"]
                sources[source_id]["title"] = metadata.get("title") if isinstance(metadata.get("title"), str) else None
        claim = unit["claim"]
        # Structured entity and relation labels can legitimately repeat a
        # source's factual terminology; screen prose-bearing fields instead.
        claim_fields = [str(value) for key in ("proposition", "conditions", "unknowns")
                        for value in ([claim[key]] if isinstance(claim[key], str) else claim[key])]
        claim_fields.extend(str(value) for attribute in claim.get("typed_attributes", [])
                            for value in (attribute["value"], *attribute["qualifiers"]))
        # A generated proposition can itself copy a substantial source span.
        # A claims-only review does not silently authorize that verbatim text.
        for anchor in unit["evidence"]:
            if (not rights[anchor["source_id"]]["quotes_allowed"]
                    and _copies_source_expression(claim_fields, anchor["quote"])):
                return None, []
        evidence = []
        for anchor in unit["evidence"]:
            source_id = anchor["source_id"]
            row = {"source_id": source_id, "source_revision_id": anchor["source_revision_id"],
                   "blob_sha256": anchor["blob_sha256"], "snapshot_id": anchor["snapshot_id"],
                   "ir_id": anchor["ir_id"], "block_id": anchor["block_id"],
                   "start": anchor["start"], "end": anchor["end"],
                   "quote_status": "included" if rights[source_id]["quotes_allowed"] else "withheld_by_rights"}
            if rights[source_id]["quotes_allowed"]:
                row["quote"] = anchor["quote"]
                row["locator"] = anchor["locator"]
            evidence.append(row)
        portable = {"candidate_id": unit["candidate_id"],
                    "claim": {key: claim[key] for key in ("proposition", "subject", "predicate", "object",
                             "polarity", "conditions", "unknowns", "assertion_kind")},
                    "evidence": evidence,
                    "assessment": {key: unit["assessment"][key] for key in ("relation", "extent")},
                    "allowed_uses": unit["allowed_uses"], "review_id": unit["review_id"],
                    "eligibility": "eligible_at_export_or_read"}
        if claim.get("typed_attributes"):
            portable["claim"]["typed_attributes"] = claim["typed_attributes"]
        return portable, list(sources.values())

    @classmethod
    def _render(cls, package, ledger, conn, limit: int | None = None) -> dict:
        catalog = Catalog(ledger)
        units, sources, blocked = [], {}, 0
        for unit in package.units:
            public, refs = cls._portable_unit(unit, ledger, conn, catalog)
            if public is None:
                blocked += 1
                continue
            units.append(public)
            for source in refs:
                sources[source["source_id"]] = source
            if limit is not None and len(units) >= limit:
                break
        gaps = list(package.gaps)
        if blocked:
            gaps.append("部分证据因来源再分发许可或评测隔离而未对外提供。")
        return {"units": units, "sources": [sources[key] for key in sorted(sources)],
                "gaps": list(dict.fromkeys(gaps))}

    def search_evidence(self, query: str, *, purpose: str = "explanation", limit: int = 10) -> dict:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ExternalEvidenceError("Search limit must be 1–100")
        with self._session() as (ledger, knowledge, conn):
            catalog = Catalog(ledger)
            withheld = 0

            def externally_usable(unit, snapshot_conn):
                nonlocal withheld
                portable, _ = self._portable_unit(unit, ledger, snapshot_conn, catalog)
                if portable is None:
                    withheld += 1
                    return False
                return True

            # Check reuse permission before applying the caller's result limit.
            # The callback shares KnowledgeService's release/governance snapshot.
            package = knowledge.search(query, purpose=purpose, limit=limit, unit_filter=externally_usable)
            version = self._version(ledger, conn)
            result = self._render(package, ledger, conn, limit)
            if withheld:
                result["gaps"].append("部分匹配证据因来源再分发许可或评测隔离而未对外提供。")
            return {**version, "purpose": purpose,
                    "retrieval": {**package.retrieval, "candidate_scan": "all_ranked_until_limit",
                                  "more_eligible_results_possible": len(package.units) == limit}, **result}

    def resolve_evidence(self, candidate_ids: list[str], *, purpose: str = "explanation") -> dict:
        if not isinstance(candidate_ids, list) or len(candidate_ids) > 100:
            raise ExternalEvidenceError("Resolve accepts at most 100 exact candidate IDs")
        with self._session() as (ledger, knowledge, conn):
            package = knowledge.resolve(candidate_ids, purpose=purpose)
            version = self._version(ledger, conn)
            return {**version, "purpose": purpose, "retrieval": package.retrieval,
                    **self._render(package, ledger, conn)}

    def export_knowledge(self, *, purpose: str = "explanation") -> dict:
        if purpose not in {"explanation", "recommendation"}:
            raise ExternalEvidenceError("Invalid export purpose")
        with self._session() as (ledger, knowledge, conn):
            conn.execute("BEGIN")
            version = self._version(ledger, conn)
            release = ledger.get_record("release", version["release_id"], conn=conn) if version["release_id"] else None
            manifests = release["units"] if release else []
            if len(manifests) > 10000:
                raise ExternalEvidenceError("Release exceeds bounded portable export size")
            units, gaps = [], []
            for manifest in manifests:
                item = knowledge._eligible_unit(manifest, purpose=purpose, conn=conn, gaps=gaps)
                if item is not None:
                    units.append(item)
            # Use the same renderer as live search and exact resolution.
            package = type("_Package", (), {"units": units, "gaps": gaps})()
            rendered = self._render(package, ledger, conn)
            result = {"schema_version": "sckg-portable-evidence-v1", **version, "purpose": purpose,
                      "manifest_unit_count": len(manifests), "eligible_unit_count": len(units), **rendered}
            result["snapshot_hash"] = content_hash(result)
            result["captured_at"] = utcnow()
            return result
