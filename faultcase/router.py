"""Route model calls across providers with fallback and usage logging.

Reads config/providers.yaml, keeps one OpenAI-compatible client per
provider and exposes ``call(role, messages, response_schema)``. For each
provider in the role's route it requests a JSON response and validates it
against the schema: invalid JSON or schema errors are retried once, any
other error or timeout moves to the next provider. Every attempt appends
one line to logs/usage.jsonl with tokens and latency but never message
contents or keys.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate
from openai import OpenAI

from faultcase.settings import Settings, load_settings

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config" / "providers.yaml"
DEFAULT_USAGE_PATH = ROOT / "logs" / "usage.jsonl"


class RouterError(Exception):
    """Raised when a role has no working provider (or no such role)."""


class _InvalidResponse(Exception):
    """Invalid JSON or schema failure: retry the same provider once."""


def _unsupported_format(error: Exception) -> bool:
    text = str(error).lower()
    return "response_format" in text or "json_schema" in text


class Router:
    """One OpenAI-compatible client per provider, with role-based fallback."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        config: dict | None = None,
        settings: Settings | None = None,
        usage_path: str | Path | None = None,
        client_factory=None,
    ):
        if config is None:
            with open(config_path or DEFAULT_CONFIG_PATH, encoding="utf-8") as fh:
                config = yaml.safe_load(fh)
        self._config = config
        self._settings = settings or load_settings()
        self._usage_path = Path(usage_path or DEFAULT_USAGE_PATH)
        self._factory = client_factory or self._default_client
        options = config.get("settings", {})
        self._timeout = float(options.get("timeout_seconds", 90))
        self._max_retries = int(options.get("max_retries_per_provider", 1))
        self._log_usage = bool(options.get("log_usage", True))
        env_values = {
            "META_API_KEY": self._settings.meta_api_key,
            "BASETEN_API_KEY": self._settings.baseten_api_key,
            "FIREWORKS_API_KEY": self._settings.fireworks_api_key,
            "BASETEN_MODEL": self._settings.baseten_model,
        }
        self._providers: dict[str, dict] = {}
        self._clients: dict[str, object] = {}
        self._json_mode: dict[str, str] = {}
        for name, spec in config.get("providers", {}).items():
            api_key = env_values.get(spec.get("api_key_env", ""))
            model = spec.get("model") or env_values.get(spec.get("model_env", ""))
            self._providers[name] = {
                "base_url": spec["base_url"],
                "api_key": api_key,
                "model": model,
            }
            self._json_mode[name] = "json_schema"
            self._clients[name] = (
                self._factory(name, spec["base_url"], api_key, self._timeout)
                if api_key else None
            )

    @staticmethod
    def _default_client(name, base_url, api_key, timeout):
        return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)

    def _log(self, entry: dict) -> None:
        if not self._log_usage:
            return
        self._usage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._usage_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def _create(self, name: str, model: str, messages: list, schema: dict):
        client = self._clients[name]
        if self._json_mode[name] == "json_object":
            return client.chat.completions.create(
                model=model, messages=messages,
                response_format={"type": "json_object"},
            )
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "faultcase_response", "schema": schema},
                },
            )
        except Exception as exc:
            if _unsupported_format(exc):
                self._json_mode[name] = "json_object"
                return client.chat.completions.create(
                    model=model, messages=messages,
                    response_format={"type": "json_object"},
                )
            raise

    def call(self, role: str, messages: list, response_schema: dict) -> dict:
        """Call the role's providers in order; return the validated JSON dict."""
        return self.call_with_info(role, messages, response_schema)[0]

    def call_with_info(self, role: str, messages: list, response_schema: dict):
        """Call the role's route; return (validated data, successful attempt info)."""
        routes = self._config.get("routes", {})
        if role not in routes:
            raise RouterError(
                f"unknown role {role!r} (available: {', '.join(sorted(routes))})"
            )
        route = routes[role] or []
        errors: dict[str, str] = {}
        for index, name in enumerate(route):
            provider = self._providers[name]
            fallback_used = index > 0
            if not provider["api_key"]:
                errors[name] = "missing API key"
                self._log({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "role": role, "provider": name, "model": provider["model"],
                    "latency_ms": 0, "prompt_tokens": 0, "completion_tokens": 0,
                    "success": False, "fallback_used": fallback_used,
                })
                continue
            for attempt in range(self._max_retries + 1):
                start = time.perf_counter()
                prompt_tokens = completion_tokens = 0
                try:
                    completion = self._create(
                        name, provider["model"], messages, response_schema
                    )
                    try:
                        usage = completion.usage
                        prompt_tokens = usage.prompt_tokens or 0
                        completion_tokens = usage.completion_tokens or 0
                    except AttributeError:
                        pass
                    try:
                        content = completion.choices[0].message.content or ""
                    except (AttributeError, IndexError):
                        raise _InvalidResponse("malformed completion: no choices")
                    try:
                        data = json.loads(content)
                    except json.JSONDecodeError as exc:
                        raise _InvalidResponse(f"invalid JSON: {exc}")
                    try:
                        validate(instance=data, schema=response_schema)
                    except ValidationError as exc:
                        raise _InvalidResponse(f"schema validation failed: {exc.message}")
                    info = {
                        "provider": name, "model": provider["model"],
                        "latency_ms": int((time.perf_counter() - start) * 1000),
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "fallback_used": fallback_used,
                    }
                    self._log({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "role": role, **info, "success": True,
                    })
                    return data, info
                except _InvalidResponse as exc:
                    self._log({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "role": role, "provider": name, "model": provider["model"],
                        "latency_ms": int((time.perf_counter() - start) * 1000),
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "success": False, "fallback_used": fallback_used,
                    })
                    if attempt < self._max_retries:
                        continue
                    errors[name] = str(exc)
                    break
                except Exception as exc:
                    self._log({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "role": role, "provider": name, "model": provider["model"],
                        "latency_ms": int((time.perf_counter() - start) * 1000),
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "success": False, "fallback_used": fallback_used,
                    })
                    errors[name] = f"{type(exc).__name__}: {exc}"
                    break
        detail = "; ".join(f"{name} ({error})" for name, error in errors.items())
        raise RouterError(f"all providers failed for role {role!r}: {detail or 'empty route'}")


_default_router: Router | None = None


def call_with_info(role: str, messages: list, response_schema: dict):
    """Call the role's route with the default router (lazy singleton)."""
    global _default_router
    if _default_router is None:
        _default_router = Router()
    return _default_router.call_with_info(role, messages, response_schema)


def call(role: str, messages: list, response_schema: dict) -> dict:
    """Call the role's route with the default router (lazy singleton)."""
    return call_with_info(role, messages, response_schema)[0]
