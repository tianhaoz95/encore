"""Audio understanding: stem separation, speech recognition, diarization.

Concert footage is mostly music, so we separate vocals first (Demucs) and run
ASR / voice-reference extraction on the vocal stem only."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from ..core.config import ASRConfig, DiarizationConfig, SeparationConfig
from ..core.schemas import TranscriptSegment


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


# ------------------------------------------------------------ separation --

def separate_vocals(audio: Path, out_dir: Path, cfg: SeparationConfig) -> tuple[Optional[Path], Optional[Path]]:
    """Returns (vocals, instrumental) or (None, None) if separation is unavailable."""
    backend = cfg.backend
    if backend == "none" or (backend == "auto" and not _has("demucs")):
        return None, None
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", cfg.model,
                    "-o", str(out_dir), str(audio)], check=True, capture_output=True)
    stem_dir = out_dir / cfg.model / audio.stem
    vocals, inst = stem_dir / "vocals.wav", stem_dir / "no_vocals.wav"
    v_dst, i_dst = out_dir / "vocals.wav", out_dir / "instrumental.wav"
    shutil.move(vocals, v_dst)
    shutil.move(inst, i_dst)
    shutil.rmtree(out_dir / cfg.model, ignore_errors=True)
    return v_dst, i_dst


# ------------------------------------------------------------------- ASR --

def _pick_asr(backend: str) -> str:
    if backend != "auto":
        return backend
    if platform.system() == "Darwin" and platform.machine() == "arm64" and _has("mlx_whisper"):
        return "mlx-whisper"
    if _has("faster_whisper"):
        return "faster-whisper"
    return "none"


_MLX_REPOS = {
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "tiny": "mlx-community/whisper-tiny",
}


def transcribe(audio: Path, cfg: ASRConfig) -> tuple[list[TranscriptSegment], Optional[str]]:
    """Returns (segments, detected_language)."""
    backend = _pick_asr(cfg.backend)
    if backend == "none":
        return [], cfg.language
    if backend == "mlx-whisper":
        import mlx_whisper  # type: ignore

        repo = _MLX_REPOS.get(cfg.model, cfg.model)
        res = mlx_whisper.transcribe(str(audio), path_or_hf_repo=repo, language=cfg.language,
                                     condition_on_previous_text=False)
        segs = [TranscriptSegment(start=s["start"], end=s["end"], text=s["text"].strip())
                for s in res.get("segments", []) if s["text"].strip()]
        return segs, res.get("language")
    if backend == "faster-whisper":
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(cfg.model, device="auto", compute_type="auto")
        it, info = model.transcribe(str(audio), language=cfg.language, vad_filter=True)
        segs = [TranscriptSegment(start=s.start, end=s.end, text=s.text.strip()) for s in it if s.text.strip()]
        return segs, info.language
    raise ValueError(f"unknown ASR backend {backend}")


# ----------------------------------------------------------- diarization --

def diarize(audio: Path, segments: list[TranscriptSegment], cfg: DiarizationConfig) -> list[TranscriptSegment]:
    """Label each transcript segment with a speaker. No-op if pyannote is absent."""
    if not segments or cfg.backend == "none" or (cfg.backend == "auto" and not _has("pyannote.audio")):
        return segments
    from pyannote.audio import Pipeline  # type: ignore

    pipe = Pipeline.from_pretrained(cfg.model, use_auth_token=os.environ.get(cfg.hf_token_env))
    try:
        import torch

        if torch.cuda.is_available():
            pipe.to(torch.device("cuda"))
        elif torch.backends.mps.is_available():
            pipe.to(torch.device("mps"))
    except Exception:
        pass
    turns = [(t.start, t.end, spk) for t, _, spk in pipe(str(audio)).itertracks(yield_label=True)]
    out = []
    for seg in segments:
        overlap: dict[str, float] = {}
        for a, b, spk in turns:
            o = min(b, seg.end) - max(a, seg.start)
            if o > 0:
                overlap[spk] = overlap.get(spk, 0) + o
        out.append(seg.model_copy(update={"speaker": max(overlap, key=overlap.get) if overlap else None}))
    return out
