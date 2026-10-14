"""Face detection, identity embeddings and clustering into characters.

Backends:
  insightface  - RetinaFace + ArcFace (buffalo_l). Best; CUDA on Spark, CoreML/CPU on Mac.
  opencv       - YuNet + SFace from the OpenCV model zoo (auto-downloaded, ~40 MB). Decent.
The same engine is reused to QC generated keyframes (identity similarity)."""

from __future__ import annotations

import importlib.util
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

CACHE = Path.home() / ".cache" / "encore"
_YUNET = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
_SFACE = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"


@dataclass
class Face:
    bbox: np.ndarray  # x1, y1, x2, y2
    score: float
    embedding: np.ndarray  # L2-normalised

    @property
    def size(self) -> float:
        return float(min(self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1]))


def _download(url: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / url.rsplit("/", 1)[-1]
    if not dst.exists() or dst.stat().st_size < 10_000:
        tmp = dst.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(dst)
    return dst


class FaceEngine:
    def __init__(self, backend: str = "auto"):
        if backend == "auto":
            backend = "insightface" if importlib.util.find_spec("insightface") else "opencv"
        self.backend = backend
        if backend == "insightface":
            from insightface.app import FaceAnalysis  # type: ignore
            import onnxruntime as ort  # type: ignore

            avail = ort.get_available_providers()
            providers = [p for p in ("CUDAExecutionProvider", "CoreMLExecutionProvider",
                                     "CPUExecutionProvider") if p in avail]
            self.app = FaceAnalysis(name="buffalo_l", providers=providers,
                                    allowed_modules=["detection", "recognition"])
            self.app.prepare(ctx_id=0, det_size=(640, 640))
        elif backend == "opencv":
            self.det = cv2.FaceDetectorYN.create(str(_download(_YUNET)), "", (320, 320), 0.7, 0.3, 5000)
            self.rec = cv2.FaceRecognizerSF.create(str(_download(_SFACE)), "")
        else:
            raise ValueError(f"unknown face backend {backend}")

    def detect(self, img: np.ndarray) -> list[Face]:
        if self.backend == "insightface":
            return [Face(bbox=f.bbox.astype(np.float32), score=float(f.det_score),
                         embedding=f.normed_embedding.astype(np.float32)) for f in self.app.get(img)]
        h, w = img.shape[:2]
        self.det.setInputSize((w, h))
        _, dets = self.det.detect(img)
        faces = []
        for d in dets if dets is not None else []:
            aligned = self.rec.alignCrop(img, d)
            emb = self.rec.feature(aligned).flatten().astype(np.float32)
            emb /= np.linalg.norm(emb) + 1e-8
            x, y, bw, bh = d[:4]
            faces.append(Face(bbox=np.array([x, y, x + bw, y + bh], np.float32), score=float(d[-1]),
                              embedding=emb))
        return faces


_engine: Optional[FaceEngine] = None


def get_engine(backend: str = "auto") -> FaceEngine:
    global _engine
    if _engine is None or (backend not in ("auto", _engine.backend)):
        _engine = FaceEngine(backend)
    return _engine


def sharpness(img: np.ndarray) -> float:
    return float(cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def crop_face(img: np.ndarray, bbox: np.ndarray, margin: float = 0.45) -> np.ndarray:
    """Square crop with margin (head + a bit of hair/shoulders) for references."""
    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    side = max(x2 - x1, y2 - y1) * (1 + 2 * margin)
    a, b = int(max(cx - side / 2, 0)), int(max(cy - side / 2, 0))
    c, d = int(min(cx + side / 2, w)), int(min(cy + side / 2, h))
    return img[b:d, a:c]


def cluster_embeddings(embs: np.ndarray, threshold: float, min_size: int) -> np.ndarray:
    """Average-linkage agglomerative clustering on cosine distance.

    Returns labels (-1 = noise/small cluster). O(n^2) memory; fine for the few
    hundred faces a clip yields at 2 fps."""
    n = len(embs)
    if n == 0:
        return np.zeros(0, int)
    clusters: dict[int, list[int]] = {i: [i] for i in range(n)}
    sim = embs @ embs.T
    # cluster-level similarity matrix (average linkage), updated incrementally
    csim = sim.copy()
    np.fill_diagonal(csim, -np.inf)
    active = np.ones(n, bool)
    while True:
        masked = np.where(active[:, None] & active[None, :], csim, -np.inf)
        i, j = np.unravel_index(np.argmax(masked), masked.shape)
        if masked[i, j] < 1 - threshold:
            break
        ni, nj = len(clusters[i]), len(clusters[j])
        new_row = (csim[i] * ni + csim[j] * nj) / (ni + nj)
        csim[i, :] = new_row
        csim[:, i] = new_row
        csim[i, i] = -np.inf
        clusters[i].extend(clusters.pop(j))
        active[j] = False
        csim[j, :] = -np.inf
        csim[:, j] = -np.inf
    labels = np.full(n, -1, int)
    big = sorted((m for m in clusters.values() if len(m) >= min_size), key=len, reverse=True)
    for lab, members in enumerate(big):
        labels[members] = lab
    return labels


def identity_similarity(img_path: Path, refs: list[np.ndarray], engine: FaceEngine) -> list[float]:
    """For each face found in a generated image, best cosine similarity to any
    reference identity. Used to reject off-model keyframes."""
    img = cv2.imread(str(img_path))
    if img is None or not refs:
        return []
    faces = engine.detect(img)
    ref = np.stack(refs)
    return [float((ref @ f.embedding).max()) for f in faces]
