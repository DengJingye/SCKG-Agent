"""Bounded, offline dependency probe; never installs or executes an analysis task.

Run with the target prefix's Python. The parent qualifies prefix isolation and
metadata before starting an isolated child with a temporary workspace. The
child imports the real worker's import prelude, not its execution body.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import site
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def _inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _requirements(path: Path, seen=None) -> dict[str, str]:
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen or not _inside(path, ROOT):
        raise ValueError("requirements_cycle_or_foreign_path")
    seen.add(path)
    result = {}
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            additions = _requirements(path.parent / line[3:].strip(), seen)
        else:
            name, separator, version = line.partition("==")
            if not separator or not name or not version or any(c.isspace() for c in line):
                raise ValueError("only_exact_product_pins_supported")
            additions = {name.lower().replace("_", "-"): version}
        if result.keys() & additions.keys():
            raise ValueError("duplicate_product_pin")
        result.update(additions)
    return result


def _preflight(prefix: Path, profile: str, contract: dict) -> dict:
    failures, versions = [], {}
    if Path(sys.prefix).resolve() != prefix.resolve():
        failures.append("running_python_is_not_expected_prefix")
    cfg = prefix / "pyvenv.cfg"
    kind = "venv" if cfg.is_file() else "conda" if (prefix / "conda-meta").is_dir() else "unknown"
    if kind == "venv":
        values = {key.strip(): value.strip() for line in cfg.read_text().lower().splitlines()
                  if "=" in line for key, value in [line.split("=", 1)]}
        if values.get("include-system-site-packages", "").strip() != "false":
            failures.append("venv_inherits_or_does_not_declare_system_site_packages")
    elif kind == "unknown":
        failures.append("prefix_is_neither_independent_conda_nor_declared_venv")
    if site.ENABLE_USER_SITE:
        failures.append("user_site_enabled_run_with_python_isolated_mode")
    foreign = [s for s in sys.path if s and ("site-packages" in Path(s).parts or "dist-packages" in Path(s).parts)
               and not _inside(Path(s), prefix)]
    if foreign:
        failures.append("foreign_site_packages_on_path")
    wanted = _requirements(ROOT / contract["profiles"][profile]["requirements"])
    distributions = {}
    for dist in importlib.metadata.distributions():
        name = (dist.metadata.get("Name") or "").lower().replace("_", "-")
        distributions.setdefault(name, []).append(dist)
    for name, expected in wanted.items():
        found = distributions.get(name, [])
        versions[name] = {"expected": expected, "found": [d.version for d in found]}
        if len(found) != 1:
            failures.append("missing_or_duplicate_distribution:" + name)
        elif found[0].version != expected:
            failures.append("distribution_version_mismatch:" + name)
        elif not _inside(Path(found[0].locate_file("")), prefix):
            failures.append("distribution_outside_prefix:" + name)
    return {"prefix": str(prefix.resolve()), "prefix_kind": kind,
            "python": sys.version, "executable": sys.executable,
            "platform": platform.system(), "machine": platform.machine(),
            "user_site_enabled": site.ENABLE_USER_SITE, "foreign_site_packages": foreign,
            "versions": versions, "failures": failures}


def _worker_imports() -> list[dict]:
    source = ROOT / "sckg_workbench/analysis.py"
    tree = ast.parse(source.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AnalysisService")
    function = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_execute")
    records = []
    for n in function.body:
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            continue
        if isinstance(n, ast.Import):
            names = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module:
            name = n.module if n.level == 0 else "sckg_workbench." + n.module
            names = [name]
        else:
            break
        for name in names:
            imported = importlib.import_module(name)
            if isinstance(n, ast.ImportFrom):
                for alias in n.names:
                    if not hasattr(imported, alias.name):
                        importlib.import_module(name + "." + alias.name)
            records.append({"module": name, "source_line": n.lineno,
                            "module_file": getattr(imported, "__file__", None)})
    required = {"anndata", "scipy", "execution.local_user_service", "execution.preview_execution_service"}
    if not required.issubset({r["module"] for r in records}):
        raise ValueError("worker_import_prelude_changed_requires_review")
    return records


def _probe(profile: str, contract: dict, scratch: Path, prefix: Path) -> dict:
    def offline(event, args):
        if event in {"socket.connect", "socket.connect_ex", "subprocess.Popen", "os.system"}:
            raise PermissionError("dependency_probe_forbids_network_and_external_execution")
    sys.addaudithook(offline)
    os.environ.update(SCKG_HOME=str(scratch / "legacy-home"),
                      SCKG_WORKBENCH_HOME=str(scratch / "workspace"),
                      SCKG_ENV_FILE=str(scratch / "no-credential-file"),
                      SCKG_PRIVACY_MODE="strict_offline", SCKG_EXTERNAL_NETWORK_ALLOWED="false",
                      SCKG_OFFLINE_LLM="true")
    sys.path.insert(0, str(ROOT))
    pins = _requirements(ROOT / contract["profiles"][profile]["requirements"])
    modules = {}
    for name in pins:
        imported = importlib.import_module(contract["import_names"].get(name, name.replace("-", "_")))
        path = getattr(imported, "__file__", None)
        if not path or not _inside(Path(path), prefix):
            raise ValueError("import_origin_outside_prefix:" + name)
        modules[name] = path
    from sckg_workbench.storage import Workspace
    from sckg_workbench.datasets import DatasetService
    from sckg_workbench.contracts import DatasetProfile
    from sckg_workbench.analysis import AnalysisService
    from sckg_workbench.code_runtime import CodeRuntime
    # Same minimal HDF5 pattern as test_workbench_datasets.dense; no test dependency.
    import h5py
    import numpy as np
    data = scratch / "synthetic.h5ad"
    with h5py.File(data, "w") as handle:
        handle.attrs["encoding-type"] = "anndata"
        handle.create_dataset("X", data=np.arange(6, dtype=np.float32).reshape(2, 3))
        for group in ("obs", "var", "layers", "obsm", "obsp", "uns"):
            handle.create_group(group)
    before = hashlib.sha256(data.read_bytes()).hexdigest()
    workspace = Workspace(scratch / "workspace")
    service = AnalysisService(workspace)
    dataset = DatasetService(workspace)
    asset = dataset.register_local(data, label="synthetic dependency probe only")
    result = dataset.profile(asset["asset_id"], max_rows=2, max_columns=3)
    typed = DatasetProfile.model_validate(result["profile"])
    if typed.dimensions != {"n_obs": 2, "n_vars": 3} or hashlib.sha256(data.read_bytes()).hexdigest() != before:
        raise ValueError("bounded_dataset_probe_failed")
    worker = _worker_imports() if profile == "analysis" else []
    typed_contract = None
    if profile == "analysis":
        from core.tool_contract_registry import ToolContractRegistry
        tool = ToolContractRegistry().load("Scrublet", "0.2.3")
        typed_contract = {"contract_id": tool.contract_id, "tool_version": tool.tool_version}
    forbidden = {"torch", "tensorflow", "scanpy", "scrublet", "celltypist", "openai", "langgraph", "neo4j"}
    loaded = sorted(forbidden & {name.split(".")[0] for name in sys.modules})
    if loaded:
        raise ValueError("unexpected_fit_or_legacy_framework_import")
    return {"product_imports": modules, "analysis_service_constructed": isinstance(service, AnalysisService),
            "code_runtime_imported": CodeRuntime.__name__, "synthetic_profile_dimensions": typed.dimensions,
            "synthetic_input_unchanged": True, "worker_import_prelude": worker,
            "analysis_import_probe_interpreter": sys.executable if profile == "analysis" else None,
            "worker_launcher_source": "sckg_workbench/analysis.py:_execute_supervised uses sys.executable",
            "worker_task_executed": False, "typed_scientific_contract": typed_contract,
            "unexpected_frameworks_loaded": loaded, "provider_calls": 0, "scientific_fits": 0,
            "qualification_scope": "host imports/service/data-profile only; separate fitting runtime not qualified"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--profile", choices=("base", "analysis"), default="analysis")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--probe", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    contract = json.loads((ROOT / "workbench-dependencies.json").read_text())
    if args.probe:
        try:
            value = _probe(args.profile, contract, args.probe, args.prefix)
            print(json.dumps({"status": "passed", **value}, ensure_ascii=False))
            return 0
        except Exception as exc:
            print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
                              "error": str(exc)[:400]}))
            return 2
    before = _preflight(args.prefix, args.profile, contract)
    result = {"schema": "workbench-dependency-qualification-v1", "profile": args.profile,
              "preflight": before, "probe": None, "pip_check": None,
              "probe_process": None,
              "status": "failed", "clean_install_claim": False,
              "provider_calls": 0, "scientific_fits": 0}
    if not before["failures"]:
        with tempfile.TemporaryDirectory(prefix="sckg-dependency-probe-") as directory:
            env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR"}}
            for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
                env[key] = "1"
            command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--prefix", str(args.prefix),
                       "--profile", args.profile, "--probe", directory]
            try:
                child = subprocess.run(command, cwd=directory, env=env, capture_output=True, text=True, timeout=60)
                result["probe_process"] = {"returncode": child.returncode, "stderr": child.stderr[:4096],
                                           "stdout_sha256": hashlib.sha256(child.stdout.encode()).hexdigest()}
                result["probe"] = json.loads(child.stdout)
                result["probe"]["returncode"] = child.returncode
                check = subprocess.run([sys.executable, "-I", "-m", "pip", "check"],
                                       cwd=directory, env=env, capture_output=True, text=True, timeout=30)
                result["pip_check"] = {"returncode": check.returncode, "stdout": check.stdout[:4096], "stderr": check.stderr[:4096]}
                if child.returncode == 0 and result["probe"]["status"] == "passed" and check.returncode == 0:
                    result["status"] = "passed"
            except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                result["probe"] = {"status": "failed", "error_type": type(exc).__name__}
    # A clean-install claim additionally needs the root's fresh-install/wheel receipts.
    if args.report:
        with args.report.open("x") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
