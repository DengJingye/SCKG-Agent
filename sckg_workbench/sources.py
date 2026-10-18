"""Unreviewed source acquisition with immutable originals and bounded parsing.

No source is trusted by its extension, URL, domain, or byte identity. Remote
retrieval only occurs through the explicit register_url/register_github methods
with allow_network=True; the default transport pins validated public addresses.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from .parsing import parse_document

MAX_SOURCE_BYTES = 25 * 1024 * 1024
DEFAULT_TIMEOUT = 20.0


class SourceError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex


def validate_remote_url(url: str, *, resolve: bool = False) -> tuple[str, list[str]]:
    """Reject local schemes/addresses; optionally resolve and validate every IP."""
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 33 for c in url):
        raise SourceError("URL is invalid or contains whitespace/control characters")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise SourceError("Invalid URL") from exc
    if parts.scheme not in {"https", "http"} or not host:
        raise SourceError("Only explicit public HTTP(S) source URLs are supported")
    if parts.username is not None or parts.password is not None or "\\" in url:
        raise SourceError("URL credentials and backslashes are not accepted")
    if port is not None and port != (443 if parts.scheme == "https" else 80):
        raise SourceError("Only standard HTTP(S) ports are allowed")
    host = host.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "%" in host:
        raise SourceError("Local hosts are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise SourceError("Non-public IP addresses are not allowed")
    addresses = []
    if resolve:
        try:
            infos = socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError as exc:
            raise SourceError("Source hostname could not be resolved") from exc
        addresses = sorted({info[4][0] for info in infos})
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise SourceError("Source hostname resolves to a non-public address")
    normalized = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))
    return normalized, addresses


@dataclass(frozen=True)
class FetchResult:
    data: bytes
    final_url: str
    content_type: str = "application/octet-stream"
    redirects: tuple[str, ...] = ()


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, timeout=timeout)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def fetch_public_url(url: str, *, timeout: float = DEFAULT_TIMEOUT, max_bytes: int = MAX_SOURCE_BYTES) -> FetchResult:
    """Fetch with bounded reads, no cookies, and public-IP pinning on every hop."""
    if timeout <= 0 or max_bytes < 1:
        raise SourceError("Fetch limits must be positive")
    history = []
    deadline = time.monotonic() + timeout
    for _ in range(6):
        current, addresses = validate_remote_url(url, resolve=True)
        parts = urlsplit(current)
        connection_class = _PinnedHTTPSConnection if parts.scheme == "https" else _PinnedHTTPConnection
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceError("Remote fetch timed out")
        connection = connection_class(parts.hostname, addresses[0], remaining)
        try:
            target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            connection.request("GET", target, headers={"User-Agent": "scKG-Workbench/1.0", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise SourceError("Redirect response has no Location")
                history.append(current)
                url = urljoin(current, location)
                continue
            if response.status != 200:
                raise SourceError(f"Remote source returned HTTP {response.status}")
            encoding = response.getheader("Content-Encoding", "identity").lower()
            if encoding not in {"", "identity"}:
                raise SourceError("Encoded remote responses are not supported by this bounded fetcher")
            length = response.getheader("Content-Length")
            if length is not None:
                try:
                    if int(length) < 0 or int(length) > max_bytes:
                        raise SourceError("Remote source exceeds the size limit")
                except ValueError as exc:
                    raise SourceError("Invalid or oversized remote Content-Length") from exc
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SourceError("Remote fetch timed out")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise SourceError("Remote source exceeds the size limit")
                chunks.append(chunk)
            data = b"".join(chunks)
            return FetchResult(data, current, response.getheader("Content-Type", "application/octet-stream"), tuple(history))
        except (OSError, http.client.HTTPException) as exc:
            raise SourceError(f"Remote fetch failed: {type(exc).__name__}") from exc
        finally:
            connection.close()
    raise SourceError("Too many redirects")


def github_raw_url(repo: str, commit: str, path: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        raise SourceError("GitHub repo must be owner/repository")
    if any(part in {".", ".."} for part in repo.split("/")):
        raise SourceError("GitHub repo must name an owner and repository")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit or ""):
        raise SourceError("GitHub sources require an explicit full 40-character commit SHA")
    if not path or path.startswith("/") or "\\" in path or any(ord(c) < 32 for c in path):
        raise SourceError("GitHub sources require an exact relative file path")
    segments = path.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise SourceError("GitHub path traversal is not allowed")
    return f"https://raw.githubusercontent.com/{repo}/{commit.lower()}/{quote(path, safe='/')}"


class SourceService:
    def __init__(self, ledger):
        self.ledger = ledger
        self.workspace = ledger.workspace
        self.blob_dir = Path(self.workspace.artifacts_dir) / "source_blobs"

    def _cached(self, request_id: str | None, fingerprint: str, *, conn=None):
        if request_id is None:
            return None
        if not isinstance(request_id, str) or not request_id or len(request_id) > 200:
            raise SourceError("request_id must contain 1–200 characters")
        key = "source_request:" + hashlib.sha256(request_id.encode()).hexdigest()
        cached = self.ledger.get_state(key, conn=conn)
        if cached:
            if cached["fingerprint"] != fingerprint:
                raise SourceError("request_id was already used for a different acquisition")
            return cached["result"]
        return None

    @staticmethod
    def _fingerprint(value) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()

    def _store_blob(self, data: bytes, sha: str) -> Path:
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        path = self.blob_dir / sha
        if path.is_symlink():
            raise SourceError("Original blob must not be a symlink")
        descriptor, temporary = tempfile.mkstemp(prefix=".acquiring-", dir=self.blob_dir)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != data:
                    raise SourceError("Immutable source blob is corrupted or has a hash collision")
        finally:
            os.unlink(temporary)
        return path

    def register_bytes(self, filename: str, data: bytes, *, request_id: str | None = None,
                       media_type: str | None = None, metadata: dict | None = None) -> dict:
        return self._register(filename, data, request_id=request_id, media_type=media_type, metadata=metadata,
                              acquisition={"method": "upload"})

    def _register(self, filename, data, *, request_id, media_type, metadata, acquisition, fingerprint=None):
        if not isinstance(data, bytes) or not data:
            raise SourceError("Source must contain non-empty bytes")
        if len(data) > MAX_SOURCE_BYTES:
            raise SourceError("Source exceeds the 25 MiB size limit")
        if not isinstance(filename, str) or not filename or any(ord(c) < 32 for c in filename):
            raise SourceError("A valid source filename is required")
        filename = Path(filename.replace("\\", "/")).name
        if filename in {"", ".", ".."} or len(filename) > 255:
            raise SourceError("Invalid source filename")
        metadata = dict(metadata or {})
        reserved = {"id", "source_id", "source_revision_id", "blob_path", "blob_sha256", "identity_status", "trust_status", "review_status", "trusted", "reviewed", "verified", "human_reviewed"}
        if reserved.intersection(metadata):
            raise SourceError("Source metadata cannot assign identity, storage, or review/trust state")
        sha = hashlib.sha256(data).hexdigest()
        fingerprint = fingerprint or self._fingerprint([filename, sha, media_type, metadata, acquisition])
        with self.ledger.transaction() as conn:
            cached = self._cached(request_id, fingerprint, conn=conn)
            if cached:
                return cached
            path = self._store_blob(data, sha)
            source_id, revision_id = _id("src"), _id("srcrev")
            acquisition_id, original_id, snapshot_id = _id("acq"), _id("original"), _id("snapshot")
            timestamp = _now()
            source = {"id": source_id, "source_id": source_id, "source_revision_id": revision_id,
                      "acquisition_id": acquisition_id, "original_id": original_id, "snapshot_id": snapshot_id,
                      "filename": filename, "media_type": media_type or "application/octet-stream", "size_bytes": len(data),
                      "blob_sha256": sha, "identity_status": "provisional", "trust_status": "unreviewed",
                      "created_at": timestamp, "metadata": metadata, "acquisition_method": acquisition["method"]}
            relative = str(path.relative_to(self.workspace.root))
            records = [
                ("original", original_id, {"id": original_id, "blob_sha256": sha, "blob_path": relative, "size_bytes": len(data)}),
                ("snapshot", snapshot_id, {"id": snapshot_id, "original_id": original_id, "captured_at": timestamp, "acquisition": acquisition}),
                ("acquisition", acquisition_id, {"id": acquisition_id, "source_id": source_id, "source_revision_id": revision_id, "snapshot_id": snapshot_id, "received_at": timestamp, **acquisition}),
                ("source_revision", revision_id, {"id": revision_id, "source_id": source_id, "original_id": original_id, "snapshot_id": snapshot_id, "blob_sha256": sha, "created_at": timestamp}),
                ("source", source_id, source),
            ]
            for kind, record_id, payload in records:
                self.ledger.put_record(kind, record_id, payload, conn=conn)
            self.ledger.append_event("source_registered", source_id, {"acquisition_id": acquisition_id, "source_revision_id": revision_id, "snapshot_id": snapshot_id, "blob_sha256": sha}, conn=conn)
            if request_id is not None:
                key = "source_request:" + hashlib.sha256(request_id.encode()).hexdigest()
                self.ledger.set_state(key, {"fingerprint": fingerprint, "result": source}, conn=conn)
        return source

    def register_url(self, url: str, *, allow_network: bool = False, request_id: str | None = None,
                     fetcher=None, metadata: dict | None = None) -> dict:
        if not allow_network:
            raise SourceError("Remote acquisition requires explicit allow_network=True")
        normalized, _ = validate_remote_url(url)
        fingerprint = self._fingerprint(["url", normalized, metadata or {}])
        cached = self._cached(request_id, fingerprint)
        if cached:
            return cached
        # An injected fetcher is a trusted transport boundary, useful for tests.
        # Production should use fetch_public_url, which resolves/pins every hop.
        result = (fetcher or fetch_public_url)(normalized, timeout=DEFAULT_TIMEOUT, max_bytes=MAX_SOURCE_BYTES)
        if not isinstance(result, FetchResult):
            raise SourceError("Fetcher must return FetchResult; arbitrary responses are not accepted")
        final_url, _ = validate_remote_url(result.final_url)
        for redirect in result.redirects:
            validate_remote_url(redirect)
        filename = PurePosixPath(unquote(urlsplit(final_url).path)).name or "source"
        content_type = result.content_type.split(";", 1)[0].strip().lower()
        if not Path(filename).suffix:
            filename += {"text/html": ".html", "application/pdf": ".pdf", "text/plain": ".txt", "text/markdown": ".md", "application/xml": ".xml", "text/xml": ".xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx"}.get(content_type, ".bin")
        return self._register(filename, result.data, request_id=request_id, media_type=content_type, metadata=metadata,
                              acquisition={"method": "url", "requested_url": normalized, "final_url": final_url, "redirects": list(result.redirects)}, fingerprint=fingerprint)

    def register_github(self, repo: str, commit: str, path: str, *, allow_network: bool = False,
                        request_id: str | None = None, fetcher=None) -> dict:
        url = github_raw_url(repo, commit, path)

        def fixed_revision_fetcher(target, **kwargs):
            result = (fetcher or fetch_public_url)(target, **kwargs)
            if not isinstance(result, FetchResult) or result.final_url != url:
                raise SourceError("GitHub retrieval did not retain the requested immutable commit/path URL")
            return result

        return self.register_url(url, allow_network=allow_network, request_id=request_id, fetcher=fixed_revision_fetcher,
                                 metadata={"source_kind": "github_file", "repo": repo, "commit": commit.lower(), "path": path})

    def parse(self, source_id: str, *, max_pages: int = 200, max_chars: int = 1_000_000, max_blocks: int = 20000) -> dict:
        source = self.ledger.get_record("source", source_id)
        if not source:
            raise SourceError("Unknown source")
        revision = self.ledger.get_record("source_revision", source["source_revision_id"])
        original = self.ledger.get_record("original", revision["original_id"])
        # Never trust a ledger pathname for read access; reconstruct from its digest.
        sha = original["blob_sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise SourceError("Invalid original digest")
        path = self.blob_dir / sha
        if path.is_symlink():
            raise SourceError("Original blob must not be a symlink")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise SourceError("Original blob integrity check failed")
        ir = parse_document(data, source["filename"], source_id=source_id, source_revision_id=revision["id"],
                            max_pages=max_pages, max_chars=max_chars, max_blocks=max_blocks)
        with self.ledger.transaction() as conn:
            existing = self.ledger.get_record("document_ir", ir["id"], conn=conn)
            if existing:
                return existing
            self.ledger.put_record("document_ir", ir["id"], ir, conn=conn)
            self.ledger.append_event("source_parsed", source_id, {"document_ir_id": ir["id"], "status": ir["status"], "coverage": ir["coverage"]}, conn=conn)
        return ir
