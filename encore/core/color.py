"""Colour matching: grade generated shots toward the source clip's look.

We compute Reinhard LAB statistics of source and shot, bake the transfer into a
3D LUT (.cube) and let ffmpeg's lut3d apply it — fast, no per-frame Python."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def lab_stats(images: list[Path]) -> dict:
    pix = []
    for p in images:
        img = cv2.imread(str(p))
        if img is None:
            continue
        img = cv2.resize(img, (256, int(256 * img.shape[0] / img.shape[1])))
        lab = cv2.cvtColor(img.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
        pix.append(lab.reshape(-1, 3))
    if not pix:
        return {"mean": [50.0, 0.0, 0.0], "std": [20.0, 10.0, 10.0]}
    allp = np.concatenate(pix)
    return {"mean": allp.mean(0).tolist(), "std": (allp.std(0) + 1e-3).tolist()}


def write_transfer_lut(src_stats: dict, dst_stats: dict, out: Path, size: int = 33,
                       strength: float = 0.7) -> Path:
    """LUT mapping colours with `src_stats` (the generated shot) toward `dst_stats` (the source)."""
    g = np.linspace(0, 1, size, dtype=np.float32)
    # .cube ordering: red changes fastest, then green, then blue
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    rgb = np.stack([r, gg, b], -1).reshape(-1, 1, 3)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    ms, ss = np.array(src_stats["mean"]), np.array(src_stats["std"])
    md, sd = np.array(dst_stats["mean"]), np.array(dst_stats["std"])
    # clamp the scale so we never blow out a nearly flat shot
    scale = np.clip(sd / ss, 0.5, 2.0)
    moved = (lab - ms) * scale + md
    lab2 = lab + (moved - lab) * strength
    out_rgb = np.clip(cv2.cvtColor(lab2.astype(np.float32), cv2.COLOR_LAB2RGB), 0, 1).reshape(-1, 3)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        f.write(f"TITLE \"encore match\"\nLUT_3D_SIZE {size}\n")
        for v in out_rgb:
            f.write(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
    return out
