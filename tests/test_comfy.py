import json

import httpx

from encore.backends.comfy import ComfyClient, fill_template, placeholders


def test_fill_template_types():
    wf = {"1": {"inputs": {"seed": "{{SEED}}", "text": "a {{PROMPT}} b", "img": "{{IMAGE}}", "n": 3,
                           "link": ["2", 0]}}}
    out = fill_template(wf, {"SEED": 42, "PROMPT": "cat", "IMAGE": "x.png"})
    assert out["1"]["inputs"] == {"seed": 42, "text": "a cat b", "img": "x.png", "n": 3, "link": ["2", 0]}
    assert placeholders(wf) == {"SEED", "PROMPT", "IMAGE"}


def test_run_roundtrip(tmp_path):
    wf = tmp_path / "wf.json"
    wf.write_text(json.dumps({"1": {"class_type": "LoadImage", "inputs": {"image": "{{IMAGE}}"}},
                              "2": {"class_type": "KSampler", "inputs": {"seed": "{{SEED}}", "prompt": "{{PROMPT}}"}}}))
    img = tmp_path / "in.png"
    img.write_bytes(b"png")
    seen = {}

    def handler(req: httpx.Request):
        if req.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "uploaded.png", "subfolder": ""})
        if req.url.path == "/prompt":
            seen["prompt"] = json.loads(req.content)["prompt"]
            return httpx.Response(200, json={"prompt_id": "p1"})
        if req.url.path == "/history/p1":
            return httpx.Response(200, json={"p1": {"status": {"status_str": "success", "completed": True},
                                                    "outputs": {"9": {"images": [{"filename": "o.png", "subfolder": "",
                                                                                  "type": "output"}]}}}})
        if req.url.path == "/view":
            return httpx.Response(200, content=b"result")
        return httpx.Response(404)

    c = ComfyClient("http://comfy")
    c.http = httpx.Client(transport=httpx.MockTransport(handler))
    files = c.run(wf, {"IMAGE": img, "PROMPT": "hello", "SEED": 7}, tmp_path / "out")
    assert files[0].read_bytes() == b"result"
    assert seen["prompt"]["1"]["inputs"]["image"] == "uploaded.png"
    assert seen["prompt"]["2"]["inputs"] == {"seed": 7, "prompt": "hello"}


def test_shipped_workflows_parse():
    from encore.core.config import REPO_ROOT

    for f in (REPO_ROOT / "workflows").glob("*.json"):
        wf = json.loads(f.read_text())
        assert all("class_type" in n for n in wf.values()), f
        assert "PREFIX" in placeholders(wf), f
