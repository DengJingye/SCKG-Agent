from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from typing import Sequence

import numpy as np

from core.settings import PROJECT_ROOT
from execution.model_pack_manager import ModelPackManager


class LocalEmbeddingWorker:
    """Persistent, fixed-entrypoint embedding worker from the local model pack."""

    def __init__(self, manager: ModelPackManager | None = None) -> None:
        self.manager = manager or ModelPackManager()
        probe = self.manager.probe()
        if not probe.environment_ready or not probe.snapshot_ready or not probe.snapshot_digest:
            raise RuntimeError("local dense model pack is not installed")
        self.revision = probe.revision
        self.snapshot_digest = probe.snapshot_digest
        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        env["HF_HOME"] = str(self.manager.pack_root / "cache")
        self._stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        self._process = subprocess.Popen(
            [
                str(self.manager.python_executable),
                str(PROJECT_ROOT / "execution/model_workers/bge_m3_worker.py"),
                "--model-path",
                str(self.manager.snapshot_root),
            ],
            cwd=PROJECT_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            bufsize=1,
        )
        self._lock = threading.Lock()

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 1024), dtype=np.float32)
        if self._process.poll() is not None:
            raise RuntimeError("local embedding worker exited unexpectedly")
        request = json.dumps({"texts": list(texts)}, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            assert self._process.stdin is not None
            assert self._process.stdout is not None
            self._process.stdin.write(request + "\n")
            self._process.stdin.flush()
            line = self._process.stdout.readline()
        if not line:
            self._stderr.flush()
            self._stderr.seek(0)
            stderr = self._stderr.read()[-800:]
            raise RuntimeError(f"local embedding worker returned no response: {stderr}")
        response = json.loads(line)
        if response.get("error"):
            raise RuntimeError(
                f"local embedding worker error: {response['error']}:{response.get('message', '')}"
            )
        matrix = np.asarray(response.get("vectors"), dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != len(texts):
            raise RuntimeError("local embedding worker returned invalid shape")
        return matrix

    def close(self) -> None:
        if self._process.poll() is None:
            if self._process.stdin is not None:
                self._process.stdin.close()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
        self._stderr.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
