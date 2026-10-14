"""Headless ComfyUI client.

Workflows are ComfyUI *API-format* JSON (Workflow > Export (API)). Any string
input may contain placeholders that are substituted per job:

  {{PROMPT}} {{NEGATIVE}} {{IMAGE}} {{IMAGE2}} {{AUDIO}} {{WIDTH}} {{HEIGHT}}
  {{FRAMES}} {{FPS}} {{SEED}} {{STEPS}} {{LORA}} {{PREFIX}}

A string that is *exactly* one numeric placeholder (e.g. "{{SEED}}") becomes a
number. File placeholders are uploaded to ComfyUI's input folder first. To use
a different model, build it in ComfyUI, export API JSON, add placeholders, and
point the config at the file — no code change needed."""

from __future__ import annotations

import json
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx

_PH = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
FILE_KEYS = {"IMAGE", "IMAGE2", "AUDIO", "VIDEO"}


class ComfyError(RuntimeError):
    pass


def fill_template(node: Any, values: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        return {k: fill_template(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [fill_template(v, values) for v in node]
    if isinstance(node, str):
        full = _PH.fullmatch(node)
        if full and full.group(1) in values and isinstance(values[full.group(1)], (int, float)):
            return values[full.group(1)]
        return _PH.sub(lambda m: str(values.get(m.group(1), m.group(0))), node)
    return node


def placeholders(workflow: dict) -> set[str]:
    return set(_PH.findall(json.dumps(workflow)))


class ComfyClient:
    def __init__(self, url: str, timeout: float = 3600):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex
        self.http = httpx.Client(timeout=httpx.Timeout(60.0, read=600.0))

    def ping(self) -> dict:
        return self.http.get(f"{self.url}/system_stats", timeout=5).json()

    def upload(self, path: Path) -> str:
        with open(path, "rb") as fh:
            r = self.http.post(f"{self.url}/upload/image",
                               files={"image": (f"mre_{uuid.uuid4().hex[:8]}_{path.name}", fh)},
                               data={"overwrite": "true"})
        r.raise_for_status()
        d = r.json()
        return f"{d['subfolder']}/{d['name']}" if d.get("subfolder") else d["name"]

    def run(self, workflow_path: Path, values: dict[str, Any], out_dir: Path,
            want: tuple[str, ...] = ("images", "gifs", "videos", "audio")) -> list[Path]:
        wf = json.loads(Path(workflow_path).read_text())
        values = dict(values)
        values.setdefault("SEED", random.randint(0, 2**31 - 1))
        values.setdefault("PREFIX", f"encore/{uuid.uuid4().hex[:8]}")
        for k in FILE_KEYS & set(values):
            if values[k]:
                values[k] = self.upload(Path(values[k]))
        missing = placeholders(wf) - set(values)
        if missing:
            raise ComfyError(f"{workflow_path.name}: no value for placeholders {sorted(missing)}")
        prompt = fill_template(wf, values)
        r = self.http.post(f"{self.url}/prompt", json={"prompt": prompt, "client_id": self.client_id})
        if r.status_code >= 400:
            raise ComfyError(f"ComfyUI rejected workflow {workflow_path.name}: {r.text[:1500]}")
        pid = r.json()["prompt_id"]
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            h = self.http.get(f"{self.url}/history/{pid}").json()
            if pid in h:
                entry = h[pid]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                    raise ComfyError(f"ComfyUI execution error: {json.dumps(msgs)[:1500]}")
                if status.get("completed", True):
                    return self._download(entry.get("outputs", {}), out_dir, want)
            time.sleep(2)
        raise ComfyError(f"ComfyUI job {pid} timed out")

    def _download(self, outputs: dict, out_dir: Path, want: tuple[str, ...]) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for node_out in outputs.values():
            for key in want:
                for item in node_out.get(key, []):
                    if item.get("type") not in ("output", None):
                        continue
                    params = {"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                              "type": item.get("type", "output")}
                    dst = out_dir / item["filename"]
                    with self.http.stream("GET", f"{self.url}/view", params=params) as resp:
                        resp.raise_for_status()
                        with open(dst, "wb") as f:
                            for chunk in resp.iter_bytes():
                                f.write(chunk)
                    files.append(dst)
        if not files:
            raise ComfyError("ComfyUI finished but produced no output files")
        return files


_clients: dict[str, ComfyClient] = {}


def get_comfy(url: str, timeout: Optional[float] = None) -> ComfyClient:
    if url not in _clients:
        _clients[url] = ComfyClient(url, timeout or 3600)
    return _clients[url]
