"""encore command line."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import pipeline
from .core.config import Config, apply_overrides, load_config
from .core.project import Project

app = typer.Typer(add_completion=False, help="Extend a movie clip with on-device AI.")
console = Console()

ConfigOpt = typer.Option(None, "--config", "-c", help="config.yaml (default ./config.yaml or $ENCORE_CONFIG)")
SetOpt = typer.Option(None, "--set", "-s", help="override config, e.g. -s tts.backend=say")


def _cfg(config: Optional[Path], overrides: Optional[List[str]]) -> Config:
    return apply_overrides(load_config(config), overrides or [])


def _project(cfg: Config, name: str) -> Project:
    p = Path(name)
    if not (p / "project.json").exists():
        p = Path(cfg.projects_dir) / name
    if not (p / "project.json").exists():
        raise typer.BadParameter(f"no project {name}")
    return Project(p)


@app.command()
def new(clip: Path = typer.Argument(..., exists=True), prompt: str = typer.Argument(...),
        name: Optional[str] = None, seconds: int = typer.Option(60, help="target length of the new footage"),
        language: Optional[str] = typer.Option(None, help="dialogue language, e.g. ko, en"),
        names: Optional[str] = typer.Option(None, help="comma-separated names for detected people, in order"),
        config: Optional[Path] = ConfigOpt, set_: Optional[List[str]] = SetOpt):
    """Create a project from a clip and a text request."""
    cfg = _cfg(config, set_)
    opts = {"target_seconds": seconds}
    if language:
        opts["language"] = language
    if names:
        opts["names"] = [n.strip() for n in names.split(",") if n.strip()]
    proj = Project.create(Path(cfg.projects_dir), clip, prompt, name, opts)
    console.print(f"created [bold]{proj.meta.name}[/] at {proj.path}")


@app.command()
def run(name: str, from_: Optional[str] = typer.Option(None, "--from"), until: Optional[str] = None,
        only: Optional[str] = None, shots: Optional[str] = typer.Option(None, help="comma-separated shot ids"),
        stages: Optional[str] = typer.Option(None, help="explicit comma-separated stages, e.g. voices,shoot,edit"),
        force: bool = False, resume: bool = typer.Option(True, help="start at the first unfinished stage"),
        config: Optional[Path] = ConfigOpt, set_: Optional[List[str]] = SetOpt):
    """Run pipeline stages (analyze, bible, script, voices, keyframes, shoot, edit)."""
    cfg = _cfg(config, set_)
    proj = _project(cfg, name)
    if from_ is None and only is None and stages is None and resume and not shots:
        from_ = pipeline.first_incomplete(proj)
        if from_ is None:
            console.print("all stages done (use --from STAGE to redo)")
            return
    pipeline.run(proj, cfg, from_stage=from_, until=until, only=only,
                 shots=shots.split(",") if shots else None, force=force,
                 stages=stages.split(",") if stages else None,
                 on_stage=lambda s, st: console.print(f"[cyan]{s}[/] {st}"))
    final = proj.p("output", "final.mp4")
    if final.exists():
        console.print(f"[green]output:[/] {final}")


@app.command()
def status(name: str, config: Optional[Path] = ConfigOpt):
    """Show stage status, cast and shot list."""
    cfg = _cfg(config, None)
    proj = _project(cfg, name)
    meta = proj.meta
    console.print(f"[bold]{meta.name}[/]  prompt: {meta.prompt}")
    for s, st in meta.stages.items():
        console.print(f"  {s:10s} {st.status}" + (f"  [red]{st.error}[/]" if st.error else ""))
    if proj.bible:
        for c in proj.bible.characters:
            console.print(f"  cast {c.id}: {c.name}  refs={len(c.face_refs)} voice={'yes' if c.voice_ref else 'no'}"
                          f"  {c.description[:60]}")
    if proj.script:
        t = Table("id", "kind", "framing", "chars", "dur", "lines")
        for sh in proj.script.shots:
            t.add_row(sh.id, sh.kind.value, sh.framing.value, ",".join(sh.characters), f"{sh.duration:.1f}",
                      " / ".join(f"{l.speaker}: {l.text}" for l in sh.lines)[:80])
        console.print(t)


@app.command("list")
def list_(config: Optional[Path] = ConfigOpt):
    cfg = _cfg(config, None)
    for p in Project.list(Path(cfg.projects_dir)):
        m = p.meta
        done = sum(1 for s in m.stages.values() if s.status == "done")
        console.print(f"{m.name:40s} {done}/{len(m.stages)} stages  {m.prompt[:50]}")


@app.command()
def rename(name: str, char_id: str, new_name: str, config: Optional[Path] = ConfigOpt):
    """Give a detected character a real name (used by the script writer)."""
    cfg = _cfg(config, None)
    proj = _project(cfg, name)
    b = proj.bible
    ch = b.character(char_id) if b else None
    if not ch:
        raise typer.BadParameter(char_id)
    ch.name = new_name
    proj.save_bible(b)
    console.print(f"{char_id} -> {new_name}")


@app.command()
def revise(name: str, instruction: str, config: Optional[Path] = ConfigOpt, set_: Optional[List[str]] = SetOpt):
    """Edit the script with a natural-language instruction."""
    from .write.scriptwriter import revise_script

    cfg = _cfg(config, set_)
    proj = _project(cfg, name)
    proj.save_script(revise_script(cfg.llm, proj.bible, proj.script, instruction))
    proj.set_stage("script", "done")
    status(name, config)


@app.command("lora-dataset")
def lora_dataset(name: str, char_id: str, config: Optional[Path] = ConfigOpt):
    """Build an identity-LoRA training set for one character."""
    from .cast.lora import build_dataset

    cfg = _cfg(config, None)
    out = build_dataset(_project(cfg, name), char_id)
    console.print(f"dataset: {out}\n" + json.loads((out / "README.json").read_text())["suggested"])


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8700, config: Optional[Path] = ConfigOpt,
          set_: Optional[List[str]] = SetOpt):
    """Start the web UI / API."""
    import uvicorn

    from .server.app import create_app

    uvicorn.run(create_app(_cfg(config, set_)), host=host, port=port)


@app.command()
def doctor(config: Optional[Path] = ConfigOpt, set_: Optional[List[str]] = SetOpt):
    """Check that every configured backend is installed / reachable."""
    import httpx

    cfg = _cfg(config, set_)
    ok = lambda b: "[green]ok[/]" if b else "[red]missing[/]"  # noqa: E731
    has = lambda m: importlib.util.find_spec(m) is not None  # noqa: E731
    console.print(f"ffmpeg            {ok(shutil.which('ffmpeg'))}")

    def ping(url: str, path: str) -> bool:
        try:
            return httpx.get(url.rstrip("/") + path, timeout=3).status_code < 500
        except Exception:
            return False

    if cfg.llm.backend == "openai":
        console.print(f"LLM  {cfg.llm.model:22s} {ok(ping(cfg.llm.base_url, '/models'))} {cfg.llm.base_url}")
    if cfg.vlm.backend == "openai":
        console.print(f"VLM  {cfg.vlm.model:22s} {ok(ping(cfg.vlm.base_url, '/models'))} {cfg.vlm.base_url}")
    console.print(f"ASR  mlx-whisper {ok(has('mlx_whisper'))}  faster-whisper {ok(has('faster_whisper'))}")
    console.print(f"Separation demucs {ok(has('demucs'))}   Diarization pyannote {ok(has('pyannote.audio'))}")
    console.print(f"Faces insightface {ok(has('insightface'))} (opencv fallback always available)")
    urls = set()
    if cfg.tts.backend == "worker":
        urls.add(cfg.tts.url)
    if "worker" in (cfg.video.talking_backend, cfg.video.broll_backend):
        urls.add(cfg.video.worker_url)
    for u in urls:
        console.print(f"worker            {ok(ping(u, '/health'))} {u}")
    comfy = set()
    if cfg.image.backend == "comfyui":
        comfy.add(cfg.image.url)
    if "comfyui" in (cfg.video.talking_backend, cfg.video.broll_backend):
        comfy.add(cfg.video.comfy_url)
    for u in comfy:
        console.print(f"ComfyUI           {ok(ping(u, '/system_stats'))} {u}")


if __name__ == "__main__":
    app()
