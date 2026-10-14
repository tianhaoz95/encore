"""Client for the encore GPU worker (encore/workers/server.py), which runs on
the DGX Spark (or the Mac) and wraps TTS / talking-head / i2v model repos."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import httpx


class WorkerError(RuntimeError):
    pass


class WorkerClient:
    def __init__(self, url: str, timeout: float = 3600):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.http = httpx.Client(timeout=httpx.Timeout(60.0, read=300.0))

    def health(self) -> dict:
        return self.http.get(f"{self.url}/health", timeout=5).json()

    def run(self, task: str, engine: str, params: dict, files: dict[str, Path], out: Path,
            poll: float = 2.0) -> Path:
        """Submit a job, wait for it, download the result to `out`."""
        handles = {k: (Path(v).name, open(v, "rb")) for k, v in files.items() if v}
        try:
            r = self.http.post(f"{self.url}/jobs/{task}",
                               data={"engine": engine, "params": json.dumps(params)}, files=handles)
        finally:
            for _, fh in handles.values():
                fh.close()
        if r.status_code >= 400:
            raise WorkerError(f"worker rejected {task}: {r.status_code} {r.text[:500]}")
        job_id = r.json()["id"]
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            st = self.http.get(f"{self.url}/jobs/{job_id}").json()
            if st["status"] == "done":
                with self.http.stream("GET", f"{self.url}/jobs/{job_id}/result") as resp:
                    resp.raise_for_status()
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with open(out, "wb") as f:
                        for chunk in resp.iter_bytes():
                            f.write(chunk)
                return out
            if st["status"] == "failed":
                raise WorkerError(f"worker job {task}/{engine} failed: {st.get('error')}")
            time.sleep(poll)
        raise WorkerError(f"worker job {job_id} timed out")


_clients: dict[str, WorkerClient] = {}


def get_worker(url: str, timeout: Optional[float] = None) -> WorkerClient:
    if url not in _clients:
        _clients[url] = WorkerClient(url, timeout or 3600)
    return _clients[url]
