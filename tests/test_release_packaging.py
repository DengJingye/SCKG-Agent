from pathlib import Path
import subprocess
import zipfile

from scripts.build_local_release import (
    build_release,
    collect_release_files,
    load_release_manifest,
    release_bytes,
    validate_release,
)


def test_release_is_small_and_excludes_private_or_large_runtime_assets():
    manifest = load_release_manifest()
    files = collect_release_files(manifest)
    names = {item.as_posix() for item in files}
    assert not any(name.startswith(".sckg_exec/") for name in names)
    assert not any(name.startswith("data/evidence_sources/") for name in names)
    assert "data/scKG_embeddings_backup.jsonl" not in names
    assert not any(Path(name).suffix in {".h5ad", ".pdf"} for name in names)
    report = validate_release(files, manifest)
    assert report["issues"] == []
    assert report["total_size_bytes"] < 500 * 1024**2
    assert all(b"/Users/" not in release_bytes(item) for item in files)


def test_release_contains_rebuildable_control_plane_and_executable_launcher(tmp_path):
    output = tmp_path / "sckg-mac-beta.zip"
    report = build_release(output)
    assert report["issues"] == []
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "release/control-plane-manifest.json" in names
        assert "release/locks/control-plane-osx-arm64.conda-explicit.txt" in names
        assert "release/locks/control-plane-osx-arm64.requirements.lock" in names
        launcher = archive.getinfo("release/bootstrap/launch_sckg.command")
        assert (launcher.external_attr >> 16) & 0o111


def test_bootstrap_requires_explicit_reviewed_install_confirmation(tmp_path):
    script = Path("release/bootstrap/install_sckg.command").resolve()
    completed = subprocess.run(
        [str(script)],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "--accept-reviewed-install" in completed.stdout
    assert not (tmp_path / ".sckg").exists()
