"""Engines the GPU worker can run. Each engine handles one task type:

  tts      text (+ reference voice)      -> wav
  talking  image + dialogue audio track(s) -> lip-synced mp4
  i2v      image + prompt                 -> mp4

Built-in types:
  chatterbox    Resemble Chatterbox (multilingual incl. Korean), python API
  f5            F5-TTS, python API
  infinitetalk  MeiGen InfiniteTalk / MultiTalk repo, via its generate script
  command       any CLI, configured as an argv template (CosyVoice, Wan2.2, HunyuanVideo, ...)
  say           macOS `say` (testing the worker on a Mac)
  kenburns      ffmpeg still-image motion (testing without a GPU)
"""

from __future__ import annotations

import gc
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

EMOTION_EXAGGERATION = {"excited": 0.75, "happy": 0.65, "laughing": 0.8, "emotional": 0.7, "neutral": 0.5,
                        "calm": 0.35, "serious": 0.4, "sad": 0.45}


class Engine:
    task = "tts"
    gpu = True  # GPU engines are unloaded when another GPU engine loads

    def __init__(self, name: str, conf: dict):
        self.name = name
        self.conf = conf
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def run(self, params: dict, files: dict[str, Path], out: Path) -> Path:  # pragma: no cover
        raise NotImplementedError

    def _preset_voice(self, params: dict) -> Optional[Path]:
        """No reference audio (e.g. a 'host' who isn't in the clip): use a stock voice."""
        d = self.conf.get("voices_dir")
        if not d:
            return None
        wavs = sorted(Path(d).expanduser().glob("*.wav"))
        return wavs[int(params.get("voice_index", 0)) % len(wavs)] if wavs else None


# ------------------------------------------------------------------ TTS --

class ChatterboxEngine(Engine):
    def load(self):
        import torch

        device = self.conf.get("device") or ("cuda" if torch.cuda.is_available() else
                                              "mps" if torch.backends.mps.is_available() else "cpu")
        if self.conf.get("multilingual", True):
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # type: ignore

            self.model = ChatterboxMultilingualTTS.from_pretrained(device=device)
            self.multi = True
        else:
            from chatterbox.tts import ChatterboxTTS  # type: ignore

            self.model = ChatterboxTTS.from_pretrained(device=device)
            self.multi = False
        self.loaded = True

    def unload(self):
        self.model = None
        _free_gpu()
        self.loaded = False

    def run(self, params, files, out):
        import torchaudio as ta

        ref = files.get("ref_audio") or self._preset_voice(params)
        kw = {"exaggeration": EMOTION_EXAGGERATION.get(params.get("emotion", "neutral"), 0.5),
              "cfg_weight": float(self.conf.get("cfg_weight", 0.5))}
        if ref:
            kw["audio_prompt_path"] = str(ref)
        if self.multi:
            kw["language_id"] = (params.get("language") or "en").split("-")[0]
        wav = self.model.generate(params["text"], **kw)
        out = out.with_suffix(".wav")
        ta.save(str(out), wav, self.model.sr)
        return out


class F5Engine(Engine):
    def load(self):
        from f5_tts.api import F5TTS  # type: ignore

        self.model = F5TTS(model=self.conf.get("model", "F5TTS_v1_Base"))
        self.loaded = True

    def unload(self):
        self.model = None
        _free_gpu()
        self.loaded = False

    def run(self, params, files, out):
        ref = files.get("ref_audio") or self._preset_voice(params)
        if not ref:
            raise ValueError("F5-TTS needs a reference voice (upload one or set voices_dir)")
        out = out.with_suffix(".wav")
        self.model.infer(ref_file=str(ref), ref_text=params.get("ref_text", ""), gen_text=params["text"],
                         file_wave=str(out))
        return out


class SayEngine(Engine):
    gpu = False

    def run(self, params, files, out):
        out = out.with_suffix(".aiff")
        subprocess.run(["say", "-o", str(out), params["text"]], check=True)
        return out


# --------------------------------------------------------------- video ---

