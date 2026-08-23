from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description="Fixed offline BGE-M3 embedding worker.")
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if not args.model_path.is_dir() or not (args.model_path / "config.json").is_file():
        raise SystemExit("model snapshot is incomplete")

    from sentence_transformers import SentenceTransformer
    import torch

    model = SentenceTransformer(str(args.model_path), local_files_only=True)
    if args.smoke:
        vector = model.encode(["single-cell RNA sequencing"], normalize_embeddings=True)
        array = np.asarray(vector)
        print(json.dumps({"shape": list(array.shape), "finite": bool(np.isfinite(array).all())}))
        return 0 if array.shape == (1, 1024) and np.isfinite(array).all() else 1

    for line in sys.stdin:
        try:
            request = json.loads(line)
            texts = request.get("texts")
            if not isinstance(texts, list) or not texts or not all(
                isinstance(text, str) for text in texts
            ):
                raise ValueError("texts must be a non-empty string list")
            values = model.encode(
                texts,
                batch_size=4,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            response = {"vectors": np.asarray(values, dtype=np.float32).tolist()}
            if torch.backends.mps.is_available():
                torch.mps.synchronize()
                torch.mps.empty_cache()
        except Exception as exc:
            response = {"error": type(exc).__name__, "message": str(exc)[:500]}
        print(json.dumps(response, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
