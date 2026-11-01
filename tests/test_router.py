"""Router tests with fake clients: fallback, retry and total failure."""

import json
from types import SimpleNamespace

import pytest

from faultcase.router import Router, RouterError
from faultcase.settings import Settings

SCHEMA = {
    "type": "object",
    "required": ["ok"],
    "properties": {"ok": {"type": "boolean"}},
}
MESSAGES = [{"role": "user", "content": "SECRET-PROMPT-DO-NOT-LOG"}]


def _completion(content, prompt_tokens=10, completion_tokens=5):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )


class FakeClient:
    """Scripted stand-in for an OpenAI client (no network)."""

    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.calls = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        behavior = self._behaviors.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def _router(tmp_path, clients, route=("baseten", "fireworks"), settings=None):
    config = {
        "providers": {
            "baseten": {
                "base_url": "http://baseten.test",
                "api_key_env": "BASETEN_API_KEY",
                "model": "model-baseten",
            },
            "fireworks": {
                "base_url": "http://fireworks.test",
                "api_key_env": "FIREWORKS_API_KEY",
                "model": "model-fireworks",
            },
        },
        "routes": {"test_role": list(route)},
        "settings": {
            "timeout_seconds": 5,
            "max_retries_per_provider": 1,
            "log_usage": True,
        },
    }
    settings = settings or Settings(
        meta_api_key=None,
        baseten_api_key="KEY-BASETEN-SECRET",
        fireworks_api_key="KEY-FIREWORKS-SECRET",
        baseten_model="model-baseten",
    )
    factory_calls = []

    def factory(name, base_url, api_key, timeout):
        factory_calls.append(name)
        return clients[name]

    router = Router(
        config=config,
        settings=settings,
        usage_path=tmp_path / "usage.jsonl",
        client_factory=factory,
    )
    return router, factory_calls


def _log_lines(tmp_path):
    with open(tmp_path / "usage.jsonl", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_baseten_fails_fireworks_answers(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([RuntimeError("baseten is down")]),
        "fireworks": FakeClient([_completion('{"ok": true}')]),
    })
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    lines = _log_lines(tmp_path)
    assert [(l["provider"], l["success"], l["fallback_used"]) for l in lines] == [
        ("baseten", False, False),
        ("fireworks", True, True),
    ]
    assert lines[1]["model"] == "model-fireworks"
    assert (lines[1]["prompt_tokens"], lines[1]["completion_tokens"]) == (10, 5)
    raw = (tmp_path / "usage.jsonl").read_text(encoding="utf-8")
    assert "SECRET-PROMPT-DO-NOT-LOG" not in raw
    assert "SECRET" not in raw


def test_invalid_json_retried_once_then_succeeds(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([
            _completion('{"ok": tru'),
            _completion('{"ok": true}'),
        ]),
        "fireworks": FakeClient([]),
    }, route=("baseten",))
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    lines = _log_lines(tmp_path)
    assert len(lines) == 2
    assert all(l["provider"] == "baseten" and not l["fallback_used"] for l in lines)
    assert [l["success"] for l in lines] == [False, True]


def test_schema_error_retried_then_next_provider(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([
            _completion('{"wrong": 1}'),
            _completion('{"wrong": 2}'),
        ]),
        "fireworks": FakeClient([_completion('{"ok": true}')]),
    })
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    lines = _log_lines(tmp_path)
    assert [l["provider"] for l in lines] == ["baseten", "baseten", "fireworks"]
    assert [l["fallback_used"] for l in lines] == [False, False, True]


def test_all_providers_fail_with_clear_exception(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([RuntimeError("baseten is down")]),
        "fireworks": FakeClient([TimeoutError("fireworks timed out")]),
    })
    with pytest.raises(RouterError) as exc_info:
        router.call("test_role", MESSAGES, SCHEMA)
    message = str(exc_info.value)
    assert "test_role" in message
    assert "baseten" in message and "baseten is down" in message
    assert "fireworks" in message and "fireworks timed out" in message


def test_json_schema_unsupported_falls_back_to_json_object(tmp_path):
    fireworks = FakeClient([
        Exception("400 response_format json_schema is not supported"),
        _completion('{"ok": true}'),
    ])
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([RuntimeError("baseten is down")]),
        "fireworks": fireworks,
    })
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    assert fireworks.calls[0]["response_format"]["type"] == "json_schema"
    assert fireworks.calls[1]["response_format"] == {"type": "json_object"}


def test_missing_key_provider_is_skipped(tmp_path):
    settings = Settings(
        meta_api_key=None,
        baseten_api_key=None,
        fireworks_api_key="KEY-FIREWORKS-SECRET",
        baseten_model="model-baseten",
    )
    router, factory_calls = _router(tmp_path, {
        "fireworks": FakeClient([_completion('{"ok": true}')]),
    }, settings=settings)
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    assert factory_calls == ["fireworks"]
    lines = _log_lines(tmp_path)
    assert [(l["provider"], l["success"]) for l in lines] == [
        ("baseten", False),
        ("fireworks", True),
    ]


def test_unknown_role_raises(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([]),
        "fireworks": FakeClient([]),
    })
    with pytest.raises(RouterError, match="unknown role"):
        router.call("nope", MESSAGES, SCHEMA)
