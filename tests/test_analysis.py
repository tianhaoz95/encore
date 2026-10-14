import numpy as np

from encore.analyze.faces import cluster_embeddings
from encore.core.color import write_transfer_lut


def test_cluster_two_identities():
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=128), rng.normal(size=128)
    embs = np.stack([v + rng.normal(scale=0.15, size=128) for v in [a] * 6 + [b] * 4 + [rng.normal(size=128)]])
    embs /= np.linalg.norm(embs, axis=1, keepdims=True)
    labels = cluster_embeddings(embs, threshold=0.5, min_size=3)
    assert len(set(labels[:6])) == 1 and len(set(labels[6:10])) == 1
    assert labels[0] != labels[6] and labels[-1] == -1


def test_identity_lut(tmp_path):
    stats = {"mean": [50, 0, 0], "std": [20, 10, 10]}
    lut = write_transfer_lut(stats, stats, tmp_path / "x.cube", size=5)
    rows = [l for l in lut.read_text().splitlines() if l and l[0].isdigit()]
    vals = np.array([[float(x) for x in r.split()] for r in rows])
    assert vals.shape == (125, 3)
    assert np.allclose(vals[1], [0.25, 0, 0], atol=0.02)  # red varies fastest
    assert np.allclose(vals[-1], [1, 1, 1], atol=0.02)
