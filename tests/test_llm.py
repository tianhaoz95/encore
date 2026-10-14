import pytest

from encore.core.llm import LLMError, extract_json
from encore.core.schemas import Character, Line, Shot, ShotKind, ShotList, StoryBible
from encore.write.scriptwriter import normalize, template_script


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('<think>hmm {"no": 1}</think>\n```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('Sure! Here it is: {"a": "x}y", "b": [1, {"c": 3}]} hope that helps') == \
        {"a": "x}y", "b": [1, {"c": 3}]}
    with pytest.raises(LLMError):
        extract_json("no json here")


def bible():
    return StoryBible(characters=[Character(id="char_0", name="Jisoo"), Character(id="char_1", name="Lisa")])


def test_normalize_repairs_llm_slips():
    script = ShotList(title="t", format="interview", shots=[
        Shot(id="s01", kind=ShotKind.talking, characters=[], lines=[Line(speaker="Jisoo", text="Hi!")]),
        Shot(id="s01", kind=ShotKind.extend, lines=[]),
        Shot(id="s03", kind=ShotKind.talking, characters=["Lisa"], lines=[Line(speaker="Host", text="Q?"),
                                                                          Line(speaker="  ", text=" ")]),
        Shot(id="s04", kind=ShotKind.talking, lines=[]),
    ])
    out = normalize(script, bible())
    ids = [s.id for s in out.shots]
    assert len(set(ids)) == len(ids)
    assert out.shots[0].lines[0].speaker == "char_0" and out.shots[0].characters == ["char_0"]
    assert out.shots[1].kind == ShotKind.broll  # extend only allowed first
    assert out.shots[2].characters == ["char_1"] and out.shots[2].lines[0].speaker == "host"
    assert "host" in out.extra_voices and len(out.shots[2].lines) == 1
    assert out.shots[3].kind == ShotKind.broll  # talking without lines


def test_template_script_is_valid():
    s = template_script(bible(), "a podcast", {})
    assert s.shots and all(sh.setting for sh in s.shots)
    assert any(l.speaker == "char_0" for sh in s.shots for l in sh.lines)


def test_chat_client_schema_fallback_and_retry():
    import json

    import httpx

    from encore.core.llm import ChatClient
    from encore.analyze.vlm import PersonDescription

    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body.get("response_format", {}).get("type"))
        if body.get("response_format", {}).get("type") == "json_schema":
            return httpx.Response(400, json={"error": "unsupported"})  # old server
        n = sum(1 for m in body["messages"] if m["role"] == "assistant")
        content = "oops not json" if n == 0 else '{"description": "short black hair"}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    c = ChatClient("http://llm/v1", "m")
    c.http = httpx.Client(transport=httpx.MockTransport(handler))
    out = c.structured([{"role": "user", "content": "describe"}], PersonDescription)
    assert out.description == "short black hair"
    assert calls[:2] == ["json_schema", "json_object"]
