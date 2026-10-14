"""Shot boundary detection."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..core.media import _bin


def detect_cuts(video: Path, threshold: float = 0.3) -> list[float]:
    """Return cut timestamps (seconds). PySceneDetect if installed, else ffmpeg's
    scene-change score."""
    try:
        from scenedetect import ContentDetector, detect  # type: ignore

        scenes = detect(str(video), ContentDetector(threshold=threshold * 90))
        return [s[0].get_seconds() for s in scenes[1:]]
    except ImportError:
        pass
    proc = subprocess.run(
        [_bin("ffmpeg"), "-hide_banner", "-i", str(video), "-vf",
         f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
        capture_output=True, text=True)
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", proc.stderr)]


def scene_ranges(video: Path, total: float, min_len: float = 0.8) -> list[tuple[float, float]]:
    cuts = [c for c in detect_cuts(video) if 0 < c < total]
    bounds = [0.0] + cuts + [total]
    ranges: list[tuple[float, float]] = []
    for a, b in zip(bounds, bounds[1:]):
        if ranges and b - a < min_len:
            ranges[-1] = (ranges[-1][0], b)  # merge flashes into the previous shot
        else:
            ranges.append((a, b))
    return ranges or [(0.0, total)]
