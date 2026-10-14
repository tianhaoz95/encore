"""Stage 7 — conform, grade, mix and assemble the final film."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from ..core import media
from ..core.color import lab_stats, write_transfer_lut
from ..core.config import Config
from ..core.project import Project


def run(project: Project, cfg: Config, **_) -> Path:
    script, a, bible = project.script, project.analysis, project.bible
    assert script and a and bible, "run shoot first"
    e = cfg.edit
    parts_dir = project.dir("output", "parts")
    parts: list[Path] = []
    offsets: list[tuple[str, float]] = []
    t = 0.0

    if e.prepend_source:
        src_part = media.normalize_video(project.source, parts_dir / "000_source.mp4", e.width, e.height, e.fps)
        parts.append(src_part)
        t += media.duration(src_part)
    gen_start = t

    for i, shot in enumerate(script.shots, 1):
        vid = project.shot_video(shot.id)
        if not vid.exists():
            raise FileNotFoundError(f"missing shot video {shot.id}; run shoot first")
        vf = []
        if e.color_match and a.color_stats:
            frames = media.sample_frames(vid, 3, project.dir("output", "tmp", shot.id))
            lut = write_transfer_lut(lab_stats(frames), a.color_stats, project.p("output", "tmp", f"{shot.id}.cube"))
            vf.append(f"lut3d=file='{lut}'")
        if e.grain:
            vf.append(f"noise=alls={int(e.grain)}:allf=t")
        audio = project.shot_audio(shot.id)
        part = media.normalize_video(vid, parts_dir / f"{i:03d}_{shot.id}.mp4", e.width, e.height, e.fps,
                                     extra_vf=",".join(vf) or None, audio=audio if audio.exists() else None,
                                     min_seconds=shot.duration)
        parts.append(part)
        offsets.append((shot.id, t))
        t += media.duration(part)

    joined = project.p("output", "_joined.mp4")
    if e.crossfade > 0:
        media.concat_with_crossfade(parts, joined, e.crossfade)
    else:
        media.concat_videos(parts, joined)

    srt = _write_srt(project, offsets, {c.id: c.name for c in bible.characters}, script.extra_voices)
    final = project.p("output", "final.mp4")
    _finish(project, cfg, joined, final, srt, gen_start)
    project.log(f"edit: wrote {project.rel(final)} ({media.duration(final):.1f}s)")
    return final


def _finish(project: Project, cfg: Config, joined: Path, final: Path, srt: Optional[Path], gen_start: float) -> None:
    e, a = cfg.edit, project.analysis
    inputs: list = ["-i", joined]
    vchain, achain = "[0:v]null[v0]", "[0:a]anull[a0]"
    filters = []
    vlast, alast = "v0", "a0"
    filters += [vchain, achain]
    n = 1
    if e.watermark:
        wm = _watermark(project.p("output", "tmp", "watermark.png"), e.watermark_text, e.height)
        inputs += ["-i", wm]
        filters.append(f"[{vlast}][{n}:v]overlay=W-w-24:H-h-24[v1]")
        vlast, n = "v1", n + 1
    if srt and e.subtitles == "burn":
        filters.append(f"[{vlast}]subtitles='{srt}'[v2]")
        vlast = "v2"
    inst = project.p(a.instrumental_path) if a and a.instrumental_path else None
    if e.music_bed and inst and inst.exists():
        inputs += ["-stream_loop", "-1", "-i", inst]
        delay = int(gen_start * 1000)
        filters += [
            f"[{alast}]asplit=2[dlg][sc]",
            f"[{n}:a]volume={e.music_gain_db}dB,adelay={delay}|{delay},aformat=channel_layouts=stereo[mus]",
            "[mus][sc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[duck]",
            "[dlg][duck]amix=inputs=2:duration=first:normalize=0[a1]",
        ]
        alast, n = "a1", n + 1
    filters.append(f"[{alast}]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
    media.ffmpeg(*inputs, "-filter_complex", ";".join(filters), "-map", f"[{vlast}]", "-map", "[aout]",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
                 "-ar", "48000", "-shortest", "-movflags", "+faststart",
                 "-metadata", "comment=AI-generated with encore (on-device). Contains synthetic media.",
                 final)


def _watermark(out: Path, text: str, height: int) -> Path:
    size = max(height // 40, 12)
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:
        font = ImageFont.load_default()
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    l, tp, r, b = probe.textbbox((0, 0), text, font=font)
    img = Image.new("RGBA", (r - l + 16, b - tp + 10), (0, 0, 0, 90))
    ImageDraw.Draw(img).text((8 - l, 5 - tp), text, fill=(255, 255, 255, 200), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def _fmt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(project: Project, offsets: list[tuple[str, float]], names: dict[str, str],
               extra: dict[str, str]) -> Optional[Path]:
    entries = []
    for shot_id, off in offsets:
        timing = project.read_json(f"audio/{shot_id}.json", {}) or {}
        for ln in timing.get("lines", []):
            who = names.get(ln["speaker"], ln["speaker"].replace("_", " ").title())
            entries.append((off + ln["start"], off + ln["end"], f"{who}: {ln['text']}"))
    if not entries:
        return None
    out = project.p("output", "final.srt")
    out.write_text("\n".join(f"{i}\n{_fmt(a)} --> {_fmt(b)}\n{txt}\n" for i, (a, b, txt) in enumerate(entries, 1)))
    return out
