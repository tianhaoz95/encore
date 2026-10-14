"""Turn (story bible + user request) into a shot list with a local LLM."""

from __future__ import annotations

import json
import re

from ..core.config import LLMConfig
from ..core.llm import ChatClient
from ..core.schemas import Framing, Line, Shot, ShotKind, ShotList, StoryBible

SYSTEM = """You are a screenwriter and director creating a short follow-up video that \
extends an existing clip. You write the script AND the shot list. Output ONLY JSON.

Rules:
- Every shot has a unique id: "s01", "s02", ...
- kind:
  * "talking": characters on screen speak lines (will be lip-synced). Put the speakers in `characters`.
  * "broll": visuals with no on-screen speech (optional voice-over lines from a narrator/host).
  * "extend": a direct visual continuation of the source clip's final frame (use at most once, as s01, only if it helps the transition).
- framing: wide | medium | closeup | two_shot. Vary framing like a real edit (establishing wide, then mediums/close-ups, cutaways).
- `speaker` in lines must be a character id from the cast list, or a key you define in `extra_voices`
  (e.g. "host", "narrator") for people who are not in the source clip.
- Lines are natural spoken dialogue, max ~30 words each, in the requested language. 1-4 lines per talking shot.
- `visual` is a self-contained prompt for an image/video model: describe people by APPEARANCE (never by name;
  models do not know names), their position in frame, action, setting, lighting, lens. 30-70 words.
- `setting`: a short location name. Reuse the EXACT same string for every shot in the same location so the
  look stays consistent.
- `duration` in seconds: talking shots ~ length of their lines; broll 3-5.
- Stay faithful to who the characters are. Keep it respectful; no defamatory or explicit content.
"""


def _cast_block(bible: StoryBible) -> str:
    cast = [{"id": c.id, "name": c.name, "appearance": c.description or "unknown",
             "has_voice_sample": bool(c.voice_ref)} for c in bible.characters if c.enabled]
    return json.dumps(cast, ensure_ascii=False, indent=1)


def build_messages(bible: StoryBible, request: str, options: dict) -> list[dict]:
    seconds = options.get("target_seconds", 60)
    lang = options.get("language") or bible.language or "en"
    user = f"""SOURCE CLIP
Summary: {bible.summary or 'n/a'}
Visual style: {bible.visual_style or 'n/a'}
Setting: {bible.setting or 'n/a'}
Speech heard in the clip: {bible.transcript_excerpt[:800] or 'n/a'}

CAST (ids to use as speakers):
{_cast_block(bible)}

REQUEST: {request}

Target total length: about {seconds} seconds ({max(3, int(seconds / 6))}-{max(4, int(seconds / 3.5))} shots).
Dialogue language: {lang} (unless the request says otherwise).

Return JSON with keys: title, format, logline, extra_voices (object: speaker key -> voice description), shots
(array of {{id, kind, framing, setting, characters, visual, camera, lines: [{{speaker, text, emotion}}], duration}})."""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def write_script(cfg: LLMConfig, bible: StoryBible, request: str, options: dict) -> ShotList:
    if cfg.backend == "template":
        return template_script(bible, request, options)
    client = ChatClient(cfg.base_url, cfg.model, cfg.api_key, cfg.timeout, cfg.temperature, cfg.max_tokens)
    script = client.structured(build_messages(bible, request, options), ShotList)
    return normalize(script, bible)


def revise_script(cfg: LLMConfig, bible: StoryBible, script: ShotList, instruction: str) -> ShotList:
    """Apply a natural-language edit ("make s03 funnier", "add a shot where ...")."""
    client = ChatClient(cfg.base_url, cfg.model, cfg.api_key, cfg.timeout, cfg.temperature, cfg.max_tokens)
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"CAST:\n{_cast_block(bible)}\n\nCURRENT SHOT LIST:\n"
                                        f"{script.model_dump_json(indent=1)}\n\nREVISION REQUEST: {instruction}\n"
                                        "Return the full revised shot list JSON."}]
    return normalize(client.structured(msgs, ShotList), bible)


