"""Stage 1 — understand the source clip."""

from __future__ import annotations

import cv2
import numpy as np

from ..analyze import audio as audio_mod
from ..analyze import vlm
from ..analyze.faces import crop_face, get_engine, sharpness
from ..analyze.scenes import scene_ranges
from ..core import media
from ..core.color import lab_stats
from ..core.config import Config
from ..core.project import Project
from ..core.schemas import Analysis, FaceTrack, Scene


def run(project: Project, cfg: Config, **_) -> Analysis:
    src = project.source
    info = media.source_info(src)
    info.path = project.rel(src)
    project.log(f"analyze: {info.width}x{info.height} {info.fps:.2f}fps {info.duration:.1f}s audio={info.has_audio}")
    a = Analysis(source=info)

    # --- scenes + one keyframe each
    frames_dir = project.dir("analysis", "frames")
    for i, (s, e) in enumerate(scene_ranges(src, info.duration)):
        kf = media.extract_frame(src, (s + e) / 2, frames_dir / f"scene_{i:03d}.jpg")
        a.scenes.append(Scene(index=i, start=s, end=e, keyframe=project.rel(kf)))
    project.log(f"analyze: {len(a.scenes)} scenes")
    a.last_frame = project.rel(media.extract_last_frame(src, project.p("analysis", "last_frame.png")))
    a.color_stats = lab_stats([project.p(s.keyframe) for s in a.scenes[-6:]] + [project.p(a.last_frame)])

    # --- audio: separate, transcribe, diarize
    lang = None
    if info.has_audio:
        mix = media.extract_audio(src, project.p("analysis", "audio", "mix.wav"))
        try:
            vocals, inst = audio_mod.separate_vocals(mix, project.dir("analysis", "audio"), cfg.separation)
        except Exception as e:  # separation is a nice-to-have
            project.log(f"analyze: vocal separation failed ({e}); using the full mix")
            vocals, inst = None, None
        a.vocals_path = project.rel(vocals) if vocals else project.rel(mix)
        a.instrumental_path = project.rel(inst) if inst else None
        speech = vocals or mix
        segs, lang = audio_mod.transcribe(speech, cfg.asr)
        try:
            segs = audio_mod.diarize(speech, segs, cfg.diarization)
        except Exception as e:
            project.log(f"analyze: diarization failed ({e}); continuing without speaker labels")
        a.transcript = segs
        project.log(f"analyze: {len(segs)} transcript segments, language={lang}")
    project.write_json("analysis/language.json", {"language": lang})

    # --- faces
    a.faces = _faces(project, cfg, src, info.duration)
    project.log(f"analyze: {len(a.faces)} face detections, "
                f"{len(set(f.cluster for f in a.faces if f.cluster >= 0))} identities")

    # --- VLM description
    try:
        step = max(1, len(a.scenes) // cfg.vlm.max_frames)
        frames = [project.p(s.keyframe) for s in a.scenes[::step]][: cfg.vlm.max_frames]
        transcript = " ".join(t.text for t in a.transcript)
        desc = vlm.describe_clip(cfg.vlm, frames, transcript)
        if desc:
            a.summary = desc.summary
            a.visual_style = desc.visual_style
            project.write_json("analysis/description.json", desc.model_dump())
    except Exception as e:
        project.log(f"analyze: VLM description failed ({e})")

    project.save_analysis(a)
    return a


def _faces(project: Project, cfg: Config, src, total: float) -> list[FaceTrack]:
    if cfg.faces.backend == "none":
        return []
    try:
        engine = get_engine(cfg.faces.backend)
    except Exception as e:  # missing models / no network for the first download
        project.log(f"analyze: face detection unavailable ({e}); characters will come from the VLM")
        return []
    project.log(f"analyze: face backend = {engine.backend}")
    crops_dir = project.dir("analysis", "faces")
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    stride = max(int(round(fps / cfg.faces.sample_fps)), 1)
    tracks: list[FaceTrack] = []
    embs: list[np.ndarray] = []
    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % stride == 0:
            ok, frame = cap.retrieve()
            if ok:
                for j, f in enumerate(engine.detect(frame)):
                    if f.size < cfg.faces.min_face_px:
                        continue
                    crop = crop_face(frame, f.bbox)
                    if crop.size == 0:
                        continue
                    path = crops_dir / f"t{idx:06d}_{j}.jpg"
                    cv2.imwrite(str(path), crop)
                    tracks.append(FaceTrack(time=idx / fps, bbox=f.bbox.tolist(), score=f.score,
                                            sharpness=sharpness(crop), crop=project.rel(path)))
                    embs.append(f.embedding)
        idx += 1
    cap.release()
    if not tracks:
        return []
    E = np.stack(embs)
    np.save(project.p("analysis", "face_embeddings.npy"), E)
    from ..analyze.faces import cluster_embeddings

    labels = cluster_embeddings(E, cfg.faces.cluster_threshold, cfg.faces.min_cluster_size)
    for t, lab in zip(tracks, labels):
        t.cluster = int(lab)
    return tracks
