"""A project is a directory holding every intermediate artifact, so any stage can
be re-run (or a single shot regenerated) without redoing earlier work."""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from .schemas import Analysis, ProjectMeta, ShotList, StageState, StoryBible

T = TypeVar("T", bound=BaseModel)

_lock = threading.RLock()


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return s[:48] or "project"


class Project:
    def __init__(self, path: Path):
        self.path = Path(path)

    # ---- creation / discovery

    @classmethod
    def create(cls, projects_dir: Path, source: Path, prompt: str, name: Optional[str] = None,
               options: Optional[dict] = None) -> "Project":
        name = slugify(name or f"{source.stem}-{int(time.time())}")
        path = Path(projects_dir) / name
        if path.exists():
            raise FileExistsError(f"project {name} already exists")
        (path / "source").mkdir(parents=True)
        dst = path / "source" / f"clip{source.suffix.lower()}"
        shutil.copy2(source, dst)
        proj = cls(path)
        proj.save_meta(ProjectMeta(name=name, prompt=prompt, source=str(dst.relative_to(path)),
                                   created=time.time(), options=options or {}))
        return proj

    @staticmethod
    def list(projects_dir: Path) -> list["Project"]:
        d = Path(projects_dir)
        if not d.exists():
            return []
        return [Project(p) for p in sorted(d.iterdir()) if (p / "project.json").exists()]

    # ---- paths

    def p(self, *parts: str) -> Path:
        return self.path.joinpath(*parts)

    def dir(self, *parts: str) -> Path:
        d = self.p(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def rel(self, path: Path) -> str:
        return str(Path(path).resolve().relative_to(self.path.resolve()))

    @property
    def source(self) -> Path:
        return self.p(self.meta.source)

    # ---- json helpers

    def _read(self, name: str, model: Type[T]) -> Optional[T]:
        f = self.p(name)
        if not f.exists():
            return None
        return model.model_validate_json(f.read_text())

    def _write(self, name: str, obj: BaseModel) -> None:
        f = self.p(name)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f.suffix + ".tmp")
        tmp.write_text(obj.model_dump_json(indent=2))
        tmp.replace(f)

    @property
    def meta(self) -> ProjectMeta:
        m = self._read("project.json", ProjectMeta)
        assert m is not None, f"not a project: {self.path}"
        return m

    def save_meta(self, meta: ProjectMeta) -> None:
        with _lock:
            self._write("project.json", meta)

    def set_stage(self, stage: str, status: str, error: Optional[str] = None) -> None:
        with _lock:
            meta = self.meta
            meta.stages[stage] = StageState(status=status, error=error, updated=time.time())
            self.save_meta(meta)

    def update_meta(self, **kw) -> ProjectMeta:
        with _lock:
            meta = self.meta.model_copy(update=kw)
            self.save_meta(meta)
            return meta

    @property
    def analysis(self) -> Optional[Analysis]:
        return self._read("analysis/analysis.json", Analysis)

    def save_analysis(self, a: Analysis) -> None:
        self._write("analysis/analysis.json", a)

    @property
    def bible(self) -> Optional[StoryBible]:
        return self._read("bible.json", StoryBible)

    def save_bible(self, b: StoryBible) -> None:
        self._write("bible.json", b)

    @property
    def script(self) -> Optional[ShotList]:
        return self._read("script.json", ShotList)

    def save_script(self, s: ShotList) -> None:
        self._write("script.json", s)

    def read_json(self, name: str, default=None):
        f = self.p(name)
        return json.loads(f.read_text()) if f.exists() else default

    def write_json(self, name: str, data) -> None:
        f = self.p(name)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # ---- per-shot artifact locations

    def shot_audio(self, shot_id: str) -> Path:
        return self.dir("audio") / f"{shot_id}.wav"

    def shot_keyframe(self, shot_id: str) -> Path:
        return self.dir("keyframes") / f"{shot_id}.png"

    def shot_video(self, shot_id: str) -> Path:
        return self.dir("shots") / f"{shot_id}.mp4"

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
        with _lock:
            with open(self.p("log.txt"), "a") as f:
                f.write(line)