def normalize(script: ShotList, bible: StoryBible) -> ShotList:
    """Repair common LLM slips: names instead of ids, missing speakers on screen,
    duplicate ids, an `extend` shot that is not first."""
    by_name = {c.name.lower(): c.id for c in bible.characters}
    ids = {c.id for c in bible.characters}

    def fix(ref: str) -> str:
        r = ref.strip()
        if r in ids:
            return r
        return by_name.get(r.lower(), re.sub(r"\W+", "_", r.lower()).strip("_") or "narrator")

    seen: set[str] = set()
    shots: list[Shot] = []
    for i, s in enumerate(script.shots):
        s.characters = [c for c in dict.fromkeys(fix(c) for c in s.characters) if c in ids]
        s.lines = [Line(speaker=fix(l.speaker), text=l.text.strip(), emotion=l.emotion)
                   for l in s.lines if l.text.strip()]
        for l in s.lines:
            if l.speaker not in ids and l.speaker not in script.extra_voices:
                script.extra_voices[l.speaker] = "a clear, friendly voice"
        if s.kind == ShotKind.talking:
            onscreen_speakers = [l.speaker for l in s.lines if l.speaker in ids]
            for spk in onscreen_speakers:
                if spk not in s.characters:
                    s.characters.append(spk)
            if not s.lines:
                s.kind = ShotKind.broll
        if s.kind == ShotKind.extend and shots:
            s.kind = ShotKind.broll
        sid = s.id if s.id and s.id not in seen else f"s{i + 1:02d}"
        while sid in seen:
            sid += "b"
        s.id = sid
        seen.add(sid)
        s.setting = s.setting or bible.setting or "studio"
        s.duration = float(min(max(s.duration or 4.0, 1.5), 30.0))
        shots.append(s)
    script.shots = shots
    return script


def template_script(bible: StoryBible, request: str, options: dict) -> ShotList:
    """Deterministic no-LLM script (tests, dry runs, or when no LLM server is up)."""
    cast = [c for c in bible.characters if c.enabled] or []
    ids = [c.id for c in cast]
    look = lambda c: c.description or "a person"  # noqa: E731
    setting = "podcast studio"
    everyone = ", ".join(look(c) for c in cast) or "the guests"
    shots = [Shot(id="s01", kind=ShotKind.talking, framing=Framing.wide, setting=setting, characters=ids,
                  visual=f"Wide shot of {everyone} sitting on a sofa in a cozy podcast studio with "
                         "microphones, warm practical lights, shallow depth of field",
                  lines=[Line(speaker="host", text=f"Welcome back! Today we're talking about: {request[:80]}.")],
                  duration=5)]
    questions = ["How did that performance feel?", "What was the hardest part of preparing?",
                 "Anything you want to say to the fans?"]
    for i, c in enumerate(cast[:3]):
        shots.append(Shot(id=f"s{len(shots) + 1:02d}", kind=ShotKind.talking, framing=Framing.closeup,
                          setting=setting, characters=[c.id],
                          visual=f"Close-up of {look(c)} answering a question, smiling, studio microphone in "
                                 "front, warm light", lines=[
                              Line(speaker="host", text=questions[i % len(questions)]),
                              Line(speaker=c.id, text="Honestly, it was amazing. We worked so hard for this, "
                                                      "and seeing everyone there made it worth it.")],
                          duration=6))
    shots.append(Shot(id=f"s{len(shots) + 1:02d}", kind=ShotKind.broll, framing=Framing.wide, setting=setting,
                      characters=ids, visual=f"{everyone} laughing together in the studio, slow dolly out",
                      duration=4))
    return normalize(ShotList(title="Behind the Stage", format="podcast", logline=request,
                              extra_voices={"host": "warm, upbeat podcast host"}, shots=shots), bible)
