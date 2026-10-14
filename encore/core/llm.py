"""Client for any local OpenAI-compatible chat server (Ollama, mlx_lm.server,
vLLM, llama.cpp server, LM Studio). No cloud endpoints are ever contacted
unless you point base_url at one yourself."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLMError(RuntimeError):
    pass


def image_part(path: Path, max_side: int = 768) -> dict:
    """Encode an image as an OpenAI `image_url` content part, downscaled."""
    from PIL import Image
    import io

    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def extract_json(text: str):
    """Pull the first JSON object/array out of a model reply (handles ```json
    fences and reasoning-model <think> blocks)."""
    text = _THINK_RE.sub("", text).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise LLMError(f"no JSON in reply: {text[:300]!r}")
    start = min(starts)
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return json.loads(text[start: i + 1])
    raise LLMError(f"unterminated JSON in reply: {text[:300]!r}")


class ChatClient:
    def __init__(self, base_url: str, model: str, api_key: str = "local", timeout: float = 600,
                 temperature: float = 0.7, max_tokens: int = 8192):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.http = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {api_key}"})

    def chat(self, messages: list[dict], json_schema: Optional[dict] = None,
             temperature: Optional[float] = None) -> str:
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
        }
        if json_schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "output", "schema": json_schema}}
        try:
            r = self.http.post(f"{self.base_url}/chat/completions", json=body)
            if r.status_code >= 400 and json_schema is not None:
                # Older servers only know json_object (or nothing at all).
                body["response_format"] = {"type": "json_object"}
                r = self.http.post(f"{self.base_url}/chat/completions", json=body)
                if r.status_code >= 400:
                    body.pop("response_format")
                    r = self.http.post(f"{self.base_url}/chat/completions", json=body)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"LLM request to {self.base_url} failed: {e}") from e
        return r.json()["choices"][0]["message"]["content"] or ""

    def structured(self, messages: list[dict], model: Type[T], retries: int = 2,
                   temperature: Optional[float] = None) -> T:
        """Ask for JSON matching `model`; feed validation errors back on failure."""
        schema = model.model_json_schema()
        msgs = list(messages)
        last_err: Exception | None = None
        for _ in range(retries + 1):
            reply = self.chat(msgs, json_schema=schema, temperature=temperature)
            try:
                return model.model_validate(extract_json(reply))
            except (LLMError, ValidationError, json.JSONDecodeError) as e:
                last_err = e
                msgs = msgs + [
                    {"role": "assistant", "content": reply[:6000]},
                    {"role": "user", "content": f"That was not valid. Error:\n{str(e)[:1500]}\n"
                                                "Reply again with ONLY the corrected JSON."},
                ]
        raise LLMError(f"model never produced valid {model.__name__}: {last_err}")
