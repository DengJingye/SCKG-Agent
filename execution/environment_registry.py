from __future__ import annotations

from pathlib import Path

from core.execution_models import EnvironmentRecord
from core.settings import PROJECT_ROOT


DEFAULT_ENVIRONMENT_ROOT = PROJECT_ROOT / "execution" / "environments"


class EnvironmentRegistry:
    def __init__(self, root: Path = DEFAULT_ENVIRONMENT_ROOT) -> None:
        self.root = Path(root)

    def contains(self, environment_id: str) -> bool:
        return (self.root / f"{environment_id}.json").is_file()

    def get(self, environment_id: str) -> EnvironmentRecord:
        path = self.root / f"{environment_id}.json"
        if not path.is_file():
            raise KeyError(f"environment is not registered: {environment_id}")
        record = EnvironmentRecord.model_validate_json(path.read_text(encoding="utf-8"))
        if record.environment_id != environment_id:
            raise ValueError(
                f"environment id mismatch: expected {environment_id}, got {record.environment_id}"
            )
        return record

    def load_all(self) -> list[EnvironmentRecord]:
        if not self.root.exists():
            return []
        return [
            EnvironmentRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.root.glob("*.json"))
        ]

