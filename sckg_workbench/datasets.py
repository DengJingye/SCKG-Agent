"""Local H5AD registration and bounded, read-only measurements.

No AnnData materialization, outbound calls or scientific state classification
occur here. Local references are never fully scanned; explicit small uploads are
hashed in full. A sampled integer matrix is not certified raw counts.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import itertools
import math
import os
from pathlib import Path
import stat
from typing import Any

from .contracts import DatasetProfile
from .storage import Ledger, Workspace, content_hash, new_id, utcnow


FINGERPRINT_WINDOW = 65536
MAX_METADATA_KEYS = 64
MAX_DECODED_BYTES = 16 * 1024 * 1024
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class DatasetChangedError(ValueError):
    """The registered file no longer matches the local version being inspected."""


def _signature(st: os.stat_result) -> dict[str, int]:
    return {"device": st.st_dev, "inode": st.st_ino, "size": st.st_size,
            "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns}


def _fingerprint(handle, size: int) -> dict[str, Any]:
    width = min(size, FINGERPRINT_WINDOW)
    offsets = sorted({0, max(0, (size - width) // 2), max(0, size - width)})
    samples = []
    for offset in offsets:
        handle.seek(offset)
        block = handle.read(width)
        if len(block) != width:
            raise DatasetChangedError("file changed during bounded fingerprint read")
        samples.append({"offset": offset, "bytes": len(block),
                        "sha256": hashlib.sha256(block).hexdigest()})
    handle.seek(0)
    payload = {"method": "first_middle_last_windows", "file_size_bytes": size,
               "window_bytes": FINGERPRINT_WINDOW, "ranges": samples,
               "full_content_hash": False}
    return {**payload, "fingerprint_sha256": content_hash(payload)}


@contextmanager
def _open_local(path: Path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as handle:
        before = _signature(os.fstat(handle.fileno()))
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("dataset must be a regular local file")
        yield handle, before
        after = _signature(os.fstat(handle.fileno()))
        # Also detect path replacement while the original inode was held open.
        if before != after or before != _signature(path.stat()):
            raise DatasetChangedError("dataset changed while being read; register its new version")


def _local_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError("register a regular .h5ad path, not a symlink")
    path = path.resolve(strict=True)
    if path.suffix.lower() != ".h5ad" or not path.is_file():
        raise ValueError("an existing local .h5ad file is required")
    return path


def _safe_child(group, name: str, h5py):
    link = group.get(name, getlink=True)
    if link is None:
        return None
    if not isinstance(link, h5py.HardLink):
        raise ValueError("H5AD external and soft links are not read")
    obj = group[name]
    if isinstance(obj, h5py.Dataset) and (obj.is_virtual or obj.external):
        raise ValueError("virtual or externally stored HDF5 arrays are not read")
    return obj


def _keys(group, name: str, h5py) -> dict[str, Any]:
    obj = _safe_child(group, name, h5py)
    if obj is None:
        return {"keys": [], "truncated": False, "count": 0}
    if not isinstance(obj, h5py.Group):
        return {"keys": [], "truncated": False, "count": None, "unknown": "not_a_group"}
    keys = list(itertools.islice(obj.keys(), MAX_METADATA_KEYS + 1))
    return {"keys": keys[:MAX_METADATA_KEYS], "truncated": len(keys) > MAX_METADATA_KEYS,
            "count": len(obj)}


def _encoding(obj) -> str:
    value = obj.attrs.get("encoding-type", "")
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _axis_alignment(file, name: str, expected: int, h5py) -> str:
    group = _safe_child(file, name, h5py)
    if not isinstance(group, h5py.Group):
        return "unknown_no_dataframe_index"
    key = group.attrs.get("_index")
    if isinstance(key, bytes):
        key = key.decode("utf-8")
    if not isinstance(key, str) or "/" in key:
        return "unknown_no_dataframe_index"
    index = _safe_child(group, key, h5py)
    if not isinstance(index, h5py.Dataset) or len(index.shape) != 1:
        return "unknown_index_encoding"
    if index.shape[0] != expected:
        raise ValueError(f"{name} index length disagrees with X shape")
    return "index_length_matches_X_names_not_read"


def _matrix_shape(obj, h5py) -> tuple[int, int]:
    shape = obj.shape if isinstance(obj, h5py.Dataset) else obj.attrs.get("shape")
    if shape is None or len(shape) != 2 or any(int(n) < 0 for n in shape):
        raise ValueError("H5AD matrix must declare a two-dimensional shape")
    return int(shape[0]), int(shape[1])


def _read_budget_ok(dataset, requested_shape: tuple[int, ...]) -> bool:
    # A tiny slice may decompress an enormous HDF5 chunk. Bound decoded work too.
    if dataset.dtype.kind not in "biuf":
        return False
    if dataset.chunks is None:
        decoded = math.prod(requested_shape) * dataset.dtype.itemsize
    else:
        chunks = math.prod(math.ceil(n / c) for n, c in zip(requested_shape, dataset.chunks))
        decoded = chunks * math.prod(dataset.chunks) * dataset.dtype.itemsize
    return decoded <= MAX_DECODED_BYTES


def _sample_matrix(obj, matrix_id: str, h5py, np, *, rows: int, columns: int,
                   sparse_values: int) -> dict[str, Any]:
    shape = _matrix_shape(obj, h5py)
    result: dict[str, Any] = {"matrix_id": matrix_id, "shape": list(shape),
                              "representation_state": "unknown", "full_scan": False}
    if isinstance(obj, h5py.Dataset):
        nr, nc = min(rows, shape[0]), min(columns, shape[1])
        result.update(storage="dense", dtype=str(obj.dtype),
                      sampling={"method": "leading_rectangle", "row_range": [0, nr],
                                "column_range": [0, nc], "includes_implicit_zeros": True})
        if not _read_budget_ok(obj, (nr, nc)):
            return {**result, "status": "metadata_only", "unknown": "unsupported_dtype_or_chunk_decode_budget"}
        values = np.asarray(obj[:nr, :nc]).reshape(-1)
    else:
        encoding = _encoding(obj)
        if encoding not in {"csr_matrix", "csc_matrix"}:
            return {**result, "status": "metadata_only", "unknown": "unsupported_matrix_encoding"}
        arrays = {key: _safe_child(obj, key, h5py) for key in ("data", "indices", "indptr")}
        if any(not isinstance(v, h5py.Dataset) or len(v.shape) != 1 for v in arrays.values()):
            raise ValueError("sparse matrix requires one-dimensional data, indices and indptr")
        data = arrays["data"]
        expected_pointer_count = shape[0 if encoding == "csr_matrix" else 1] + 1
        if arrays["indices"].shape != data.shape or arrays["indptr"].shape[0] != expected_pointer_count:
            raise ValueError("sparse matrix component dimensions are inconsistent")
        count = min(sparse_values, data.shape[0])
        result.update(storage=encoding, dtype=str(data.dtype), stored_entries=int(data.shape[0]),
                      sampling={"method": "leading_stored_entries", "entry_range": [0, count],
                                "includes_implicit_zeros": False})
        if not _read_budget_ok(data, (count,)):
            return {**result, "status": "metadata_only", "unknown": "unsupported_dtype_or_chunk_decode_budget"}
        values = np.asarray(data[:count])
    finite = np.isfinite(values)
    finite_values = values[finite]
    result.update(status="sampled", sampled_value_count=int(values.size),
                  finite_sample_count=int(finite.sum()), nonfinite_sample_count=int((~finite).sum()),
                  sample_min=float(finite_values.min()) if finite_values.size else None,
                  sample_max=float(finite_values.max()) if finite_values.size else None,
                  negative_sample_count=int((finite_values < 0).sum()),
                  noninteger_sample_count=int((finite_values != np.floor(finite_values)).sum()))
    return result


def _inspect(handle, *, rows: int, columns: int, matrices: int, sparse_values: int) -> dict:
    try:
        import h5py
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("local H5AD profiling requires h5py and numpy") from exc
    with h5py.File(handle, "r") as file:
        if _encoding(file) not in {"", "anndata"}:
            raise ValueError("file does not declare AnnData encoding")
        x = _safe_child(file, "X", h5py)
        if x is None or not isinstance(x, (h5py.Dataset, h5py.Group)):
            raise ValueError("H5AD file has no supported X matrix")
        shape = _matrix_shape(x, h5py)
        alignment = {"obs": _axis_alignment(file, "obs", shape[0], h5py),
                     "var": _axis_alignment(file, "var", shape[1], h5py)}
        metadata = {name: _keys(file, name, h5py) for name in ("obs", "var", "layers", "obsm", "obsp", "uns")}
        samples = [_sample_matrix(x, "X", h5py, np, rows=rows, columns=columns, sparse_values=sparse_values)]
        raw = _safe_child(file, "raw", h5py)
        if raw is not None and isinstance(raw, h5py.Group) and len(samples) < matrices:
            raw_x = _safe_child(raw, "X", h5py)
            if raw_x is not None:
                samples.append(_sample_matrix(raw_x, "raw.X", h5py, np, rows=rows, columns=columns, sparse_values=sparse_values))
        layers = _safe_child(file, "layers", h5py)
        if isinstance(layers, h5py.Group):
            for key in itertools.islice(layers.keys(), max(0, matrices - len(samples))):
                layer = _safe_child(layers, key, h5py)
                samples.append(_sample_matrix(layer, f"layers/{key}", h5py, np,
                                              rows=rows, columns=columns, sparse_values=sparse_values))
        return {"dimensions": {"n_obs": shape[0], "n_vars": shape[1]},
                "metadata": metadata, "axis_alignment": alignment,
                "matrices": samples, "reader_version": h5py.__version__}


class DatasetService:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.ledger = Ledger(workspace)

    def register_local(self, path: str | Path, *, label: str | None = None,
                       project_id: str | None = None, previous_asset_id: str | None = None) -> dict:
        source = _local_path(path)
        return self._register_path(source, label=label, project_id=project_id,
                                   previous_asset_id=previous_asset_id)

    def register_upload(self, filename: str, content: bytes, *, label: str | None = None,
                        project_id: str | None = None, previous_asset_id: str | None = None) -> dict:
        """Archive at most 25 MiB supplied bytes; never overwrite an existing asset."""
        if not isinstance(filename, str) or not filename or Path(filename).name != filename or "\\" in filename:
            raise ValueError("upload filename must be a plain .h5ad filename")
        if Path(filename).suffix.lower() != ".h5ad":
            raise ValueError("upload must be .h5ad")
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_UPLOAD_BYTES:
            raise ValueError("upload must be nonempty bytes of at most 25 MiB")
        if previous_asset_id is not None and self.get_asset(previous_asset_id) is None:
            raise ValueError("previous dataset asset does not exist")
        import h5py
        try:
            with h5py.File(io.BytesIO(content), "r"):
                pass
        except (OSError, ValueError) as exc:
            raise ValueError("upload is not a readable HDF5 file") from exc
        archive = self.workspace.artifacts_dir / "datasets"
        if self.workspace.artifacts_dir.is_symlink() or archive.is_symlink():
            raise ValueError("dataset archive must not be a symlink")
        archive.mkdir(mode=0o700, exist_ok=True)
        source = archive / (new_id("dataset-upload") + ".h5ad")
        descriptor = os.open(source, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        source.chmod(0o400)
        return self._register_path(source, label=label or filename, project_id=project_id,
                                   previous_asset_id=previous_asset_id, storage="immutable_upload",
                                   content_sha256=hashlib.sha256(content).hexdigest(),
                                   upload_filename=filename)

    def _register_path(self, source: Path, *, label: str | None, project_id: str | None,
                       previous_asset_id: str | None, storage: str = "local_reference",
                       content_sha256: str | None = None, upload_filename: str | None = None) -> dict:
        if previous_asset_id is not None and self.get_asset(previous_asset_id) is None:
            raise ValueError("previous dataset asset does not exist")
        with _open_local(source) as (handle, signature):
            fingerprint = _fingerprint(handle, signature["size"])
            if content_sha256 is not None:
                # Uploads alone are explicitly small and fully hashed; local files never take this path.
                if signature["size"] > MAX_UPLOAD_BYTES:
                    raise ValueError("uploaded archive exceeds upload bound")
                if hashlib.sha256(handle.read(MAX_UPLOAD_BYTES + 1)).hexdigest() != content_sha256:
                    raise DatasetChangedError("uploaded archive does not match supplied bytes")
            # Validate only the bounded HDF5 signature, leaving matrix reads to profile().
            import h5py
            if not h5py.is_hdf5(source):
                raise ValueError("file is not HDF5; .h5ad suffix alone is insufficient")
        asset_id = new_id("dataset")
        asset = {"asset_id": asset_id, "artifact_id": asset_id, "namespace": self.workspace.namespace,
                 "path": str(source), "label": label or source.name, "project_id": project_id,
                 "previous_asset_id": previous_asset_id, "format": "h5ad", "storage": storage,
                 "upload_filename": upload_filename,
                 "registered_at": utcnow(), "stat_signature": signature, "bounded_fingerprint": fingerprint,
                 "content_sha256": content_sha256,
                 "full_content_hash_status": "verified_small_upload" if content_sha256 else "not_computed_bounded_registration",
                 "raw_data_modified": False, "outbound_allowed": False}
        with self.ledger.transaction() as tx:
            self.ledger.put_record("dataset_asset", asset_id, asset, conn=tx)
            self.ledger.append_event("dataset.registered", asset_id, {"storage": storage}, conn=tx)
        return asset

    def get_asset(self, asset_id: str) -> dict | None:
        return self.ledger.get_record("dataset_asset", asset_id)

    def list_assets(self) -> list[dict]:
        return self.ledger.list_records("dataset_asset")

    def get_profile(self, profile_id: str) -> dict | None:
        return self.ledger.get_record("dataset_profile", profile_id)

    def list_profiles(self, asset_id: str) -> list[dict]:
        return [p for p in self.ledger.list_records("dataset_profile") if p["asset_id"] == asset_id]

    def profile(self, asset_id: str, *, max_rows: int = 32, max_columns: int = 128,
                max_matrices: int = 8, max_sparse_values: int = 4096) -> dict:
        bounds = {"max_rows": (max_rows, 128), "max_columns": (max_columns, 512),
                  "max_matrices": (max_matrices, 16), "max_sparse_values": (max_sparse_values, 65536)}
        if any(type(value) is not int or not 1 <= value <= ceiling for value, ceiling in bounds.values()):
            raise ValueError("sample limits must be bounded positive integers")
        asset = self.get_asset(asset_id)
        if asset is None:
            raise ValueError("dataset asset does not exist")
        source = _local_path(asset["path"])
        with _open_local(source) as (handle, signature):
            if signature != asset["stat_signature"]:
                raise DatasetChangedError("registered dataset changed; register a new asset version")
            fingerprint = _fingerprint(handle, signature["size"])
            if fingerprint != asset["bounded_fingerprint"]:
                raise DatasetChangedError("registered dataset bounded fingerprint changed")
            inspected = _inspect(handle, rows=max_rows, columns=max_columns,
                                 matrices=max_matrices, sparse_values=max_sparse_values)
            if _fingerprint(handle, signature["size"]) != fingerprint:
                raise DatasetChangedError("dataset changed during profiling")
        unknowns = ["whole_dataset_value_distribution_not_scanned",
                    "raw_counts_and_transformation_provenance_not_verified", "modality_and_species_not_inferred",
                    "biological_replicates_and_cell_pairing_not_verified", "obs_and_var_values_not_read",
                    "sparse_indices_and_pointer_values_not_fully_validated",
                    "bounded_fingerprint_is_not_whole_file_integrity_proof"]
        if asset["content_sha256"] is None:
            unknowns.append("full_content_sha256_not_computed")
        if any(item["truncated"] for item in inspected["metadata"].values()):
            unknowns.append("metadata_key_list_truncated")
        sampled_layers = sum(item["matrix_id"].startswith("layers/") for item in inspected["matrices"])
        if (inspected["metadata"]["layers"].get("count") or 0) > sampled_layers:
            unknowns.append("some_layers_not_sampled")
        profile = DatasetProfile(
            artifact_id=asset_id, content_sha256=asset["content_sha256"], dimensions=inspected["dimensions"],
            measurements={"matrices": inspected["matrices"], "metadata": inspected["metadata"],
                          "axis_alignment": inspected["axis_alignment"],
                          "selected_count_source": None, "local_only": True},
            sampling={"scope": "partial_deterministic_prefixes", "full_scan": False,
                      **{key: value for key, (value, _) in bounds.items()},
                      "max_decoded_bytes_per_matrix": MAX_DECODED_BYTES,
                      "representative_random_sample": False,
                      "statistics_apply_to": "only_explicitly_reported_ranges"},
            unknowns=unknowns, raw_data_modified=False)
        profile_id = new_id("dataset-profile")
        record = {"profile_id": profile_id, "asset_id": asset_id, "created_at": utcnow(),
                  "profile": profile.model_dump(), "stat_signature": signature,
                  "bounded_fingerprint": fingerprint, "reader": {"name": "h5py", "version": inspected["reader_version"]},
                  "status": "bounded_profile", "validity": "matched_registration_at_profile_time"}
        with self.ledger.transaction() as tx:
            self.ledger.put_record("dataset_profile", profile_id, record, conn=tx)
            self.ledger.append_event("dataset.profiled", asset_id, {"profile_id": profile_id, "full_scan": False}, conn=tx)
        return record
