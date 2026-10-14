"""Stage 4 — synthesise dialogue.

For each shot we produce:
  audio/<shot>.wav         full dialogue mix
  audio/<shot>.<cid>.wav   one track per on-screen character, silent while
                           others talk (what multi-person lip-sync models want)
  audio/<shot>.json        line timings (subtitles, editing)
Line renders are cached by content hash, so editing one line re-renders one line."""

from __future__ import annotations

import hashlib
from typing import Optional

import numpy as np

from ..backends.tts import TTS
from ..core import media
from ..core.config import Config
from ..core.project import Project
from ..core.schemas import Shot, ShotKind, StoryBible

LEAD_IN, GAP, TAIL = 0.3, 0.35, 0.5


def run(project: Project, cfg: Config, shots: Optional[list[str]] = None, **_) -> None:
    bible, script = project.bible, project.script
    assert bible and script, "run script first"
    tts = TTS(cfg.tts)
    voice_order = [c.id for c in bible.characters] + list(script.extra_voices)
    language = project.meta.options.get("language")  # requested dialogue language wins over ASR's guess
    for shot in script.shots:
        if shots and shot.id not in shots:
            continue
        render_shot(project, tts, bible, shot, voice_order, script.extra_voices, language)
    project.save_script(script)  # durations updated to match the audio


def render_shot(project: Project, tts: TTS, bible: StoryBible, shot: Shot, voice_order: list[str],
                extra_voices: dict[str, str], language: Optional[str] = None) -> None:
    sr = media.SR
    if not shot.lines:
        # silent shot: still write an (empty) track so editing is uniform
        media.write_wav(project.shot_audio(shot.id), media.silence(shot.duration))
        project.write_json(f"audio/{shot.id}.json", {"duration": shot.duration, "lines": []})
        return

    lang_default = language or bible.language or "en"
    pieces: list[tuple[str, np.ndarray]] = []
    for line in shot.lines:
        char = bible.character(line.speaker)
        ref = project.p(char.voice_ref) if char and char.voice_ref else None
        ref_stamp = f"{ref}:{ref.stat().st_mtime}" if ref and ref.exists() else ""  # re-render on new voice upload
        key = hashlib.sha1("|".join([tts.backend, line.speaker, line.text, line.emotion, language or "", ref_stamp,
                                     (char.voice_preset or "") if char else ""]).encode()).hexdigest()[:16]
        wav = project.dir("audio", "lines") / f"{key}.wav"
        if not wav.exists():
            tts.synthesize(line.text, wav, language=language or (char.language if char else None) or lang_default,
                           ref_audio=ref if ref and ref.exists() else None,
                           ref_text=char.voice_ref_text if char else None, emotion=line.emotion,
                           voice_index=voice_order.index(line.speaker) if line.speaker in voice_order else 0,
                           voice_preset=(char.voice_preset if char else extra_voices.get(line.speaker)))
        pieces.append((line.speaker, media.trim_silence(media.read_wav(wav))))

    total = LEAD_IN + sum(len(p) / sr for _, p in pieces) + GAP * (len(pieces) - 1) + TAIL
    if shot.kind != ShotKind.talking:
        total = max(total, shot.duration)
    n = int(round(total * sr))
    mix = np.zeros(n, np.float32)
    tracks = {cid: np.zeros(n, np.float32) for cid in shot.characters}
    timings, t = [], LEAD_IN
    for (speaker, samples), line in zip(pieces, shot.lines):
        a = int(round(t * sr))
        b = min(a + len(samples), n)
        mix[a:b] += samples[: b - a]
        if speaker in tracks:
            tracks[speaker][a:b] += samples[: b - a]
        timings.append({"speaker": speaker, "text": line.text, "start": round(t, 3),
                        "end": round(t + len(samples) / sr, 3)})
        t += len(samples) / sr + GAP

    media.write_wav(project.shot_audio(shot.id), mix)
    for cid, tr in tracks.items():
        media.write_wav(project.dir("audio") / f"{shot.id}.{cid}.wav", tr)
    project.write_json(f"audio/{shot.id}.json", {"duration": round(total, 3), "lines": timings})
    shot.duration = round(total, 3)
    project.log(f"voices: {shot.id} {len(pieces)} lines, {total:.1f}s")
