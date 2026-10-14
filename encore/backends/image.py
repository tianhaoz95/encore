"""Keyframe image generation.

  comfyui - reference-conditioned edit model (FLUX.1 Kontext dev, Qwen-Image-Edit, ...)
            given a reference sheet (face crops / master frame) + prompt
  still   - PIL compositor: the reference faces laid out over a backdrop. No GPU;
            used for dry runs and as the input to the Ken Burns video fallback."""

from __future__ import annotations

import random
import shutil
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from ..core.config import ImageConfig, resolve_path
from .comfy import get_comfy


def reference_sheet(images: list[Path], out: Path, height: int = 768) -> Path:
    """Stitch reference images side by side (what Kontext-style editors expect
    when you want several identities in one frame)."""
    tiles = []
    for p in images:
        im = Image.open(p).convert("RGB")
        w = int(im.width * height / im.height)
        tiles.append(im.resize((max(w, 1), height), Image.LANCZOS))
    if not tiles:
        raise ValueError("reference_sheet needs at least one image")
    sheet = Image.new("RGB", (sum(t.width for t in tiles), height), "white")
    x = 0
    for t in tiles:
        sheet.paste(t, (x, 0))
        x += t.width
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


class ImageGen:
    def __init__(self, cfg: ImageConfig):
        self.cfg = cfg

    @property
    def is_real(self) -> bool:
        return self.cfg.backend != "still"

    def generate(self, prompt: str, refs: list[Path], out: Path, backdrop: Optional[Path] = None,
                 seed: Optional[int] = None, lora: Optional[str] = None, label: str = "") -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.cfg.backend == "comfyui":
            sheet = reference_sheet(refs or ([backdrop] if backdrop else []), out.with_name(out.stem + "_ref.png"))
            values = {"PROMPT": prompt, "NEGATIVE": "blurry, deformed face, extra limbs, text, watermark",
                      "IMAGE": sheet, "WIDTH": self.cfg.width, "HEIGHT": self.cfg.height,
                      "STEPS": self.cfg.steps, "SEED": seed if seed is not None else random.randint(0, 2**31),
                      "LORA": lora or "none.safetensors"}
            files = get_comfy(self.cfg.url, self.cfg.timeout).run(
                resolve_path(self.cfg.workflow), values, out.parent / "_comfy", want=("images",))
            Image.open(files[-1]).convert("RGB").save(out)
            return out
        if self.cfg.backend == "still":
            return compose_still(refs, out, self.cfg.width, self.cfg.height, backdrop, label or prompt)
        raise ValueError(f"unknown image backend {self.cfg.backend}")


def compose_still(refs: list[Path], out: Path, width: int, height: int,
                  backdrop: Optional[Path] = None, caption: str = "") -> Path:
    if backdrop and Path(backdrop).exists():
        bg = ImageOps.fit(Image.open(backdrop).convert("RGB"), (width, height)).filter(ImageFilter.GaussianBlur(18))
    else:
        bg = Image.new("RGB", (width, height), (24, 24, 32))
    bd = Path(backdrop).resolve() if backdrop else None
    refs = [p for p in refs if p and Path(p).exists() and Path(p).resolve() != bd]
    if refs:
        n = len(refs)
        side = int(min(height * 0.62, width / n * 0.85))
        gap = (width - n * side) / (n + 1)
        for i, p in enumerate(refs):
            face = ImageOps.fit(Image.open(p).convert("RGB"), (side, side))
            bg.paste(face, (int(gap + i * (side + gap)), int(height * 0.14)))
    if caption:
        d = ImageDraw.Draw(bg)
        try:
            font = ImageFont.load_default(size=max(height // 30, 12))
        except TypeError:
            font = ImageFont.load_default()
        d.rectangle([0, height - height // 9, width, height], fill=(0, 0, 0))
        d.text((20, height - height // 11), caption[:140], fill=(235, 235, 235), font=font)
    bg.save(out)
    return out


def copy_image(src: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".png":
        shutil.copy2(src, out)
    else:
        Image.open(src).convert("RGB").save(out)
    return out
