"""Stage 2 — build the Story Bible: who is in the clip, what they look and sound
like, and the clip's overall look. This is the main human checkpoint: rename
characters, disable extras, or swap in a better voice reference in the UI."""

from __future__ import annotations

import shutil
from collections import defaultdict

import numpy as np

from ..analyze import vlm
from ..core import media
from ..core.config import Config
from ..core.project import Project
from ..core.schemas import Analysis, Character, FaceTrack, StoryBible

VOICE_REF_SECONDS = 12.0


def run(project: Project, cfg: Config, **_) -> StoryBible:
    a = project.analysis
    assert a is not None, "run analyze first"
    desc = project.read_json("analysis/description.json", {}) or {}
    lang = (project.read_json("analysis/language.json", {}) or {}).get("language") or "en"
    names = project.meta.options.get("names") or []

    clusters: dict[int, list[FaceTrack]] = defaultdict(list)
    for f in a.faces:
        if f.cluster >= 0:
            clusters[f.cluster].append(f)
    order = sorted(clusters, key=lambda k: len(clusters[k]), reverse=True)[: cfg.faces.max_characters]

    emb_all = _load_embeddings(project, a)
    chars: list[Character] = []
    for n, k in enumerate(order):
        cid = f"char_{n}"
        cdir = project.dir("cast", cid)
        refs = _pick_refs(clusters[k], cfg.faces.refs_per_character)
        ref_paths = []
        for i, f in enumerate(refs):
            dst = cdir / f"ref_{i}.jpg"
            shutil.copy2(project.p(f.crop), dst)
            ref_paths.append(project.rel(dst))
        if emb_all is not None:
            idx = [i for i, f in enumerate(a.faces) if f.cluster == k]
            m = emb_all[idx].mean(0)
            np.save(cdir / "embedding.npy", m / (np.linalg.norm(m) + 1e-8))
        description = ""
        try:
            description = vlm.describe_person(cfg.vlm, [project.p(r) for r in ref_paths]) or ""
        except Exception as e:
            project.log(f"bible: VLM person description failed for {cid}: {e}")
        name = names[n] if n < len(names) else f"Person {n + 1}"
        chars.append(Character(id=cid, name=name, description=description, face_refs=ref_paths,
                               language=lang))

    if not chars:  # no usable faces (animation, crowd shots, ...): fall back to VLM's people list
        for n, person in enumerate((desc.get("people") or [])[: cfg.faces.max_characters] or ["the main person"]):
            name = names[n] if n < len(names) else f"Person {n + 1}"
            chars.append(Character(id=f"char_{n}", name=name, description=person, language=lang))

    _assign_voices(project, a, clusters, order, chars)

    bible = StoryBible(
        title=project.meta.name,
        summary=a.summary or desc.get("summary", ""),
        visual_style=a.visual_style or desc.get("visual_style", ""),
        setting=desc.get("setting", ""),
        language=lang,
        characters=chars,
        transcript_excerpt=" ".join(t.text for t in a.transcript)[:2000],
    )
    project.save_bible(bible)
    project.log(f"bible: {len(chars)} characters: {', '.join(c.name for c in chars)}")
    return bible


def _load_embeddings(project: Project, a: Analysis):
    f = project.p("analysis", "face_embeddings.npy")
    if not f.exists():
        return None
    E = np.load(f)
    return E if len(E) == len(a.faces) else None


def _pick_refs(faces: list[FaceTrack], n: int) -> list[FaceTrack]:
    """Large, sharp, confident faces, spread out in time (different poses/lighting)."""
    def quality(f: FaceTrack) -> float:
        size = min(f.bbox[2] - f.bbox[0], f.bbox[3] - f.bbox[1])
        return f.score * np.log1p(size) * np.log1p(f.sharpness)

    picked: list[FaceTrack] = []
    for f in sorted(faces, key=quality, reverse=True):
        if all(abs(f.time - p.time) > 1.0 for p in picked):
            picked.append(f)
        if len(picked) >= n:
            break
    return picked or faces[:n]


def _assign_voices(project: Project, a: Analysis, clusters, order, chars: list[Character]) -> None:
    """Attach a voice reference to each character.

    With diarization, speaker labels are mapped to characters by on-screen
    co-occurrence; without it, each segment goes to the most prominent face on
    screen while it is spoken."""
    if not a.transcript or not a.vocals_path or not chars:
        return
    cluster_to_char = {k: chars[i].id for i, k in enumerate(order)}

    def onscreen(start: float, end: float) -> dict[str, float]:
        w: dict[str, float] = defaultdict(float)
        for f in a.faces:
            if start - 0.25 <= f.time <= end + 0.25 and f.cluster in cluster_to_char:
                w[cluster_to_char[f.cluster]] += (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
        return w

    by_char: dict[str, list] = defaultdict(list)
    if any(t.speaker for t in a.transcript):
        votes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for t in a.transcript:
            if t.speaker:
                for cid, w in onscreen(t.start, t.end).items():
                    votes[t.speaker][cid] += w
        mapping, taken = {}, set()
        pairs = sorted(((w, spk, cid) for spk, d in votes.items() for cid, w in d.items()), reverse=True)
        for _, spk, cid in pairs:
            if spk not in mapping and cid not in taken:
                mapping[spk] = cid
                taken.add(cid)
        for t in a.transcript:
            if t.speaker in mapping:
                by_char[mapping[t.speaker]].append(t)
    else:
        for t in a.transcript:
            w = onscreen(t.start, t.end)
            cid = max(w, key=w.get) if w else (chars[0].id if len(chars) == 1 else None)
            if cid:
                by_char[cid].append(t)

    src = project.p(a.vocals_path)
    for c in chars:
        segs = sorted(by_char.get(c.id, []), key=lambda t: t.end - t.start, reverse=True)
        pieces, texts, total = [], [], 0.0
        for t in segs:
            if total >= VOICE_REF_SECONDS:
                break
            if t.end - t.start < 1.0:
                continue
            piece = media.cut_audio(src, t.start, min(t.end, t.start + VOICE_REF_SECONDS - total),
                                    project.p("cast", c.id, f"_seg{len(pieces)}.wav"))
            pieces.append(piece)
            texts.append(t.text)
            total += t.end - t.start
        if not pieces:
            continue
        audio = np.concatenate([np.concatenate([media.read_wav(p), media.silence(0.2)]) for p in pieces])
        out = media.write_wav(project.p("cast", c.id, "voice_ref.wav"), audio)
        for p in pieces:
            p.unlink(missing_ok=True)
        c.voice_ref = project.rel(out)
        c.voice_ref_text = " ".join(texts)
