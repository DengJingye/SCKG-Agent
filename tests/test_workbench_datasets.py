from __future__ import annotations

import hashlib
from pathlib import Path

import h5py
import numpy as np
import pytest

from sckg_workbench.contracts import DatasetProfile
from sckg_workbench.datasets import DatasetChangedError, DatasetService
from sckg_workbench.storage import Workspace


@pytest.fixture
def service(tmp_path):
    return DatasetService(Workspace(tmp_path / "workspace"))


def dense(path, matrix=None, *, extra=False):
    with h5py.File(path, "w") as f:
        f.attrs["encoding-type"] = "anndata"
        f.create_dataset("X", data=np.arange(120, dtype=np.float32).reshape(12, 10) if matrix is None else matrix)
        for name in ("obs", "var", "layers", "obsm", "obsp", "uns"):
            f.create_group(name)
        f["obs"].create_dataset("donor", data=np.array([b"not-read"] * 12))
        if extra:
            f["layers"].create_dataset("counts", data=np.ones((12, 10)))
            f.create_group("raw").create_dataset("X", data=np.ones((12, 15)))
    return path


def sparse_file(path, encoding="csr_matrix"):
    with h5py.File(path, "w") as f:
        f.attrs["encoding-type"] = "anndata"
        x = f.create_group("X")
        x.attrs["encoding-type"] = encoding
        x.attrs["shape"] = [1000000, 2000000]
        x.create_dataset("data", data=np.arange(100, dtype=float))
        x.create_dataset("indices", data=np.arange(100))
        pointer_length = (1000000 if encoding == "csr_matrix" else 2000000) + 1
        x.create_dataset("indptr", shape=(pointer_length,), dtype="int64", chunks=(1024,))
    return path


def test_local_registration_profile_roundtrip_preserves_raw_file(service, tmp_path):
    path = dense(tmp_path / "data.h5ad", extra=True)
    original = path.read_bytes()
    asset = service.register_local(path, label="test", project_id="project-a")
    record = service.profile(asset["asset_id"], max_rows=2, max_columns=3)
    assert path.read_bytes() == original
    assert asset["content_sha256"] is None
    assert asset["outbound_allowed"] is False
    profile = DatasetProfile.model_validate(record["profile"])
    assert profile.content_sha256 is None
    assert profile.dimensions == {"n_obs": 12, "n_vars": 10}
    assert profile.raw_data_modified is False
    assert profile.measurements["selected_count_source"] is None
    assert profile.measurements["matrices"][0]["sampled_value_count"] == 6
    assert profile.measurements["matrices"][0]["sample_max"] == 12.0
    assert profile.measurements["metadata"]["obs"]["keys"] == ["donor"]
    assert "not-read" not in str(record)
    assert service.get_asset(asset["asset_id"]) == asset
    assert service.get_profile(record["profile_id"]) == record
    assert service.list_profiles(asset["asset_id"]) == [record]
    assert service.list_assets() == [asset]
    assert profile.sampling["representative_random_sample"] is False


@pytest.mark.parametrize("encoding", ["csr_matrix", "csc_matrix"])
def test_sparse_samples_only_stored_prefix_without_dense_conversion(service, tmp_path, encoding):
    path = sparse_file(tmp_path / "sparse.h5ad", encoding)
    asset = service.register_local(path)
    result = service.profile(asset["asset_id"], max_sparse_values=7)["profile"]
    sample = result["measurements"]["matrices"][0]
    assert sample["shape"] == [1000000, 2000000]
    assert sample["sampled_value_count"] == 7
    assert sample["sampling"]["includes_implicit_zeros"] is False
    assert sample["representation_state"] == "unknown"
    assert result["dimensions"]["n_vars"] == 2000000


def test_sampling_does_not_infer_whole_matrix_or_raw_counts(service, tmp_path):
    values = np.ones((12, 10))
    values[-1, -1] = -100.5
    path = dense(tmp_path / "data.h5ad", values)
    record = service.profile(service.register_local(path)["asset_id"], max_rows=2, max_columns=2)
    p = record["profile"]
    sample = p["measurements"]["matrices"][0]
    assert sample["negative_sample_count"] == 0
    assert sample["noninteger_sample_count"] == 0
    assert sample["representation_state"] == "unknown"
    assert "whole_dataset_value_distribution_not_scanned" in p["unknowns"]
    assert "raw_counts_and_transformation_provenance_not_verified" in p["unknowns"]


def test_nonfinite_samples_are_json_safe(service, tmp_path):
    path = dense(tmp_path / "data.h5ad", np.array([[np.nan, np.inf, -np.inf, -1.5]]))
    sample = service.profile(service.register_local(path)["asset_id"])["profile"]["measurements"]["matrices"][0]
    assert sample["nonfinite_sample_count"] == 3
    assert sample["sample_min"] == -1.5
    assert sample["noninteger_sample_count"] == 1


def test_file_changed_since_registration_is_rejected(service, tmp_path):
    path = dense(tmp_path / "data.h5ad")
    asset = service.register_local(path)
    with h5py.File(path, "r+") as f:
        f["X"][0, 0] = 999
    with pytest.raises(DatasetChangedError, match="changed"):
        service.profile(asset["asset_id"])
    assert service.list_profiles(asset["asset_id"]) == []


