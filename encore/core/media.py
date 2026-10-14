"""Thin ffmpeg/ffprobe wrappers. Everything media-related goes through here."""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np

from .schemas import SourceInfo

SR = 24000  # internal dialogue sample rate (most TTS engines output 22.05-24 kHz)


class MediaError(RuntimeError):
    pass


def _bin(name: str) -> str:
    b = shutil.which(name)
    if not b:
        raise MediaError(f"{name} not found on PATH (brew install ffmpeg / apt install ffmpeg)")
    return b


def run(args: Sequence[str], quiet: bool = True) -> str:
    cmd = [str(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"command failed ({proc.returncode}): {' '.join(cmd[:12])} ...\n{proc.stderr[-2000:]}")
    return proc.stdout


def ffmpeg(*args, quiet: bool = True) -> str:
    return run([_bin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args], quiet)


def probe(path: Path) -> dict:
    out = run([_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_format",
               "-show_streams", str(path)])
    return json.loads(out)


def source_info(path: Path) -> SourceInfo:
    info = probe(path)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise MediaError(f"{path} has no video stream")
    num, _, den = v.get("avg_frame_rate", "25/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 25.0
    dur = float(info["format"].get("duration") or v.get("duration") or 0)
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    return SourceInfo(path=str(path), duration=dur, width=int(v["width"]), height=int(v["height"]),
                      fps=fps or 25.0, has_audio=has_audio)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def extract_frame(video: Path, t: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-ss", f"{max(t, 0):.3f}", "-i", video, "-frames:v", "1", "-q:v", "2", out)
    return out


def extract_last_frame(video: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-sseof", "-0.5", "-i", video, "-update", "1", "-q:v", "2", out)
    return out


def extract_audio(video: Path, out: Path, sr: int = 44100, mono: bool = False) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-i", video, "-vn", "-ac", "1" if mono else "2", "-ar", str(sr), "-c:a", "pcm_s16le", out)
    return out


def cut_audio(src: Path, start: float, end: float, out: Path, sr: int = SR) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src, "-ac", "1", "-ar", str(sr),
           "-c:a", "pcm_s16le", out)
    return out


def to_wav(src: Path, out: Path, sr: int = SR) -> Path:
    ffmpeg("-i", src, "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", out)
    return out


# ---- raw wav io (mono int16), used to assemble dialogue tracks sample-accurately

def read_wav(path: Path, sr: int = SR) -> np.ndarray:
    path = Path(path)
    with wave.open(str(path), "rb") as w:
        ok = w.getframerate() == sr and w.getnchannels() == 1 and w.getsampwidth() == 2
    if not ok:
        tmp = path.with_name(path.stem + f".{sr}.wav")
        to_wav(path, tmp, sr)
        path = tmp
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0


def write_wav(path: Path, samples: np.ndarray, sr: int = SR) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def silence(seconds: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(round(seconds * sr)), dtype=np.float32)


def trim_silence(x: np.ndarray, thresh: float = 0.01, pad: float = 0.05, sr: int = SR) -> np.ndarray:
    idx = np.where(np.abs(x) > thresh)[0]
    if idx.size == 0:
        return x
    p = int(pad * sr)
    return x[max(idx[0] - p, 0): idx[-1] + p]


# ---- video

def still_to_video(image: Path, out: Path, seconds: float, width: int, height: int, fps: int,
                   audio: Optional[Path] = None, motion: str = "zoom_in") -> Path:
    """Ken Burns move over a still: the zero-GPU fallback for every video stage."""
    frames = max(int(round(seconds * fps)), 1)
    z = {"zoom_in": "min(1+0.0015*on,1.25)", "zoom_out": "max(1.25-0.0015*on,1)",
         "static": "1"}.get(motion, "min(1+0.0015*on,1.25)")
    vf = (f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
          f"crop={width * 2}:{height * 2},"
          f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps},"
          f"format=yuv420p")
    args: list = ["-loop", "1", "-i", image]
    if audio:
        args += ["-i", audio]
    args += ["-vf", vf, "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
    if audio:
        args += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(*args, out)
    return out


def normalize_video(src: Path, out: Path, width: int, height: int, fps: int,
                    extra_vf: Optional[str] = None, audio: Optional[Path] = None,
                    min_seconds: Optional[float] = None) -> Path:
    """Conform any clip to the output format; replaces/adds audio if given.

    If the clip is shorter than the audio, the last frame is held (tpad) so
    dialogue is never cut off."""
    vf = [f"scale={width}:{height}:force_original_aspect_ratio=decrease",
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black", f"fps={fps}", "setsar=1"]
    if extra_vf:
        vf.append(extra_vf)
    target = min_seconds
    if audio is not None:
        target = max(target or 0, duration(audio))
    if target:
        vlen = duration(src)
        if vlen < target:
            vf.append(f"tpad=stop_mode=clone:stop_duration={target - vlen + 0.1:.3f}")
    vf.append("format=yuv420p")
    args: list = ["-i", src]
    if audio is not None:
        args += ["-i", audio, "-map", "0:v:0", "-map", "1:a:0"]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0"]
        has_audio = any(s["codec_type"] == "audio" for s in probe(src)["streams"])
        args += ["-map", "0:a:0" if has_audio else "1:a:0"]
    args += ["-vf", ",".join(vf), "-c:v", "libx264", "-preset", "fast", "-crf", "16",
             "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k"]
    if target:
        args += ["-t", f"{target:.3f}"]
    else:
        args += ["-shortest"]
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(*args, out)
    return out


def concat_videos(clips: Iterable[Path], out: Path) -> Path:
    clips = list(clips)
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{Path(c).resolve()}'\n" for c in clips))
    ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out)
    return out


def concat_with_crossfade(clips: list[Path], out: Path, fade: float) -> Path:
    if fade <= 0 or len(clips) < 2:
        return concat_videos(clips, out)
    args: list = []
    for c in clips:
        args += ["-i", c]
    durs = [duration(c) for c in clips]
    vf, af = [], []
    prev_v, prev_a, offset = "0:v", "0:a", 0.0
    for i in range(1, len(clips)):
        offset += durs[i - 1] - fade
        vf.append(f"[{prev_v}][{i}:v]xfade=transition=fade:duration={fade}:offset={offset:.3f}[v{i}]")
        af.append(f"[{prev_a}][{i}:a]acrossfade=d={fade}[a{i}]")
        prev_v, prev_a = f"v{i}", f"a{i}"
    graph = ";".join(vf + af)
    ffmpeg(*args, "-filter_complex", graph, "-map", f"[{prev_v}]", "-map", f"[{prev_a}]",
           "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-movflags", "+faststart", out)
    return out


def sample_frames(video: Path, n: int, out_dir: Path, start: float = 0.0,
                  end: Optional[float] = None) -> list[Path]:
    end = end if end is not None else duration(video)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(n):
        t = start + (end - start) * (i + 0.5) / n
        frames.append(extract_frame(video, t, out_dir / f"f{i:03d}.jpg"))
    return frames
