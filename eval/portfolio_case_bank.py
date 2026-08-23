from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.portfolio_models import PortfolioCaseSpec


CASE_BANK_PATH = Path(__file__).resolve().parent / "portfolio" / "gold_cases.json"


def load_portfolio_cases(path: Path = CASE_BANK_PATH) -> list[PortfolioCaseSpec]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = [PortfolioCaseSpec.model_validate(row) for row in rows]
    if len(cases) != 48 or len({case.case_id for case in cases}) != 48:
        raise ValueError("portfolio gold bank must contain exactly 48 unique cases")
    categories = {category: 0 for category in (
        "doublet_detection", "batch_integration", "safety_blocking", "retrieval_boundary"
    )}
    for case in cases:
        categories[case.category] += 1
    if set(categories.values()) != {12}:
        raise ValueError(f"portfolio categories must contain 12 cases each: {categories}")
    if sum(case.representative for case in cases) != 16:
        raise ValueError("portfolio gold bank must mark exactly 16 representative cases")
    return cases


def case_bank_sha256(path: Path = CASE_BANK_PATH) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
