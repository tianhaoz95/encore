"""Stage 6 — animate each keyframe into a shot."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from ..backends.video import VideoGen
from ..core.config import Config
from ..core.project import Project
from ..core.schemas import ShotKind

TALK_SUFFIX = (" The person speaking talks naturally with clear lip movement, expressive face and subtle head "
               "motion; anyone else listens and reacts naturally. Stable camera.")


def run(project: Project, cfg: Config, shots: Optional[list[str]] = None, force: bool = False, **_) -> None:
    script = project.script
    assert script, "run script first"
    gen = VideoGen(cfg.video)
    for shot in script.shots:
        if shots and shot.id not in shots:
            continue
        out = project.shot_video(shot.id)
        if out.exists() and not force:
            continue
        key = project.shot_keyframe(shot.id)
        if not key.exists():
            raise FileNotFoundError(f"no keyframe for {shot.id}; run keyframes first")
        audio = project.shot_audio(shot.id)
        backend = gen.backend_for(shot.kind.value)
        project.log(f"shoot: {shot.id} {shot.kind.value} via {backend} ({shot.duration:.1f}s)")
        if shot.kind == ShotKind.talking and audio.exists():
            chars = [c for c in shot.characters if (project.dir("audio") / f"{shot.id}.{c}.wav").exists()]
            bboxes = None
            if len(chars) > 1 and backend != "kenburns":
                chars, bboxes = speaker_layout(project, cfg, key, chars)
            tracks = [project.dir("audio") / f"{shot.id}.{c}.wav" for c in chars]
            gen.talking(key, audio, tracks, shot.visual + TALK_SUFFIX, out, shot.duration, bboxes=bboxes)
        else:
            prompt = f"{shot.visual}. Camera: {shot.camera}."
            gen.motion(shot.kind.value, key, prompt, out, shot.duration)


def speaker_layout(project: Project, cfg: Config, image: Path, chars: list[str]):
    """Match each speaking character to a face in the keyframe so multi-person
    lip-sync drives the right mouth. Returns (chars ordered left->right, bboxes),
    or (chars, None) if matching isn't possible."""
    embs = {c: np.load(project.p("cast", c, "embedding.npy")) for c in chars
            if project.p("cast", c, "embedding.npy").exists()}
    if len(embs) != len(chars):
        return chars, None
    try:
        import cv2

        from ..analyze.faces import get_engine

        faces = get_engine(cfg.faces.backend).detect(cv2.imread(str(image)))
    except Exception as e:
        project.log(f"shoot: speaker layout unavailable ({e})")
        return chars, None
    if len(faces) < len(chars):
        return chars, None
    sims = np.array([[float(f.embedding @ embs[c]) for f in faces] for c in chars])
    assigned: dict[str, int] = {}
    for _ in chars:  # greedy best-pair assignment
        i, j = np.unravel_index(np.argmax(sims), sims.shape)
        assigned[chars[i]] = int(j)
        sims[i, :] = -np.inf
        sims[:, j] = -np.inf
    ordered = sorted(chars, key=lambda c: faces[assigned[c]].bbox[0])
    return ordered, [faces[assigned[c]].bbox.round().tolist() for c in ordered]
