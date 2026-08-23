from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.hybrid_retrieval import HybridRetrievalService, LocalBgeM3Encoder


def main() -> int:
    service = HybridRetrievalService()
    encoder = LocalBgeM3Encoder()
    try:
        metadata = service.build_dense_index(encoder)
    finally:
        worker = getattr(encoder, "_worker", None)
        if worker is not None:
            worker.close()
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
