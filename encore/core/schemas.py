"""Data models shared by every stage. All of these serialise to JSON in the project dir."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- analysis --


class Scene(BaseModel):
    index: int
    start: float
    end: float
    keyframe: Optional[str] = None  # path relative to project dir
    caption: Optional[str] = None


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[str] = None  # diarization label, e.g. "SPEAKER_00"


class FaceTrack(BaseModel):
    """One detected face occurrence (a single frame)."""

    time: float
    bbox: list[float]  # x1, y1, x2, y2 in source pixels
    score: float
    sharpness: float
    crop: str  # path relative to project dir
    cluster: int = -1


class SourceInfo(BaseModel):
    path: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


class Analysis(BaseModel):
    source: SourceInfo
    scenes: list[Scene] = Field(default_factory=list)
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    faces: list[FaceTrack] = Field(default_factory=list)
    vocals_path: Optional[str] = None
    instrumental_path: Optional[str] = None
    last_frame: Optional[str] = None
    color_stats: Optional[dict] = None  # LAB mean/std of the source, for grading
    summary: Optional[str] = None
    visual_style: Optional[str] = None


# ------------------------------------------------------------------- bible --


class Character(BaseModel):
    id: str  # stable slug, e.g. "char_0"
    name: str
    description: str = ""
    face_refs: list[str] = Field(default_factory=list)  # crops, best first
    voice_ref: Optional[str] = None  # wav, 5-15 s of clean speech
    voice_ref_text: Optional[str] = None  # transcript of voice_ref (helps F5/CosyVoice)
    voice_preset: Optional[str] = None  # fallback voice name for TTS engines
    language: str = "en"
    lora: Optional[str] = None  # optional identity LoRA name on the image backend
    enabled: bool = True


class StoryBible(BaseModel):
    title: str = "Untitled"
    summary: str = ""
    visual_style: str = ""
    setting: str = ""
    language: str = "en"
    characters: list[Character] = Field(default_factory=list)
    transcript_excerpt: str = ""

    def character(self, cid: str) -> Optional[Character]:
        for c in self.characters:
            if c.id == cid or c.name.lower() == cid.lower():
                return c
        return None


# ------------------------------------------------------------------ script --


class ShotKind(str, Enum):
    talking = "talking"  # characters speak on camera (lip-synced)
    broll = "broll"  # visuals only, maybe narration/VO
    extend = "extend"  # direct continuation of the source clip's last frame


class Framing(str, Enum):
    wide = "wide"
    medium = "medium"
    closeup = "closeup"
    two_shot = "two_shot"


class Line(BaseModel):
    speaker: str  # character id, or "host" / "narrator" for non-cast voices
    text: str
    emotion: str = "neutral"


class Shot(BaseModel):
    id: str
    kind: ShotKind = ShotKind.talking
    framing: Framing = Framing.medium
    setting: str = ""
    characters: list[str] = Field(default_factory=list)  # character ids on screen
    visual: str = ""  # image/video prompt
    camera: str = "static"
    lines: list[Line] = Field(default_factory=list)
    duration: float = 5.0  # seconds; for talking shots the audio length wins


class ShotList(BaseModel):
    title: str
    format: str  # interview, podcast, vlog, ...
    logline: str = ""
    extra_voices: dict[str, str] = Field(
        default_factory=dict,
        description="non-cast speakers (e.g. host) -> short voice description",
    )
    shots: list[Shot]


# ---------------------------------------------------------------- project --


class StageName(str, Enum):
    analyze = "analyze"
    bible = "bible"
    script = "script"
    voices = "voices"
    keyframes = "keyframes"
    shoot = "shoot"
    edit = "edit"


STAGE_ORDER = [s for s in StageName]


class StageState(BaseModel):
    status: str = "pending"  # pending | running | done | failed
    error: Optional[str] = None
    updated: Optional[float] = None


class ProjectMeta(BaseModel):
    name: str
    prompt: str
    source: str  # relative path of the copied source clip
    created: float
    stages: dict[str, StageState] = Field(
        default_factory=lambda: {s.value: StageState() for s in StageName}
    )
    options: dict = Field(default_factory=dict)  # per-project overrides (format, length, ...)
