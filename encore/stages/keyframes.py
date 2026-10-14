"""Stage 5 — one approved still per shot (the most important checkpoint: video
generation is expensive, so fix faces and composition here).

Consistency strategy:
  1. per setting, generate a wide MASTER frame with everyone in it, conditioned
     on the characters' reference faces;
  2. every other shot in that setting is an *edit* of the master (closer framing,
     subset of people), conditioned on master + the relevant face refs;
  3. `extend` shots start from the source clip's real last frame;
  4. candidates whose faces don't match the references (ArcFace cosine) are
     regenerated with a new seed."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import numpy as np

from ..backends.image import ImageGen, copy_image
from ..core.config import Config
from ..core.project import Project
from ..core.schemas import Framing, Shot, ShotKind, StoryBible

FRAMING_TEXT = {
    Framing.wide: "wide establishing shot, everyone fully visible",
    Framing.two_shot: "two-shot, both people framed from the waist up",
    Framing.medium: "medium shot from the chest up",
    Framing.closeup: "close-up portrait shot, face fills the frame, shallow depth of field",
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "set"


def run(project: Project, cfg: Config, shots: Optional[list[str]] = None, force: bool = False, **_) -> None:
    bible, script, a = project.bible, project.script, project.analysis
    assert bible and script and a, "run script first"
    gen = ImageGen(cfg.image)
    qc = _QC(project, bible, cfg) if gen.is_real else None
    style = bible.visual_style or "cinematic, photorealistic"
    backdrop = project.p(a.scenes[len(a.scenes) // 2].keyframe) if a.scenes else None

    # ---- masters
    masters: dict[str, Path] = {}
    for setting in dict.fromkeys(s.setting for s in script.shots if s.kind != ShotKind.extend):
        chars = list(dict.fromkeys(c for s in script.shots if s.setting == setting for c in s.characters))
        out = project.dir("keyframes") / f"master_{_slug(setting)}.png"
        masters[setting] = out
        regenerate_master = force and (not shots or any(
            s.setting == setting and s.id in shots and s.framing == Framing.wide for s in script.shots))
        if out.exists() and not regenerate_master:
            continue
        wide = next((s for s in script.shots if s.setting == setting and s.framing == Framing.wide), None)
        people = _people(bible, chars)
        visual = wide.visual if wide else f"{people} in {setting}"
        prompt = (f"{visual}. Setting: {setting}. {FRAMING_TEXT[Framing.wide]}. Style: {style}. "
                  "Keep each person's face, hair and outfit identical to the reference photos.")
        refs = [project.p(bible.character(c).face_refs[0]) for c in chars
                if bible.character(c) and bible.character(c).face_refs]
        _generate(gen, qc, prompt, refs, out, backdrop, chars, label=f"MASTER: {setting}",
                  lora=_lora(bible, chars), project=project)
        project.log(f"keyframes: master for '{setting}' ({len(chars)} people)")

    # ---- per shot
    for shot in script.shots:
        if shots and shot.id not in shots:
            continue
        out = project.shot_keyframe(shot.id)
        if out.exists() and not force:
            continue
        if shot.kind == ShotKind.extend:
            copy_image(project.p(a.last_frame), out)
        else:
            master = masters[shot.setting]
            all_in_setting = list(dict.fromkeys(
                c for s in script.shots if s.setting == shot.setting for c in s.characters))
            if shot.framing == Framing.wide and set(shot.characters) == set(all_in_setting):
                copy_image(master, out)
            else:
                prompt = (f"Using the scene in the first image: {shot.visual}. {FRAMING_TEXT[shot.framing]}. "
                          f"Same location, lighting and wardrobe. Style: {style}. "
                          "Faces must match the reference photos exactly.")
                refs = [master] + [project.p(bible.character(c).face_refs[0]) for c in shot.characters
                                   if bible.character(c) and bible.character(c).face_refs]
                _generate(gen, qc, prompt, refs, out, master, shot.characters,
                          label=f"{shot.id} {shot.framing.value}: {shot.visual}",
                          lora=_lora(bible, shot.characters), project=project)
        project.log(f"keyframes: {shot.id} ({shot.framing.value})")


def _people(bible: StoryBible, ids: list[str]) -> str:
    descs = [(bible.character(c).description or "a person") for c in ids if bible.character(c)]
    return "; ".join(descs) or "the people"


def _lora(bible: StoryBible, ids: list[str]) -> Optional[str]:
    for c in ids:
        ch = bible.character(c)
        if ch and ch.lora:
            return ch.lora
    return None


def _generate(gen: ImageGen, qc: Optional["_QC"], prompt: str, refs: list[Path], out: Path,
              backdrop: Optional[Path], chars: list[str], label: str, lora: Optional[str],
              project: Project) -> None:
    attempts = gen.cfg.max_attempts if qc else 1
    best_score, best_tmp = -1.0, None
    for i in range(attempts):
        tmp = out.with_name(f"{out.stem}.try{i}.png")
        gen.generate(prompt, refs, tmp, backdrop=backdrop, lora=lora, label=label)
        if qc is None:
            tmp.replace(out)
            return
        score = qc.score(tmp, chars)
        project.log(f"keyframes: {out.stem} attempt {i + 1} identity={score:.2f}")
        if score > best_score:
            best_score, best_tmp = score, tmp
        if score >= gen.cfg.identity_threshold:
            break
    assert best_tmp is not None
    best_tmp.replace(out)
    for leftover in out.parent.glob(f"{out.stem}.try*.png"):
        leftover.unlink()


class _QC:
    """Score = mean over expected characters of their best match among detected faces."""

    def __init__(self, project: Project, bible: StoryBible, cfg: Config):
        self.embs: dict[str, np.ndarray] = {}
        for c in bible.characters:
            f = project.p("cast", c.id, "embedding.npy")
            if f.exists():
                self.embs[c.id] = np.load(f)
        self.engine = None
        if self.embs:
            try:
                from ..analyze.faces import get_engine

                self.engine = get_engine(cfg.faces.backend)
            except Exception as e:  # QC is best-effort
                project.log(f"keyframes: identity QC disabled ({e})")

    def score(self, image: Path, chars: list[str]) -> float:
        wanted = [self.embs[c] for c in chars if c in self.embs]
        if self.engine is None or not wanted:
            return 1.0
        import cv2

        img = cv2.imread(str(image))
        faces = self.engine.detect(img) if img is not None else []
        if not faces:
            return 0.0
        F = np.stack([f.embedding for f in faces])
        return float(np.mean([(F @ w).max() for w in wanted]))
