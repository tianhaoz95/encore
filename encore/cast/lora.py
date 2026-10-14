"""Optional: prepare an identity-LoRA dataset per character.

Reference-conditioned editing (Kontext / Qwen-Image-Edit) already preserves
identity reasonably; a small LoRA trained on the clip's face crops makes it
much more robust across angles. Training itself runs with whatever trainer you
use on the Spark (ostris/ai-toolkit, kohya-ss/musubi-tuner, ...); this module
builds the dataset and prints a starting command."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np

from ..core.project import Project


def build_dataset(project: Project, char_id: str, max_images: int = 40, min_side: int = 160) -> Path:
    from PIL import Image

    bible, a = project.bible, project.analysis
    assert bible and a, "run bible first"
    ch = bible.character(char_id)
    if ch is None:
        raise KeyError(char_id)
    emb_file = project.p("cast", ch.id, "embedding.npy")
    E_all = project.p("analysis", "face_embeddings.npy")
    idx = list(range(len(a.faces)))
    if emb_file.exists() and E_all.exists():
        centroid, E = np.load(emb_file), np.load(E_all)
        sims = E @ centroid
        idx = [i for i in np.argsort(-sims) if sims[i] > 0.5]
    out = project.dir("cast", ch.id, "lora_dataset")
    token = f"mre_{ch.id}"
    n = 0
    for i in idx:
        f = a.faces[i]
        src = project.p(f.crop)
        with Image.open(src) as im:
            if min(im.size) < min_side:
                continue
        shutil.copy2(src, out / f"{n:03d}.jpg")
        (out / f"{n:03d}.txt").write_text(f"photo of {token}, {ch.description}".strip(", "))
        n += 1
        if n >= max_images:
            break
    project.write_json(f"cast/{ch.id}/lora_dataset/README.json", {
        "trigger": token, "images": n,
        "suggested": ("ai-toolkit: copy config/examples/train_lora_flux_kontext_24gb.yaml, set "
                      f"datasets[0].folder_path={out}, trigger_word={token}, steps=1500; run `python run.py <cfg>` "
                      "on the Spark, put the .safetensors into ComfyUI/models/loras and set the "
                      f"character's `lora` field to its filename."),
    })
    return out
