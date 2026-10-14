"""Build a small synthetic test clip: two 'shots' showing a face (scikit-image's
public-domain astronaut photo) with spoken audio from macOS `say` (or a tone).

    python tests/make_fixture.py out.mp4
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


def face_image() -> Image.Image:
    try:
        from skimage import data

        return Image.fromarray(data.astronaut())
    except Exception:
        # fallback: plain gradient (no face will be found; pipeline still runs)
        g = np.linspace(0, 255, 512, dtype=np.uint8)
        return Image.fromarray(np.stack([np.tile(g, (512, 1))] * 3, -1))


def main(out: Path) -> Path:
    tmp = Path(tempfile.mkdtemp())
    img = face_image().convert("RGB")
    a = tmp / "a.png"
    b = tmp / "b.png"
    img.resize((1280, 1280)).crop((0, 160, 1280, 880)).save(a)
    Image.fromarray(np.array(img)[:, ::-1]).resize((1280, 1280)).crop((0, 280, 1280, 1000)).save(b)
    speech = tmp / "speech.aiff"
    if shutil.which("say"):
        subprocess.run(["say", "-o", str(speech), "Thank you so much everyone! We love you. "
                        "This concert was the best night of our lives. See you next time!"], check=True)
        audio = ["-i", str(speech)]
    else:
        audio = ["-f", "lavfi", "-i", "sine=frequency=220:duration=8"]
    ff = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run(ff + ["-loop", "1", "-t", "4", "-i", str(a), "-loop", "1", "-t", "4", "-i", str(b), *audio,
                         "-filter_complex",
                         "[0:v]scale=1280:720,zoompan=z='1+0.001*on':d=100:s=1280x720:fps=25[v0];"
                         "[1:v]scale=1280:720,zoompan=z='1.1-0.001*on':d=100:s=1280x720:fps=25[v1];"
                         "[v0][v1]concat=n=2:v=1:a=0,format=yuv420p[v]",
                         "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-c:a", "aac", "-t", "8", "-shortest",
                         str(out)], check=True)
    shutil.rmtree(tmp)
    return out


if __name__ == "__main__":
    print(main(Path(sys.argv[1] if len(sys.argv) > 1 else "fixture.mp4")))
