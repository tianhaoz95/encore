"""Visual understanding with a local vision-language model (e.g. Qwen2.5-VL /
Qwen3-VL via Ollama or mlx_vlm.server on the Mac)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..core.config import VLMConfig
from ..core.llm import ChatClient, image_part


class ClipDescription(BaseModel):
    summary: str = Field(description="2-4 sentences: what is happening in the clip")
    visual_style: str = Field(description="lighting, colour palette, camera style, film look")
    setting: str = Field(description="where it takes place")
    people: list[str] = Field(default_factory=list,
                              description="short visual description of each distinct person, in order of prominence")
    genre: str = ""


class PersonDescription(BaseModel):
    description: str = Field(description="appearance: hair, clothing, age range, distinctive features; no names")


def client(cfg: VLMConfig) -> Optional[ChatClient]:
    if cfg.backend == "none":
        return None
    return ChatClient(cfg.base_url, cfg.model, cfg.api_key, cfg.timeout, temperature=0.2, max_tokens=1500)


def describe_clip(cfg: VLMConfig, frames: list[Path], transcript: str) -> Optional[ClipDescription]:
    c = client(cfg)
    if c is None or not frames:
        return None
    content: list[dict] = [{"type": "text", "text": (
        "These frames are sampled in order from one video clip."
        + (f"\nSpeech/lyrics heard in the clip:\n{transcript[:1500]}" if transcript else "")
        + "\nDescribe the clip. Reply as JSON with keys summary, visual_style, setting, people, genre.")}]
    content += [image_part(f) for f in frames]
    return c.structured([{"role": "user", "content": content}], ClipDescription)


def describe_person(cfg: VLMConfig, crops: list[Path]) -> Optional[str]:
    c = client(cfg)
    if c is None or not crops:
        return None
    content: list[dict] = [{"type": "text", "text": (
        "These crops all show the same person. Describe their appearance in one sentence "
        "(hair colour/style, outfit, notable features) for an image generator. "
        'Reply as JSON: {"description": "..."}')}]
    content += [image_part(p, 384) for p in crops[:3]]
    return c.structured([{"role": "user", "content": content}], PersonDescription).description
