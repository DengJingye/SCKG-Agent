from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_scanpy_core_current_status_is_reconciled():
    spec = (ROOT / "docs" / "DEV_SPEC_2.0.md").read_text(encoding="utf-8")
    status = (ROOT / "docs" / "status" / "PROJECT_STATUS_2.0.md").read_text(
        encoding="utf-8"
    )

    current_block = spec.split(
        "### 2026-08-24 Scanpy Core Workflow / Method Graph v0 实现状态", 1
    )[1].split("---", 1)[0]
    assert "implementation_not_started" not in current_block
    assert "实现未开始的工作线" not in spec
    assert "implementation_status=implemented" in spec
    assert "engineering_smoke_status=passed" in spec
    assert "scientific_validation_status=not_evaluated" in spec
    assert "user_executable=false" in spec
    assert "enabled_for_execution=false" in spec
    assert "主规约版本：2.10.2-dev" in status
    assert "`scientifically_validated=false`" in status
    assert "`user_executable=false`" in status
    assert "全局 `ExecutionPolicy=disabled`" in status
