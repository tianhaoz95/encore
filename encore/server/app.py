"""Web UI + JSON API. Runs on the Mac next to the orchestrator; heavy work is
queued on a single background thread (the GPUs can only do one thing at a time)."""

from __future__ import annotations

import queue
import shutil
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from .. import pipeline
from ..core import media
from ..core.config import Config
from ..core.project import Project
from ..core.schemas import ShotList, StoryBible

STATIC = Path(__file__).parent / "static"


class RunRequest(BaseModel):
    from_stage: Optional[str] = None
    until: Optional[str] = None
    only: Optional[str] = None
    shots: Optional[list[str]] = None
    stages: Optional[list[str]] = None
    force: bool = False


class ReviseRequest(BaseModel):
    instruction: str


class JobRunner:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.q: "queue.Queue[tuple[str, RunRequest]]" = queue.Queue()
        self.current: Optional[dict] = None
        self.pending: list[dict] = []
        self.last_error: dict[str, str] = {}
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, name: str, req: RunRequest) -> None:
        self.pending.append({"project": name, **req.model_dump()})
        self.q.put((name, req))

    def busy(self, name: str) -> bool:
        return any(j["project"] == name for j in ([self.current] if self.current else []) + self.pending)

    def _loop(self) -> None:
        while True:
            name, req = self.q.get()
            self.pending.pop(0)
            self.current = {"project": name, **req.model_dump(), "started": time.time()}
            self.last_error.pop(name, None)
            try:
                proj = Project(Path(self.cfg.projects_dir) / name)
                pipeline.run(proj, self.cfg, from_stage=req.from_stage, until=req.until, only=req.only,
                             shots=req.shots, force=req.force, stages=req.stages)
            except Exception as e:
                self.last_error[name] = f"{type(e).__name__}: {e}"
                traceback.print_exc()
            finally:
                self.current = None


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="encore")
    runner = JobRunner(cfg)
    root = Path(cfg.projects_dir)
    root.mkdir(parents=True, exist_ok=True)

    def get(name: str) -> Project:
        p = root / name
        if not (p / "project.json").exists():
            raise HTTPException(404, f"no project {name}")
        return Project(p)

    def url(proj: Project, path: Path) -> Optional[str]:
        if not path.exists():
            return None
        return f"/files/{proj.meta.name}/{proj.rel(path)}?v={int(path.stat().st_mtime)}"

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text()

    @app.get("/api/projects")
    def list_projects():
        return [{"name": p.meta.name, "prompt": p.meta.prompt, "created": p.meta.created,
                 "stages": {k: v.status for k, v in p.meta.stages.items()}} for p in Project.list(root)]

    @app.post("/api/projects")
    async def create(clip: UploadFile = File(...), prompt: str = Form(...), name: str = Form(""),
                     seconds: int = Form(60), language: str = Form(""), names: str = Form("")):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / (Path(clip.filename or "clip.mp4").name)
            with open(tmp, "wb") as f:
                shutil.copyfileobj(clip.file, f)
            opts: dict = {"target_seconds": seconds}
            if language:
                opts["language"] = language
            if names.strip():
                opts["names"] = [n.strip() for n in names.split(",") if n.strip()]
            try:
                proj = Project.create(root, tmp, prompt, name or None, opts)
            except FileExistsError as e:
                raise HTTPException(409, str(e))
        return {"name": proj.meta.name}

    @app.get("/api/projects/{name}")
    def detail(name: str):
        proj = get(name)
        meta, bible, script, a = proj.meta, proj.bible, proj.script, proj.analysis
        shots = []
        for s in (script.shots if script else []):
            shots.append({"id": s.id, "keyframe": url(proj, proj.shot_keyframe(s.id)),
                          "video": url(proj, proj.shot_video(s.id)), "audio": url(proj, proj.shot_audio(s.id))})
        cast = []
        for c in (bible.characters if bible else []):
            cast.append({"id": c.id, "refs": [url(proj, proj.p(r)) for r in c.face_refs],
                         "voice": url(proj, proj.p(c.voice_ref)) if c.voice_ref else None})
        log = proj.p("log.txt")
        return {
            "meta": meta.model_dump(),
            "bible": bible.model_dump() if bible else None,
            "script": script.model_dump() if script else None,
            "analysis": {"summary": a.summary, "visual_style": a.visual_style, "scenes": len(a.scenes),
                         "duration": a.source.duration,
                         "transcript": " ".join(t.text for t in a.transcript)[:1500]} if a else None,
            "source": url(proj, proj.source),
            "shots": shots,
            "cast": cast,
            "final": url(proj, proj.p("output", "final.mp4")),
            "srt": url(proj, proj.p("output", "final.srt")),
            "log": log.read_text()[-6000:] if log.exists() else "",
            "busy": runner.busy(name),
            "current": runner.current if runner.current and runner.current["project"] == name else None,
            "error": runner.last_error.get(name),
        }

    @app.put("/api/projects/{name}/bible")
    def put_bible(name: str, bible: StoryBible):
        get(name).save_bible(bible)
        return {"ok": True}

    @app.put("/api/projects/{name}/script")
    def put_script(name: str, script: ShotList):
        proj = get(name)
        from ..write.scriptwriter import normalize

        proj.save_script(normalize(script, proj.bible) if proj.bible else script)
        return {"ok": True}

    @app.put("/api/projects/{name}/prompt")
    def put_prompt(name: str, body: dict):
        proj = get(name)
        proj.update_meta(prompt=body.get("prompt", proj.meta.prompt),
                         options={**proj.meta.options, **(body.get("options") or {})})
        return {"ok": True}

    @app.post("/api/projects/{name}/revise")
    def revise(name: str, req: ReviseRequest):
        from ..write.scriptwriter import revise_script

        proj = get(name)
        if not proj.script or not proj.bible:
            raise HTTPException(400, "no script yet")
        proj.save_script(revise_script(cfg.llm, proj.bible, proj.script, req.instruction))
        return {"ok": True}

    @app.post("/api/projects/{name}/run")
    def run(name: str, req: RunRequest):
        get(name)
        runner.submit(name, req)
        return {"queued": True}

    @app.post("/api/projects/{name}/characters/{cid}/voice")
    async def upload_voice(name: str, cid: str, file: UploadFile = File(...), text: str = Form("")):
        proj = get(name)
        bible = proj.bible
        ch = bible.character(cid) if bible else None
        if not ch:
            raise HTTPException(404, cid)
        raw = proj.dir("cast", cid) / f"upload{Path(file.filename or 'v.wav').suffix}"
        with open(raw, "wb") as f:
            shutil.copyfileobj(file.file, f)
        wav = media.to_wav(raw, proj.p("cast", cid, "voice_ref.wav"))
        ch.voice_ref, ch.voice_ref_text = proj.rel(wav), text or None
        proj.save_bible(bible)
        return {"ok": True}

    @app.get("/files/{name}/{path:path}")
    def files(name: str, path: str):
        proj = get(name)
        f = (proj.path / path).resolve()
        if proj.path.resolve() not in f.parents or not f.is_file():
            raise HTTPException(404)
        return FileResponse(f)

    return app