def test_replaced_inode_is_rejected_even_same_content(service, tmp_path):
    path = dense(tmp_path / "data.h5ad")
    asset = service.register_local(path)
    replacement = tmp_path / "replacement.h5ad"
    replacement.write_bytes(path.read_bytes())
    replacement.replace(path)
    with pytest.raises(DatasetChangedError):
        service.profile(asset["asset_id"])


def test_concurrent_mutation_does_not_publish_profile(service, tmp_path, monkeypatch):
    import sckg_workbench.datasets as module
    path = dense(tmp_path / "data.h5ad")
    asset = service.register_local(path)
    inspect = module._inspect

    def mutate_after_read(*args, **kwargs):
        result = inspect(*args, **kwargs)
        with path.open("ab") as f:
            f.write(b"changed")
        return result

    monkeypatch.setattr(module, "_inspect", mutate_after_read)
    with pytest.raises(DatasetChangedError):
        service.profile(asset["asset_id"])
    assert service.list_profiles(asset["asset_id"]) == []


def test_matrices_and_metadata_enumeration_are_bounded(service, tmp_path):
    path = dense(tmp_path / "data.h5ad", extra=True)
    with h5py.File(path, "r+") as f:
        for i in range(75):
            f["layers"].create_dataset(f"layer{i:03}", data=np.zeros((12, 10)))
    p = service.profile(service.register_local(path)["asset_id"], max_matrices=2)["profile"]
    assert len(p["measurements"]["matrices"]) == 2
    assert len(p["measurements"]["metadata"]["layers"]["keys"]) == 64
    assert "metadata_key_list_truncated" in p["unknowns"]
    assert "some_layers_not_sampled" in p["unknowns"]


def test_huge_compressed_chunk_is_metadata_only(service, tmp_path):
    path = tmp_path / "chunked.h5ad"
    with h5py.File(path, "w") as f:
        f.create_dataset("X", shape=(4096, 4096), dtype="float64", chunks=(4096, 4096), compression="gzip")
    sample = service.profile(service.register_local(path)["asset_id"])["profile"]["measurements"]["matrices"][0]
    assert sample["status"] == "metadata_only"
    assert sample["unknown"] == "unsupported_dtype_or_chunk_decode_budget"
    assert "sampled_value_count" not in sample


def test_external_hdf5_link_is_not_followed(service, tmp_path):
    target = dense(tmp_path / "target.h5ad")
    path = tmp_path / "external.h5ad"
    with h5py.File(path, "w") as f:
        f["X"] = h5py.ExternalLink(str(target), "/X")
    asset = service.register_local(path)
    with pytest.raises(ValueError, match="external and soft links"):
        service.profile(asset["asset_id"])


def test_external_hdf5_dataset_storage_is_not_read(service, tmp_path):
    path = tmp_path / "externaldata.h5ad"
    with h5py.File(path, "w") as f:
        f.create_dataset("X", shape=(1, 1), dtype="float64", external=[("unavailable.raw", 0, 8)])
    with pytest.raises(ValueError, match="externally stored"):
        service.profile(service.register_local(path)["asset_id"])


def test_invalid_format_and_symlink_registration_rejected(service, tmp_path):
    fake = tmp_path / "fake.h5ad"
    fake.write_text("not hdf5")
    with pytest.raises(ValueError, match="not HDF5"):
        service.register_local(fake)
    target = dense(tmp_path / "target.h5ad")
    link = tmp_path / "link.h5ad"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        service.register_local(link)


def test_invalid_sparse_components_rejected(service, tmp_path):
    path = sparse_file(tmp_path / "bad.h5ad")
    with h5py.File(path, "r+") as f:
        del f["X/indices"]
        f["X"].create_dataset("indices", data=[1, 2])
    with pytest.raises(ValueError, match="dimensions are inconsistent"):
        service.profile(service.register_local(path)["asset_id"])


@pytest.mark.parametrize("kwargs", [{"max_rows": 0}, {"max_columns": 513}, {"max_matrices": 17}, {"max_sparse_values": 65537}, {"max_rows": True}])
def test_unbounded_or_invalid_limits_rejected(service, kwargs):
    with pytest.raises(ValueError, match="sample limits"):
        service.profile("unused", **kwargs)


