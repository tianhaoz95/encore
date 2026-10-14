"""Shot video generation.

Talking shots (lip-synced to our dialogue track):
  worker   - InfiniteTalk / MultiTalk on the Spark (multi-person, long-form)
  comfyui  - any audio-driven workflow (Wan 2.2 S2V, ...) with {{AUDIO}}
  kenburns - slow push-in over the keyframe (no lip sync; dry runs)

Motion shots (b-roll / continuation of the source):
  comfyui  - image-to-video workflow (Wan 2.2 TI2V-5B / I2V-14B, HunyuanVideo-I2V, LTX)
  worker   - same models via their reference repos
  kenburns - fallback

Image-to-video models give ~5 s per run; longer shots are generated as a chain
where each segment starts from the previous segment's last frame."""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Optional

from ..core import media
from ..core.config import VideoConfig, resolve_path
from .comfy import get_comfy
from .worker_client import get_worker

NEGATIVE = ("static, frozen, blurry, low quality, deformed face, distorted hands, extra fingers, "
            "subtitles, text, watermark, jitter, flicker")


def wan_frames(seconds: float, fps: int) -> int:
    """Wan-family models need 4n+1 frames."""
    return max(int(seconds * fps) // 4 * 4 + 1, 5)


class VideoGen:
    def __init__(self, cfg: VideoConfig):
        self.cfg = cfg

    def backend_for(self, kind: str) -> str:
        return self.cfg.talking_backend if kind == "talking" else self.cfg.broll_backend

    # ----------------------------------------------------------- talking --

    def talking(self, image: Path, audio: Path, speaker_tracks: list[Path], prompt: str, out: Path,
                seconds: float, bboxes: Optional[list[list[float]]] = None) -> Path:
        backend = self.backend_for("talking")
        if backend == "worker":
            files = {"image": image, "audio": audio}
            files.update({f"audio_{i + 1}": t for i, t in enumerate(speaker_tracks)})
            params = {"prompt": prompt, "negative": NEGATIVE, "fps": self.cfg.fps, "seconds": seconds,
                      "width": self.cfg.width, "height": self.cfg.height, "num_speakers": len(speaker_tracks),
                      "bboxes": bboxes or []}
            return get_worker(self.cfg.worker_url, self.cfg.timeout).run(
                "talking", self.cfg.talking_engine, params, files, out)
        if backend == "comfyui":
            values = {"PROMPT": prompt, "NEGATIVE": NEGATIVE, "IMAGE": image, "AUDIO": audio,
                      "WIDTH": self.cfg.width, "HEIGHT": self.cfg.height, "FPS": self.cfg.fps,
                      "FRAMES": wan_frames(seconds, self.cfg.fps)}
            return self._comfy(self.cfg.workflows["talking"], values, out)
        if backend == "kenburns":
            return media.still_to_video(image, out, seconds, self.cfg.width, self.cfg.height, self.cfg.fps,
                                        audio=audio, motion="zoom_in")
        raise ValueError(f"unknown talking backend {backend}")

    # ------------------------------------------------------------ motion --

    def motion(self, kind: str, image: Path, prompt: str, out: Path, seconds: float) -> Path:
        backend = self.backend_for(kind)
        if backend == "kenburns":
            return media.still_to_video(image, out, seconds, self.cfg.width, self.cfg.height, self.cfg.fps,
                                        motion=random.choice(["zoom_in", "zoom_out"]))
        n = max(1, math.ceil(seconds / self.cfg.max_clip_seconds - 0.15))
        seg_len = seconds / n
        segs: list[Path] = []
        start = image
        for i in range(n):
            seg = out.with_name(f"{out.stem}_seg{i}.mp4")
            if backend == "comfyui":
                values = {"PROMPT": prompt, "NEGATIVE": NEGATIVE, "IMAGE": start, "WIDTH": self.cfg.width,
                          "HEIGHT": self.cfg.height, "FPS": self.cfg.fps,
                          "FRAMES": wan_frames(seg_len, self.cfg.fps)}
                self._comfy(self.cfg.workflows.get(kind, self.cfg.workflows["broll"]), values, seg)
            elif backend == "worker":
                params = {"prompt": prompt, "negative": NEGATIVE, "fps": self.cfg.fps, "seconds": seg_len,
                          "frames": wan_frames(seg_len, self.cfg.fps), "width": self.cfg.width,
                          "height": self.cfg.height}
                get_worker(self.cfg.worker_url, self.cfg.timeout).run(
                    "i2v", self.cfg.broll_engine, params, {"image": start}, seg)
            else:
                raise ValueError(f"unknown motion backend {backend}")
            segs.append(seg)
            if i < n - 1:
                start = media.extract_last_frame(seg, seg.with_suffix(".last.png"))
        if len(segs) == 1:
            segs[0].replace(out)
        else:
            media.concat_videos(segs, out)
        return out

    def _comfy(self, workflow: str, values: dict, out: Path) -> Path:
        files = get_comfy(self.cfg.comfy_url, self.cfg.timeout).run(
            resolve_path(workflow), values, out.parent / "_comfy", want=("videos", "gifs", "images"))
        vids = [f for f in files if f.suffix.lower() in (".mp4", ".webm", ".mov", ".mkv", ".gif")]
        if not vids:
            raise RuntimeError(f"workflow {workflow} produced no video: {[f.name for f in files]}")
        media.ffmpeg("-i", vids[-1], "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-an", out)
        return out
