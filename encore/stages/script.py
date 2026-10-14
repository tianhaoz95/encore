"""Stage 3 — write the script / shot list."""

from __future__ import annotations

from ..core.config import Config
from ..core.project import Project
from ..core.schemas import ShotList
from ..write.scriptwriter import write_script


def run(project: Project, cfg: Config, **_) -> ShotList:
    bible = project.bible
    assert bible is not None, "run bible first"
    meta = project.meta
    script = write_script(cfg.llm, bible, meta.prompt, meta.options)
    project.save_script(script)
    total = sum(s.duration for s in script.shots)
    project.log(f"script: '{script.title}' ({script.format}), {len(script.shots)} shots, ~{total:.0f}s")
    return script
