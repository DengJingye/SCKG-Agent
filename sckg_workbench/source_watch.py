"""One-shot checks for an archived URL source's original byte revision.

This module never replaces a source, publishes knowledge, or runs on a timer.
Changed bytes are quarantined as an immutable candidate for later human review.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile

from .sources import (DEFAULT_TIMEOUT, MAX_SOURCE_BYTES, FetchResult, SourceError,
                      SourceService, fetch_public_url, validate_remote_url)
from .storage import Ledger, content_hash, new_id, utcnow


class SourceWatchError(ValueError):
    pass


_PINNED_GITHUB = re.compile(r"^https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/", re.IGNORECASE)


class SourceUpdateService:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger
        self.workspace = ledger.workspace

    def _source(self, source_id: str) -> tuple[dict, dict]:
        if not isinstance(source_id, str) or not source_id:
            raise SourceWatchError("A source ID is required")
        source = self.ledger.get_record("source", source_id)
        if source is None:
            raise SourceWatchError("Unknown source")
        if source.get("acquisition_method") != "url":
            raise SourceWatchError("Only URL-acquired sources support update checks")
        acquisition = self.ledger.get_record("acquisition", source.get("acquisition_id", ""))
        revision = self.ledger.get_record("source_revision", source.get("source_revision_id", ""))
        if (not acquisition or acquisition.get("method") != "url"
                or acquisition.get("source_id") != source_id
                or acquisition.get("source_revision_id") != source["source_revision_id"]
                or not revision or revision.get("source_id") != source_id
                or revision.get("blob_sha256") != source["blob_sha256"]):
            raise SourceWatchError("Archived source acquisition or revision is inconsistent")
        return source, acquisition

    def _original_intact(self, source: dict) -> bool:
        path = self.workspace.artifacts_dir / "source_blobs" / source["blob_sha256"]
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
                return False
            return hashlib.sha256(path.read_bytes()).hexdigest() == source["blob_sha256"]
        except OSError:
            return False

    def _candidate_blob(self, data: bytes, sha: str) -> str:
        directory = self.workspace.artifacts_dir / "source_update_candidates"
        if directory.is_symlink():
            raise SourceWatchError("Candidate artifact directory must not be a symlink")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / sha
        if path.is_symlink():
            raise SourceWatchError("Candidate blob must not be a symlink")
        descriptor, temporary = tempfile.mkstemp(prefix=".source-update-", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != data:
                    raise SourceWatchError("Immutable candidate blob differs from its digest")
        finally:
            os.unlink(temporary)
        return str(path.relative_to(self.workspace.root))

    def _receipt(self, source: dict, acquisition: dict, *, status: str,
                 observed_sha256: str | None = None, candidate_blob_path: str | None = None,
                 final_url: str | None = None, content_type: str | None = None,
                 redirects: tuple[str, ...] = (), error_code: str | None = None) -> dict:
        if status not in {"unchanged", "changed", "error"}:
            raise SourceWatchError("Invalid check status")
        with self.ledger.transaction() as conn:
            candidate_id = None
            if status == "changed":
                if not observed_sha256 or not candidate_blob_path:
                    raise SourceWatchError("Changed bytes require a candidate artifact")
                candidate_id = "source-update-" + content_hash(
                    [source["id"], source["source_revision_id"], observed_sha256])
                candidate = self.ledger.get_record("source_update_candidate", candidate_id, conn=conn)
                if candidate is None:
                    candidate = {"id": candidate_id, "source_id": source["id"],
                                 "base_source_revision_id": source["source_revision_id"],
                                 "base_blob_sha256": source["blob_sha256"],
                                 "candidate_blob_sha256": observed_sha256,
                                 "candidate_blob_path": candidate_blob_path,
                                 "status": "candidate_only", "created_at": utcnow()}
                    self.ledger.put_record("source_update_candidate", candidate_id, candidate, conn=conn)
            receipt = {"id": new_id("source-update-check"), "schema_version": "source-update-check-v1",
                       "source_id": source["id"], "source_revision_id": source["source_revision_id"],
                       "acquisition_id": acquisition["id"],
                       "requested_url_sha256": hashlib.sha256(acquisition["requested_url"].encode()).hexdigest(),
                       "base_blob_sha256": source["blob_sha256"], "observed_blob_sha256": observed_sha256,
                       "candidate_id": candidate_id, "status": status, "error_code": error_code,
                       "final_url_sha256": hashlib.sha256(final_url.encode()).hexdigest() if final_url else None,
                       "content_type": content_type, "redirect_count": len(redirects), "checked_at": utcnow(),
                       "authority": "byte_comparison_only_no_scientific_review"}
            self.ledger.put_record("source_update_check", receipt["id"], receipt, conn=conn)
            self.ledger.append_event("source_update_checked", source["id"],
                                     {"check_id": receipt["id"], "status": status, "candidate_id": candidate_id}, conn=conn)
        return receipt

    def check(self, source_id: str, *, allow_network: bool = False, fetcher=None) -> dict:
        """Fetch once through the secure transport after explicit network opt-in."""
        if allow_network is not True:
            raise SourceWatchError("Update check requires explicit allow_network=True")
        source, acquisition = self._source(source_id)
        requested_url = acquisition.get("requested_url")
        try:
            requested_url, _ = validate_remote_url(requested_url)
        except SourceError as exc:
            return self._receipt(source, acquisition, status="error", error_code="invalid_archived_url")
        if source.get("metadata", {}).get("source_kind") == "github_file" or _PINNED_GITHUB.match(requested_url):
            return self._receipt(source, acquisition, status="error", error_code="fixed_revision_not_pollable")
        if not self._original_intact(source):
            return self._receipt(source, acquisition, status="error", error_code="original_blob_missing_or_changed")
        try:
            result = (fetcher or fetch_public_url)(requested_url, timeout=DEFAULT_TIMEOUT, max_bytes=MAX_SOURCE_BYTES)
            if not isinstance(result, FetchResult) or not isinstance(result.data, bytes):
                raise SourceError("Fetcher returned an invalid response")
            if not result.data or len(result.data) > MAX_SOURCE_BYTES:
                raise SourceError("Fetched source bytes are empty or oversized")
            if not isinstance(result.content_type, str) or len(result.content_type) > 200:
                raise SourceError("Fetched source content type is invalid")
            if not isinstance(result.redirects, tuple) or len(result.redirects) > 5:
                raise SourceError("Fetched source redirect history is invalid")
            final_url, _ = validate_remote_url(result.final_url)
            for redirect in result.redirects:
                validate_remote_url(redirect)
            sha = hashlib.sha256(result.data).hexdigest()
            candidate_path = self._candidate_blob(result.data, sha) if sha != source["blob_sha256"] else None
        except (SourceError, SourceWatchError, OSError, ValueError) as exc:
            return self._receipt(source, acquisition, status="error", error_code=type(exc).__name__)
        return self._receipt(source, acquisition,
                             status="changed" if candidate_path else "unchanged", observed_sha256=sha,
                             candidate_blob_path=candidate_path, final_url=final_url,
                             content_type=result.content_type, redirects=result.redirects)

    def stage_candidate(self, candidate_id: str, *, actor: str, reason: str) -> dict:
        """Register candidate bytes as a NEW provisional source for later review."""
        if any(not isinstance(value, str) or not value.strip() for value in (candidate_id, actor, reason)):
            raise SourceWatchError("Candidate ID, actor and reason are required")
        candidate = self.ledger.get_record("source_update_candidate", candidate_id)
        if candidate is None or candidate.get("status") != "candidate_only":
            raise SourceWatchError("Unknown or ineligible source update candidate")
        source, _ = self._source(candidate["source_id"])
        if (candidate.get("base_source_revision_id") != source["source_revision_id"]
                or candidate.get("base_blob_sha256") != source["blob_sha256"]
                or not self._original_intact(source)):
            raise SourceWatchError("Base source revision or original blob no longer matches")
        sha = candidate["candidate_blob_sha256"]
        expected = Path("artifacts") / "source_update_candidates" / sha
        if candidate.get("candidate_blob_path") != str(expected):
            raise SourceWatchError("Candidate blob path is not content-addressed")
        path = self.workspace.root / expected
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            raise SourceWatchError("Candidate blob is missing or invalid")
        data = path.read_bytes()
        if not data or hashlib.sha256(data).hexdigest() != sha:
            raise SourceWatchError("Candidate blob integrity check failed")
        metadata = {"source_kind": "source_update_candidate", "updates_source_id": source["id"],
                    "base_source_revision_id": source["source_revision_id"],
                    "source_update_candidate_id": candidate_id}
        exposure = source.get("metadata", {}).get("evaluation_exposure")
        if exposure in {"development", "holdout", "calibration"}:
            metadata["evaluation_exposure"] = exposure
        staged = SourceService(self.ledger).register_bytes(source["filename"], data,
            request_id="stage-source-update:" + candidate_id, media_type=source["media_type"], metadata=metadata)
        stage_id = "source-update-stage-" + content_hash(candidate_id)
        with self.ledger.transaction() as conn:
            existing = self.ledger.get_record("source_update_stage", stage_id, conn=conn)
            if existing is not None:
                if existing["staged_source_id"] != staged["id"]:
                    raise SourceWatchError("A source update candidate was staged inconsistently")
                return {"stage": existing, "source": staged}
            record = {"id": stage_id, "source_update_candidate_id": candidate_id,
                      "base_source_id": source["id"], "base_source_revision_id": source["source_revision_id"],
                      "staged_source_id": staged["id"], "staged_source_revision_id": staged["source_revision_id"],
                      "actor": actor.strip(), "reason": reason.strip(), "created_at": utcnow(),
                      "status": "provisional_source_only"}
            self.ledger.put_record("source_update_stage", stage_id, record, conn=conn)
            self.ledger.append_event("source_update_staged", candidate_id,
                                     {"stage_id": stage_id, "staged_source_id": staged["id"]}, conn=conn)
        return {"stage": record, "source": staged}
