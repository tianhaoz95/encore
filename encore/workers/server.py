"""encore GPU worker: a small job server that runs TTS / talking-head / i2v
engines on the machine that has the GPU (DGX Spark), one job at a time.

    encore-worker --config worker.yaml --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from .engines import Engine, build


@dataclass
class Job:
    id: str
    task: str
    engine: str
    params: dict
    files: dict[str, Path]
    dir: Path
    status: str = "queued"
    error: Optional[str] = None
    result: Optional[Path] = None
    created: float = field(default_factory=time.time)
    finished: Optional[float] = None


class Worker:
    def __init__(self, conf: dict):
        self.conf = conf
        self.work_dir = Path(conf.get("work_dir", "~/.cache/encore/worker")).expanduser()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.engines: dict[str, Engine] = {n: build(n, c) for n, c in (conf.get("engines") or {}).items()}
        self.jobs: dict[str, Job] = {}
        self.q: "queue.Queue[str]" = queue.Queue()
        self.keep_jobs = int(conf.get("keep_jobs", 200))
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, task: str, engine: str, params: dict, files: dict[str, Path], job_dir: Path) -> Job:
        eng = self.engines.get(engine)
        if eng is None:
            raise HTTPException(404, f"no engine '{engine}' (have: {sorted(self.engines)})")
        if eng.task != task:
            raise HTTPException(400, f"engine '{engine}' does '{eng.task}', not '{task}'")
        job = Job(id=job_dir.name, task=task, engine=engine, params=params, files=files, dir=job_dir)
        self.jobs[job.id] = job
        self.q.put(job.id)
        self._gc()
        return job

    def _loop(self) -> None:
        while True:
            job = self.jobs.get(self.q.get())
            if job is None:
                continue
            job.status = "running"
            try:
                eng = self.engines[job.engine]
                if not eng.loaded:
                    if eng.gpu:  # one big model in memory at a time
                        for other in self.engines.values():
                            if other is not eng and other.gpu and other.loaded:
                                other.unload()
                    eng.load()
                job.result = eng.run(job.params, job.files, job.dir / "out.bin")
                job.status = "done"
            except Exception as e:
                job.status, job.error = "failed", f"{type(e).__name__}: {e}"
                traceback.print_exc()
            job.finished = time.time()

    def _gc(self) -> None:
        done = sorted((j for j in self.jobs.values() if j.finished), key=lambda j: j.finished)
        for j in done[: max(0, len(done) - self.keep_jobs)]:
            shutil.rmtree(j.dir, ignore_errors=True)
            self.jobs.pop(j.id, None)


def create_app(conf: dict) -> FastAPI:
    worker = Worker(conf)
    app = FastAPI(title="encore worker")

    @app.get("/health")
    def health():
        return {"ok": True, "engines": {n: {"task": e.task, "loaded": e.loaded} for n, e in worker.engines.items()},
                "queued": worker.q.qsize()}

    @app.post("/jobs/{task}")
    async def submit(task: str, request: Request):
        form = await request.form()
        job_dir = worker.work_dir / uuid.uuid4().hex
        job_dir.mkdir(parents=True)
        files: dict[str, Path] = {}
        for key, val in form.multi_items():
            if hasattr(val, "filename") and val.filename:
                dst = job_dir / f"{key}{Path(val.filename).suffix}"
                with open(dst, "wb") as f:
                    shutil.copyfileobj(val.file, f)
                files[key] = dst
        params = json.loads(form.get("params") or "{}")
        job = worker.submit(task, str(form.get("engine")), params, files, job_dir)
        return {"id": job.id}

    @app.get("/jobs/{job_id}")
    def status(job_id: str):
        j = worker.jobs.get(job_id)
        if not j:
            raise HTTPException(404)
        return {"id": j.id, "status": j.status, "error": j.error, "task": j.task, "engine": j.engine}

    @app.get("/jobs/{job_id}/result")
    def result(job_id: str):
        j = worker.jobs.get(job_id)
        if not j or j.status != "done" or not j.result:
            raise HTTPException(404)
        return FileResponse(j.result)

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="encore GPU worker")
    ap.add_argument("--config", default=os.environ.get("ENCORE_WORKER_CONFIG", "worker.yaml"))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8100)
    args = ap.parse_args()
    conf = yaml.safe_load(Path(args.config).read_text()) or {}
    import uvicorn

    uvicorn.run(create_app(conf), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