class InfiniteTalkEngine(Engine):
    """Wraps https://github.com/MeiGen-AI/InfiniteTalk (also works for MultiTalk
    by pointing `script` at generate_multitalk.py)."""

    task = "talking"

    def run(self, params, files, out):
        c = self.conf
        repo = Path(c["repo"])
        n = int(params.get("num_speakers") or 0)
        tracks = [files[f"audio_{i + 1}"] for i in range(n) if f"audio_{i + 1}" in files] or [files["audio"]]
        job = {"prompt": params.get("prompt", ""), "cond_video": str(files["image"]),
               "cond_audio": {f"person{i + 1}": str(t) for i, t in enumerate(tracks)}}
        if len(tracks) > 1:
            job["audio_type"] = "para"  # tracks are already time-aligned (silence while others talk)
            if params.get("bboxes"):
                job["bbox"] = {f"person{i + 1}": b for i, b in enumerate(params["bboxes"])}
        jf = out.with_suffix(".input.json")
        jf.write_text(json.dumps(job))
        weights = c["multi_weights"] if len(tracks) > 1 else c["single_weights"]
        save = out.with_suffix("")  # the script appends .mp4
        argv = [c.get("python", sys.executable), c.get("script", "generate_infinitetalk.py"),
                "--ckpt_dir", c["ckpt_dir"], "--wav2vec_dir", c["wav2vec_dir"],
                "--infinitetalk_dir", weights, "--input_json", str(jf),
                "--size", c.get("size", "infinitetalk-480"), "--sample_steps", str(c.get("sample_steps", 40)),
                "--mode", "streaming", "--motion_frame", str(c.get("motion_frame", 9)),
                "--save_file", str(save)] + [str(a) for a in c.get("extra_args", [])]
        _run(argv, cwd=repo)
        result = save.with_suffix(".mp4")
        if not result.exists():
            raise FileNotFoundError(f"InfiniteTalk produced no {result}")
        return result


class CommandEngine(Engine):
    """Any CLI. `cmd` is an argv list (or string) with {placeholders}:
    {python} {out} {workdir} {text} {text_file} {ref_audio} {ref_text} {language} {emotion}
    {image} {audio} {audio_1}.. {prompt} {negative} {frames} {fps} {width} {height} {seconds}
    The command must write its result to {out} (or set `output_glob`)."""

    def __init__(self, name, conf):
        super().__init__(name, conf)
        self.task = conf.get("task", "tts")
        self.gpu = conf.get("gpu", True)

    def run(self, params, files, out):
        c = self.conf
        out = out.with_suffix(c.get("output_ext", out.suffix))
        workdir = out.parent
        text_file = workdir / "text.txt"
        text_file.write_text(params.get("text", ""))
        values = {k: v for k, v in params.items() if not isinstance(v, (list, dict))}
        values.update({k: str(v) for k, v in files.items()})
        values.update(python=c.get("python", sys.executable), out=str(out), workdir=str(workdir),
                      text_file=str(text_file))
        values.setdefault("ref_audio", str(self._preset_voice(params) or ""))
        cmd = c["cmd"]
        argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
        argv = [str(a).format(**values) for a in argv]
        _run(argv, cwd=Path(c["cwd"]) if c.get("cwd") else None, env=c.get("env"))
        if c.get("output_glob"):
            hits = sorted(Path(c.get("cwd", workdir)).glob(c["output_glob"]), key=lambda p: p.stat().st_mtime)
            if not hits:
                raise FileNotFoundError(f"{self.name}: nothing matched {c['output_glob']}")
            shutil.move(str(hits[-1]), out)
        if not out.exists():
            raise FileNotFoundError(f"{self.name}: command did not create {out}")
        return out


class KenBurnsEngine(Engine):
    gpu = False

    def __init__(self, name, conf):
        super().__init__(name, conf)
        self.task = conf.get("task", "i2v")

    def run(self, params, files, out):
        from ..core.media import still_to_video

        return still_to_video(files["image"], out.with_suffix(".mp4"), float(params.get("seconds", 5)),
                              int(params.get("width", 1280)), int(params.get("height", 720)),
                              int(params.get("fps", 24)), audio=files.get("audio"))


TYPES = {"chatterbox": ChatterboxEngine, "f5": F5Engine, "say": SayEngine, "infinitetalk": InfiniteTalkEngine,
         "command": CommandEngine, "kenburns": KenBurnsEngine}

TASK_OF = {"chatterbox": "tts", "f5": "tts", "say": "tts", "infinitetalk": "talking"}


def build(name: str, conf: dict) -> Engine:
    eng = TYPES[conf["type"]](name, conf)
    if conf["type"] in TASK_OF:
        eng.task = TASK_OF[conf["type"]]
    return eng


def _run(argv: list[str], cwd: Optional[Path] = None, env: Optional[dict] = None) -> None:
    import os

    e = dict(os.environ, **(env or {}))
    proc = subprocess.run(argv, cwd=cwd, env=e, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(argv[:4])} ... exited {proc.returncode}:\n{proc.stderr[-3000:]}")


def _free_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass
