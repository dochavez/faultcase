"""Router tests with fake clients: fallback, retry and total failure."""

import json
import threading
import time
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


def _completion(content, prompt_tokens=10, completion_tokens=5, cached_tokens=None,
                finish_reason=None):
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )
    if cached_tokens is not None:
        usage.prompt_tokens_details = SimpleNamespace(cached_tokens=cached_tokens)
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason=finish_reason
        )],
        usage=usage,
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
        if callable(behavior):
            return behavior()
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


def test_analysis_mode_defaults_to_single_and_reads_config(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([]),
        "fireworks": FakeClient([]),
    })
    assert router.analysis_mode("test_role") == "single"
    router._config["roles"] = {"test_role": {"analysis_mode": "second_opinion"}}
    assert router.analysis_mode("test_role") == "second_opinion"


def test_call_parallel_returns_both_in_route_order(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([_completion('{"ok": true}')]),
        "fireworks": FakeClient([_completion('{"ok": true}')]),
    })
    results = router.call_parallel("test_role", MESSAGES, SCHEMA)
    assert [(r["provider"], r["success"], r["data"]) for r in results] == [
        ("baseten", True, {"ok": True}),
        ("fireworks", True, {"ok": True}),
    ]
    lines = _log_lines(tmp_path)
    assert len(lines) == 2
    assert all(line["success"] for line in lines)


def test_call_parallel_captures_failure_without_raising(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([RuntimeError("baseten is down")]),
        "fireworks": FakeClient([_completion('{"ok": true}')]),
    })
    results = router.call_parallel("test_role", MESSAGES, SCHEMA)
    assert [r["success"] for r in results] == [False, True]
    assert "baseten is down" in results[0]["error"]
    assert results[1]["data"] == {"ok": True}


def test_call_parallel_unknown_role_raises(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([]),
        "fireworks": FakeClient([]),
    })
    with pytest.raises(RouterError, match="unknown role"):
        router.call_parallel("nope", MESSAGES, SCHEMA)


class RendezvousClient:
    """Fails unless the peer call is in flight at the same time."""

    def __init__(self, mine, peer, completion):
        self._mine = mine
        self._peer = peer
        self._completion = completion

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self._mine.set()
        assert self._peer.wait(timeout=10), "providers were not called concurrently"
        return self._completion


def test_cached_tokens_are_logged_when_reported(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([_completion('{"ok": true}', cached_tokens=7)]),
        "fireworks": FakeClient([]),
    }, route=("baseten",))
    _, info = router.call_with_info("test_role", MESSAGES, SCHEMA)
    assert info["cached_tokens"] == 7
    assert _log_lines(tmp_path)[0]["cached_tokens"] == 7


def test_cached_tokens_default_to_zero(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([_completion('{"ok": true}')]),
        "fireworks": FakeClient([]),
    }, route=("baseten",))
    _, info = router.call_with_info("test_role", MESSAGES, SCHEMA)
    assert info["cached_tokens"] == 0
    assert _log_lines(tmp_path)[0]["cached_tokens"] == 0


def test_no_hedge_when_primary_answers_fast(tmp_path):
    fireworks = FakeClient([_completion('{"ok": true}')])
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([_completion('{"ok": true}')]),
        "fireworks": fireworks,
    })
    router._hedge_after = 30
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    assert fireworks.calls == []
    assert [line for line in _log_lines(tmp_path)
            if line.get("event") == "hedge"] == []


def test_hedge_fires_when_primary_is_slow(tmp_path):
    gate = threading.Event()
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([
            lambda: gate.wait(timeout=30) and _completion('{"ok": true}'),
        ]),
        "fireworks": FakeClient([
            lambda: (gate.set(), _completion('{"ok": true}'))[1],
        ]),
    })
    router._hedge_after = 0.05
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    hedges = [line for line in _log_lines(tmp_path)
              if line.get("event") == "hedge"]
    assert len(hedges) == 1
    assert hedges[0]["winner"] == "fireworks"
    assert hedges[0]["ignored"] == "baseten"
    assert hedges[0]["providers"] == ["baseten", "fireworks"]
    assert gate.is_set()


def test_fast_primary_failure_falls_back_without_hedge(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([RuntimeError("baseten is down")]),
        "fireworks": FakeClient([_completion('{"ok": true}')]),
    })
    router._hedge_after = 5
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    lines = _log_lines(tmp_path)
    assert [line.get("event") for line in lines] == [None, None]
    assert lines[1]["fallback_used"] is True


def test_hedge_both_fail_raises_with_both_errors(tmp_path):
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([RuntimeError("baseten is down")]),
        "fireworks": FakeClient([TimeoutError("fireworks timed out")]),
    })
    with pytest.raises(RouterError) as exc_info:
        router.call("test_role", MESSAGES, SCHEMA)
    message = str(exc_info.value)
    assert "baseten is down" in message
    assert "fireworks timed out" in message


def test_reasoning_effort_sent_when_configured(tmp_path):
    baseten = FakeClient([_completion('{"ok": true}')])
    router, _ = _router(tmp_path, {
        "baseten": baseten,
        "fireworks": FakeClient([]),
    }, route=("baseten",))
    router._config["roles"] = {"test_role": {"reasoning_effort": "high"}}
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    assert baseten.calls[0]["reasoning_effort"] == "high"


def test_reasoning_effort_omitted_when_unset(tmp_path):
    baseten = FakeClient([_completion('{"ok": true}')])
    router, _ = _router(tmp_path, {
        "baseten": baseten,
        "fireworks": FakeClient([]),
    }, route=("baseten",))
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    assert "reasoning_effort" not in baseten.calls[0]


def test_reasoning_effort_rejected_once_then_remembered(tmp_path):
    fireworks = FakeClient([
        Exception("400 unknown parameter: reasoning_effort"),
        _completion('{"ok": true}'),
        _completion('{"ok": true}'),
    ])
    router, _ = _router(tmp_path, {
        "baseten": FakeClient([RuntimeError("baseten is down")]),
        "fireworks": fireworks,
    })
    router._config["roles"] = {"test_role": {"reasoning_effort": "medium"}}
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    assert fireworks.calls[0]["reasoning_effort"] == "medium"
    assert "reasoning_effort" not in fireworks.calls[1]
    assert "reasoning_effort" not in fireworks.calls[2]


def test_max_tokens_sent_when_configured(tmp_path):
    baseten = FakeClient([_completion('{"ok": true}')])
    router, _ = _router(tmp_path, {
        "baseten": baseten,
        "fireworks": FakeClient([]),
    }, route=("baseten",))
    router._config["roles"] = {"test_role": {"max_tokens": 16384}}
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    assert baseten.calls[0]["max_tokens"] == 16384


def test_max_tokens_omitted_when_unset(tmp_path):
    baseten = FakeClient([_completion('{"ok": true}')])
    router, _ = _router(tmp_path, {
        "baseten": baseten,
        "fireworks": FakeClient([]),
    }, route=("baseten",))
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    assert "max_tokens" not in baseten.calls[0]


def test_truncated_response_logged_and_retried(tmp_path):
    baseten = FakeClient([
        _completion('{"ok": tru', finish_reason="length"),
        _completion('{"ok": true}', finish_reason="stop"),
    ])
    router, _ = _router(tmp_path, {
        "baseten": baseten,
        "fireworks": FakeClient([]),
    }, route=("baseten",))
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    lines = _log_lines(tmp_path)
    assert len(lines) == 2
    assert lines[0]["truncated"] is True
    assert lines[0]["success"] is False
    assert lines[1]["success"] is True


def test_reasoning_effort_provider_override_wins(tmp_path):
    baseten = FakeClient([_completion('{"ok": true}')])
    fireworks = FakeClient([_completion('{"ok": true}')])
    router, _ = _router(tmp_path, {
        "baseten": baseten,
        "fireworks": fireworks,
    })
    router._config["roles"] = {"test_role": {
        "reasoning_effort": "high",
        "reasoning_effort_by_provider": {"baseten": "low"},
    }}
    results = router.call_parallel("test_role", MESSAGES, SCHEMA)
    assert [r["success"] for r in results] == [True, True]
    assert baseten.calls[0]["reasoning_effort"] == "low"
    assert fireworks.calls[0]["reasoning_effort"] == "high"


def test_reasoning_effort_null_override_omits_param(tmp_path):
    baseten = FakeClient([_completion('{"ok": true}')])
    router, _ = _router(tmp_path, {
        "baseten": baseten,
        "fireworks": FakeClient([]),
    }, route=("baseten",))
    router._config["roles"] = {"test_role": {
        "reasoning_effort": "high",
        "reasoning_effort_by_provider": {"baseten": None},
    }}
    assert router.call("test_role", MESSAGES, SCHEMA) == {"ok": True}
    assert "reasoning_effort" not in baseten.calls[0]


def test_call_parallel_runs_concurrently(tmp_path):
    started_baseten = threading.Event()
    started_fireworks = threading.Event()
    router, _ = _router(tmp_path, {
        "baseten": RendezvousClient(
            started_baseten, started_fireworks, _completion('{"ok": true}')),
        "fireworks": RendezvousClient(
            started_fireworks, started_baseten, _completion('{"ok": true}')),
    })
    results = router.call_parallel("test_role", MESSAGES, SCHEMA)
    assert [r["success"] for r in results] == [True, True]


def test_call_parallel_stops_waiting_for_a_slow_second_opinion(tmp_path):
    release = threading.Event()

    def slow():
        release.wait(5)
        return _completion('{"ok": true}')

    router, _ = _router(tmp_path, {
        "baseten": FakeClient([_completion('{"ok": true}')]),
        "fireworks": FakeClient([slow]),
    })
    router._config["roles"] = {"test_role": {"second_opinion_wait_seconds": 0.2}}
    start = time.monotonic()
    results = router.call_parallel("test_role", MESSAGES, SCHEMA)
    elapsed = time.monotonic() - start
    release.set()
    assert elapsed < 3
    assert results[0]["success"] is True
    assert results[1]["success"] is False
    assert "after the first opinion" in results[1]["error"]



def test_default_client_disables_sdk_retries():
    client = Router._default_client("meta", "http://meta.test", "KEY-TEST", 5)
    assert client.max_retries == 0