def test_fingerprint_read_scope_and_version_links(service, tmp_path):
    path = dense(tmp_path / "large.h5ad", np.zeros((1000, 1000)))
    asset = service.register_local(path)
    fp = asset["bounded_fingerprint"]
    assert sum(item["bytes"] for item in fp["ranges"]) <= 3 * 65536
    assert fp["full_content_hash"] is False
    assert fp["fingerprint_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest()
    newer = service.register_local(path, previous_asset_id=asset["asset_id"])
    assert newer["previous_asset_id"] == asset["asset_id"]
    assert newer["asset_id"] != asset["asset_id"]
    with pytest.raises(ValueError, match="previous"):
        service.register_local(path, previous_asset_id="missing")


def test_empty_matrix_and_no_profiles_do_not_claim_successful_analysis(service, tmp_path):
    path = dense(tmp_path / "empty.h5ad", np.zeros((0, 5)))
    asset = service.register_local(path)
    p = service.profile(asset["asset_id"])
    assert p["status"] == "bounded_profile"
    assert p["profile"]["dimensions"]["n_obs"] == 0
    assert p["profile"]["measurements"]["matrices"][0]["sample_min"] is None
    assert p["profile"]["measurements"]["selected_count_source"] is None


def test_real_anndata_file_profiles_without_materializing_anndata(service, tmp_path):
    ad = pytest.importorskip("anndata")
    scipy = pytest.importorskip("scipy.sparse")
    a = ad.AnnData(scipy.csr_matrix(np.array([[0, 2, 1], [4, 0, 0]], dtype=np.float32)))
    a.obs["donor"] = ["donor-a", "donor-b"]
    a.obsm["X_pca"] = np.ones((2, 2))
    a.layers["counts"] = a.X.copy()
    a.raw = a
    path = tmp_path / "real.h5ad"
    a.write_h5ad(path)
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    p = service.profile(service.register_local(path)["asset_id"])["profile"]
    assert p["dimensions"] == {"n_obs": 2, "n_vars": 3}
    assert [m["matrix_id"] for m in p["measurements"]["matrices"]] == ["X", "raw.X", "layers/counts"]
    assert "X_pca" in p["measurements"]["metadata"]["obsm"]["keys"]
    assert p["measurements"]["matrices"][0]["sampled_value_count"] == 3
    assert p["measurements"]["selected_count_source"] is None
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original


def test_actual_hdf5_reads_are_bounded_and_do_not_read_obs_values(service, tmp_path, monkeypatch):
    path = dense(tmp_path / "bounded.h5ad", extra=True)
    original = h5py.Dataset.__getitem__
    calls = []

    def track(dataset, selector, *args, **kwargs):
        calls.append((dataset.name, selector))
        return original(dataset, selector, *args, **kwargs)

    monkeypatch.setattr(h5py.Dataset, "__getitem__", track)
    service.profile(service.register_local(path)["asset_id"], max_rows=2, max_columns=3)
    assert [name for name, _ in calls] == ["/X", "/raw/X", "/layers/counts"]
    assert all(selector == (slice(None, 2), slice(None, 3)) for _, selector in calls)


def test_metadata_axis_length_mismatch_rejected_without_reading_labels(service, tmp_path):
    path = dense(tmp_path / "bad_axis.h5ad")
    with h5py.File(path, "r+") as f:
        f["obs"].attrs["_index"] = "_index"
        f["obs"].create_dataset("_index", data=np.arange(3))
    asset = service.register_local(path)
    with pytest.raises(ValueError, match="obs index length"):
        service.profile(asset["asset_id"])
    assert service.list_profiles(asset["asset_id"]) == []


def test_small_upload_is_archived_immutably_with_full_hash(service, tmp_path):
    path = dense(tmp_path / "upload_source.h5ad")
    content = path.read_bytes()
    expected = hashlib.sha256(content).hexdigest()
    a = service.register_upload("sample.h5ad", content, project_id="p")
    b = service.register_upload("sample.h5ad", content, previous_asset_id=a["asset_id"])
    assert a["path"] != b["path"]
    assert a["storage"] == "immutable_upload"
    assert a["content_sha256"] == expected
    assert a["full_content_hash_status"] == "verified_small_upload"
    assert a["project_id"] == "p"
    assert a["upload_filename"] == "sample.h5ad"
    assert Path(a["path"]).read_bytes() == content
    assert Path(a["path"]).stat().st_mode & 0o222 == 0
    assert path.read_bytes() == content
    p = service.profile(a["asset_id"])["profile"]
    assert p["content_sha256"] == expected
    assert "full_content_sha256_not_computed" not in p["unknowns"]
    assert p["sampling"]["full_scan"] is False


@pytest.mark.parametrize("name,content", [("../data.h5ad", b"x"), ("dir\\data.h5ad", b"x"), ("data.txt", b"x"), ("data.h5ad", b""), ("data.h5ad", b"invalid hdf5")])
def test_invalid_uploads_rejected_before_archiving(service, name, content):
    with pytest.raises(ValueError):
        service.register_upload(name, content)
    assert service.list_assets() == []
    assert not (service.workspace.artifacts_dir / "datasets").exists()


def test_oversized_upload_rejected_before_hdf5_parse(service, monkeypatch):
    import sckg_workbench.datasets as module
    monkeypatch.setattr(module, "MAX_UPLOAD_BYTES", 32)
    with pytest.raises(ValueError, match="25 MiB"):
        service.register_upload("data.h5ad", b"x" * 33)
    assert service.list_assets() == []


def test_upload_archive_symlink_rejected(service, tmp_path):
    path = dense(tmp_path / "data.h5ad")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (service.workspace.artifacts_dir / "datasets").symlink_to(elsewhere)
    with pytest.raises(ValueError, match="symlink"):
        service.register_upload("data.h5ad", path.read_bytes())
    assert list(elsewhere.iterdir()) == []
