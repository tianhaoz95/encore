"""Configuration: which backend runs each stage, and where (Mac vs DGX Spark).

Everything is local: "remote" here only ever means another machine on your LAN
(e.g. the orchestrator on the Mac Studio calling ComfyUI on the DGX Spark).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    # Any OpenAI-compatible server: Ollama, mlx_lm.server, vLLM, llama.cpp, LM Studio.
    backend: str = "openai"  # openai | template (no-LLM fallback, for tests/dry runs)
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen3:32b"
    api_key: str = "local"
    temperature: float = 0.8
    max_tokens: int = 8192
    timeout: float = 600


class VLMConfig(BaseModel):
    backend: str = "openai"  # openai | none
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen2.5vl:7b"
    api_key: str = "local"
    max_frames: int = 8
    timeout: float = 300


class ASRConfig(BaseModel):
    backend: str = "auto"  # auto | mlx-whisper | faster-whisper | none
    model: str = "large-v3-turbo"
    language: Optional[str] = None  # None = auto-detect


class SeparationConfig(BaseModel):
    backend: str = "auto"  # auto | demucs | none
    model: str = "htdemucs"


class DiarizationConfig(BaseModel):
    backend: str = "auto"  # auto | pyannote | none
    model: str = "pyannote/speaker-diarization-3.1"
    hf_token_env: str = "HF_TOKEN"  # pyannote weights are gated; token used for download only


class FacesConfig(BaseModel):
    backend: str = "auto"  # auto | insightface | opencv | none
    sample_fps: float = 2.0
    min_face_px: int = 48
    cluster_threshold: float = 0.45  # cosine distance for merging identities
    min_cluster_size: int = 3
    max_characters: int = 8
    refs_per_character: int = 6


class TTSConfig(BaseModel):
    backend: str = "worker"  # worker | say (macOS built-in) | silent
    url: str = "http://spark.local:8100"
    engine: str = "chatterbox"  # engine name on the worker: chatterbox | f5 | cosyvoice | ...
    timeout: float = 900


class ImageConfig(BaseModel):
    backend: str = "comfyui"  # comfyui | still (PIL compositor fallback)
    url: str = "http://spark.local:8188"
    workflow: str = "workflows/keyframe_flux_kontext.json"
    width: int = 1280
    height: int = 720
    steps: int = 24
    identity_threshold: float = 0.35  # min ArcFace cosine sim to accept a keyframe
    max_attempts: int = 3
    timeout: float = 1200


class VideoConfig(BaseModel):
    # Separate backends per shot kind so talking heads can go to the worker
    # (InfiniteTalk/MultiTalk) while b-roll goes through ComfyUI (Wan 2.2).
    talking_backend: str = "worker"  # worker | comfyui | kenburns
    broll_backend: str = "comfyui"  # comfyui | worker | kenburns
    comfy_url: str = "http://spark.local:8188"
    worker_url: str = "http://spark.local:8100"
    talking_engine: str = "infinitetalk"
    broll_engine: str = "wan_i2v"
    workflows: dict[str, str] = Field(
        default_factory=lambda: {
            "broll": "workflows/i2v_wan22_ti2v5b.json",
            "extend": "workflows/i2v_wan22_ti2v5b.json",
            "talking": "workflows/s2v_wan22.json",
        }
    )
    width: int = 1280
    height: int = 704
    fps: int = 24
    max_clip_seconds: float = 5.0  # i2v models produce ~5s; longer shots are chained
    timeout: float = 3600


class EditConfig(BaseModel):
    width: int = 1280
    height: int = 720
    fps: int = 25
    color_match: bool = True
    grain: int = 4  # 0 = off
    watermark: bool = True
    watermark_text: str = "AI-GENERATED"
    prepend_source: bool = True  # start the output with the original clip
    music_bed: bool = True  # use the source's instrumental stem under the dialogue
    music_gain_db: float = -18.0
    subtitles: str = "sidecar"  # none | sidecar | burn
    crossfade: float = 0.0


class Config(BaseModel):
    projects_dir: str = "projects"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    vlm: VLMConfig = Field(default_factory=VLMConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    separation: SeparationConfig = Field(default_factory=SeparationConfig)
    diarization: DiarizationConfig = Field(default_factory=DiarizationConfig)
    faces: FacesConfig = Field(default_factory=FacesConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    image: ImageConfig = Field(default_factory=ImageConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    edit: EditConfig = Field(default_factory=EditConfig)



REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_path(p: str) -> Path:
    """Resolve a config path (e.g. a workflow) relative to the repo root."""
    path = Path(p)
    return path if path.is_absolute() else REPO_ROOT / path


_DEFAULT_LOCATIONS = ["config.yaml", "config.yml"]


def load_config(path: Optional[str | os.PathLike] = None) -> Config:
    path = path or os.environ.get("ENCORE_CONFIG")
    candidates = [Path(path)] if path else [Path(p) for p in _DEFAULT_LOCATIONS]
    for c in candidates:
        if c.exists():
            data = yaml.safe_load(c.read_text()) or {}
            return Config.model_validate(data)
    if path:
        raise FileNotFoundError(path)
    return Config()


def apply_overrides(cfg: Config, overrides: list[str]) -> Config:
    """Apply dotted `key=value` overrides, e.g. `tts.backend=say`."""
    data = cfg.model_dump()
    for item in overrides:
        key, _, raw = item.partition("=")
        node = data
        parts = key.strip().split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = yaml.safe_load(raw)
    return Config.model_validate(data)
