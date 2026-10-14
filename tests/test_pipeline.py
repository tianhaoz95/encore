"""End-to-end dry run: real ffmpeg, fallback models, worker protocol."""
import json
import threading
import time

import pytest
import uvicorn

from encore import pipeline
from encore.core import media
from encore.core.config import Config
from encore.core.project import Project


def dry_config(tmp_path) -> Config:
    return Config.model_validate({
        "projects_dir": str(tmp_path / "projects"),
        "llm": {"backend": "template"}, "vlm": {"backend": "none"}, "asr": {"backend": "none"},
        "separation": {"backend": "none"}, "diarization": {"backend": "none"}, "faces": {"backend": "none"},
        "tts": {"backend": "silent"}, "image": {"backend": "still", "width": 640, "height": 360},
        "video": {"talking_backend": "kenburns", "broll_backend": "kenburns", "width": 640, "height": 360},
        "edit": {"width": 640, "height": 360, "grain": 2},
    })


def test_full_dry_run(tmp_path, clip):
    cfg = dry_config(tmp_path)
    proj = Project.create(cfg.projects_dir and tmp_path / "projects", clip, "an interview", "t1",
                          {"target_seconds": 20, "names": ["Ana"]})
    pipeline.run(proj, cfg)
    final = proj.p("output", "final.mp4")
    assert final.exists()
    assert all(s.status == "done" for s in proj.meta.stages.values())
    total = media.source_info(proj.source).duration + sum(s.duration for s in proj.script.shots)
    assert abs(media.duration(final) - total) < 1.5
    assert proj.p("output", "final.srt").read_text().count("-->") >= 3
    # regenerate one shot only
    before = proj.shot_video("s01").stat().st_mtime
    s02 = proj.shot_video("s02").stat().st_mtime
    time.sleep(1.1)
    pipeline.run(proj, cfg, stages=["shoot"], shots=["s01"])
    assert proj.shot_video("s01").stat().st_mtime > before
    assert proj.shot_video("s02").stat().st_mtime == s02


def test_worker_roundtrip(tmp_path, clip):
    from encore.backends.worker_client import WorkerClient
    from encore.workers.server import create_app

    app = create_app({"work_dir": str(tmp_path / "w"),
                      "engines": {"kb": {"type": "kenburns", "task": "talking"}}})
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8197, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    try:
        img = media.extract_frame(clip, 1.0, tmp_path / "f.jpg")
        wav = media.write_wav(tmp_path / "a.wav", media.silence(1.5))
        c = WorkerClient("http://127.0.0.1:8197", timeout=120)
        assert c.health()["engines"]["kb"]["task"] == "talking"
        out = c.run("talking", "kb", {"seconds": 1.5, "width": 320, "height": 180, "fps": 12},
                    {"image": img, "audio": wav}, tmp_path / "out.mp4", poll=0.2)
        assert media.duration(out) > 1.0
        with pytest.raises(Exception):
            c.run("tts", "kb", {}, {}, tmp_path / "x.wav")  # wrong task for engine
    finally:
        server.should_exit = True
