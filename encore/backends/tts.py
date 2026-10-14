"""Text-to-speech with voice cloning.

  worker  - encore worker (Spark/Mac) running Chatterbox / F5-TTS / CosyVoice / ...
  say     - macOS built-in voices (on-device, no cloning) — dry runs on a Mac
  silent  - silence sized to the text — pipeline testing anywhere"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..core import media
from ..core.config import TTSConfig
from .worker_client import get_worker


class TTS:
    def __init__(self, cfg: TTSConfig):
        self.cfg = cfg
        backend = cfg.backend
        if backend == "say" and (platform.system() != "Darwin" or not shutil.which("say")):
            backend = "silent"
        self.backend = backend

    def synthesize(self, text: str, out: Path, language: str = "en", ref_audio: Optional[Path] = None,
                   ref_text: Optional[str] = None, emotion: str = "neutral",
                   voice_index: int = 0, voice_preset: Optional[str] = None) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.backend == "worker":
            params = {"text": text, "language": language, "ref_text": ref_text or "", "emotion": emotion,
                      "voice_preset": voice_preset or "", "voice_index": voice_index}
            tmp = out.with_suffix(".raw")
            get_worker(self.cfg.url, self.cfg.timeout).run(
                "tts", self.cfg.engine, params, {"ref_audio": ref_audio} if ref_audio else {}, tmp)
            media.to_wav(tmp, out)
            tmp.unlink(missing_ok=True)
            return out
        if self.backend == "say":
            voice = voice_preset or _say_voice(language, voice_index)
            aiff = out.with_suffix(".aiff")
            cmd = ["say", "-o", str(aiff)] + (["-v", voice] if voice else []) + [text]
            subprocess.run(cmd, check=True, capture_output=True)
            media.to_wav(aiff, out)
            aiff.unlink(missing_ok=True)
            return out
        if self.backend == "silent":
            words = max(len(re.findall(r"\w+", text)), 1)
            return media.write_wav(out, media.silence(0.4 + words / 2.6))
        raise ValueError(f"unknown TTS backend {self.backend}")


@lru_cache(maxsize=1)
def _say_voices() -> list[tuple[str, str]]:
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return []
    voices = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s+([a-z]{2}[_-][A-Z]{2})\s+#", line)
        if m and "(" not in m.group(1):  # skip "Eddy (English (US))" style duplicates
            voices.append((m.group(1).strip(), m.group(2)))
    return voices


def _say_voice(language: str, index: int) -> Optional[str]:
    lang = language.split("-")[0].lower()
    matches = [v for v, loc in _say_voices() if loc.lower().startswith(lang)]
    return matches[index % len(matches)] if matches else None
