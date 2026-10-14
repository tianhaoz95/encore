"""Runs stages in order, recording status in project.json.

Typical human-in-the-loop flow:
  run(until="script")      -> review characters + script in the UI
  run(from="voices", until="keyframes") -> review keyframes, regenerate bad ones
  run(from="shoot")        -> final film
"""

from __future__ import annotations

import traceback
from typing import Callable, Optional

from .core.config import Config
from .core.project import Project
from .core.schemas import STAGE_ORDER, StageName
from .stages import analyze, bible, edit, keyframes, script, shoot, voices

STAGES: dict[StageName, Callable] = {
    StageName.analyze: analyze.run,
    StageName.bible: bible.run,
    StageName.script: script.run,
    StageName.voices: voices.run,
    StageName.keyframes: keyframes.run,
    StageName.shoot: shoot.run,
    StageName.edit: edit.run,
}

# stages that understand per-shot regeneration
PER_SHOT = {StageName.voices, StageName.keyframes, StageName.shoot}


def select(from_stage: Optional[str] = None, until: Optional[str] = None,
           only: Optional[str] = None, stages: Optional[list[str]] = None) -> list[StageName]:
    if stages:
        return [s for s in STAGE_ORDER if s.value in stages]
    if only:
        return [StageName(only)]
    i = STAGE_ORDER.index(StageName(from_stage)) if from_stage else 0
    j = STAGE_ORDER.index(StageName(until)) if until else len(STAGE_ORDER) - 1
    return STAGE_ORDER[i: j + 1]


def first_incomplete(project: Project) -> Optional[str]:
    for s in STAGE_ORDER:
        if project.meta.stages[s.value].status != "done":
            return s.value
    return None


def run(project: Project, cfg: Config, from_stage: Optional[str] = None, until: Optional[str] = None,
        only: Optional[str] = None, shots: Optional[list[str]] = None, force: bool = False,
        stages: Optional[list[str]] = None, on_stage: Optional[Callable[[str, str], None]] = None) -> None:
    for stage in select(from_stage, until, only, stages):
        if shots and stage not in PER_SHOT and stage != StageName.edit:
            continue
        project.set_stage(stage.value, "running")
        if on_stage:
            on_stage(stage.value, "running")
        project.log(f"=== {stage.value} ===")
        try:
            kwargs = {"shots": shots, "force": force or bool(shots)} if stage in PER_SHOT else {}
            STAGES[stage](project, cfg, **kwargs)
        except Exception as e:
            project.log(f"{stage.value} FAILED: {e}\n{traceback.format_exc()}")
            project.set_stage(stage.value, "failed", f"{type(e).__name__}: {e}")
            if on_stage:
                on_stage(stage.value, "failed")
            raise
        project.set_stage(stage.value, "done")
        if on_stage:
            on_stage(stage.value, "done")
