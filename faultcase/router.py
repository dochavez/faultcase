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
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


class _TruncatedResponse(_InvalidResponse):
    """finish_reason=length: truncated output, retry the same provider once."""


class _RaceFailed(Exception):
    """Both hedged providers failed (errors already recorded)."""


def _unsupported_format(error: Exception) -> bool:
    text = str(error).lower()
    return "response_format" in text or "json_schema" in text


def _unsupported_param(error: Exception, param: str) -> bool:
    text = str(error).lower()
    if param not in text:
        return False
    return any(
        word in text
        for word in (
            "unknown", "unsupported", "invalid", "unexpected",
            "unrecognized", "not supported", "not allowed",
        )
    )


def _cached_tokens(usage) -> int:
    """Read cached prompt tokens from an OpenAI usage object (0 if absent)."""
    details = getattr(usage, "prompt_tokens_details", None)
    if details is None:
        return 0
    if isinstance(details, dict):
        return details.get("cached_tokens") or 0
    return getattr(details, "cached_tokens", None) or 0


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
        self._log_lock = threading.Lock()
        options = config.get("settings", {})
        self._timeout = float(options.get("timeout_seconds", 90))
        self._max_retries = int(options.get("max_retries_per_provider", 1))
        self._hedge_after = float(options.get("hedge_after_seconds", 25))
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
        self._no_reasoning_effort: set[str] = set()
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
        with self._log_lock:
            self._usage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._usage_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")

    def analysis_mode(self, role: str) -> str:
        """Return "second_opinion" or "single" for a role (default "single")."""
        roles = self._config.get("roles", {})
        return roles.get(role, {}).get("analysis_mode", "single")

    def reasoning_effort(self, role: str):
        """Return the role's reasoning effort (or None when unset)."""
        roles = self._config.get("roles", {})
        return roles.get(role, {}).get("reasoning_effort")

    def max_tokens(self, role: str):
        """Return the role's max_tokens cap (or None when unset)."""
        roles = self._config.get("roles", {})
        return roles.get(role, {}).get("max_tokens")

    def _create(
        self, name: str, model: str, messages: list, schema: dict, role: str
    ):
        effort = self.reasoning_effort(role)
        if name in self._no_reasoning_effort:
            effort = None
        cap = self.max_tokens(role)
        try:
            return self._create_with_format(
                name, model, messages, schema, effort, cap
            )
        except Exception as exc:
            if effort is not None and _unsupported_param(exc, "reasoning_effort"):
                self._no_reasoning_effort.add(name)
                return self._create_with_format(
                    name, model, messages, schema, None, cap
                )
            raise

    def _create_with_format(
        self, name: str, model: str, messages: list, schema: dict,
        effort=None, cap=None,
    ):
        client = self._clients[name]
        extra = {"reasoning_effort": effort} if effort is not None else {}
        if cap is not None:
            extra["max_tokens"] = cap
        if self._json_mode[name] == "json_object":
            return client.chat.completions.create(
                model=model, messages=messages,
                response_format={"type": "json_object"}, **extra,
            )
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "faultcase_response", "schema": schema},
                },
                **extra,
            )
        except Exception as exc:
            if _unsupported_format(exc):
                self._json_mode[name] = "json_object"
                return client.chat.completions.create(
                    model=model, messages=messages,
                    response_format={"type": "json_object"}, **extra,
                )
            raise

    def call(self, role: str, messages: list, response_schema: dict) -> dict:
        """Call the role's providers in order; return the validated JSON dict."""
        return self.call_with_info(role, messages, response_schema)[0]

    def _attempt_provider(
        self, name: str, provider: dict, role: str, messages: list,
        schema: dict, fallback_used: bool = False,
    ):
        """Call one provider (retry once on invalid JSON); return (data, info).

        Raises the last error: _InvalidResponse after retries, anything else
        immediately. Every attempt is logged.
        """
        for attempt in range(self._max_retries + 1):
            start = time.perf_counter()
            prompt_tokens = completion_tokens = cached_tokens = 0
            try:
                completion = self._create(
                    name, provider["model"], messages, schema, role
                )
                try:
                    usage = completion.usage
                    prompt_tokens = usage.prompt_tokens or 0
                    completion_tokens = usage.completion_tokens or 0
                    cached_tokens = _cached_tokens(usage)
                except AttributeError:
                    pass
                try:
                    choice = completion.choices[0]
                except (AttributeError, IndexError):
                    raise _InvalidResponse("malformed completion: no choices")
                if getattr(choice, "finish_reason", None) == "length":
                    raise _TruncatedResponse(
                        "truncated response: finish_reason=length"
                    )
                try:
                    content = choice.message.content or ""
                except AttributeError:
                    raise _InvalidResponse("malformed completion: no message")
                try:
                    data = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise _InvalidResponse(f"invalid JSON: {exc}")
                try:
                    validate(instance=data, schema=schema)
                except ValidationError as exc:
                    raise _InvalidResponse(f"schema validation failed: {exc.message}")
                info = {
                    "provider": name, "model": provider["model"],
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cached_tokens": cached_tokens,
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
                    "cached_tokens": cached_tokens,
                    "truncated": isinstance(exc, _TruncatedResponse),
                    "success": False, "fallback_used": fallback_used,
                })
                if attempt < self._max_retries:
                    continue
                raise
            except Exception:
                self._log({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "role": role, "provider": name, "model": provider["model"],
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cached_tokens": cached_tokens,
                    "success": False, "fallback_used": fallback_used,
                })
                raise

    def _failure(self, role: str, name: str, error: Exception | str) -> dict:
        provider = self._providers[name]
        message = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
        return {
            "provider": name, "model": provider["model"], "success": False,
            "data": None, "info": None, "error": message,
        }

    def _log_missing_key(self, role: str, name: str, fallback_used: bool) -> None:
        provider = self._providers[name]
        self._log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "role": role, "provider": name, "model": provider["model"],
            "latency_ms": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "cached_tokens": 0,
            "success": False, "fallback_used": fallback_used,
        })

    def _race(
        self, role: str, first: str, second: str, messages: list,
        schema: dict, errors: dict, route: list,
    ):
        """Race two keyed providers; return (data, info) or raise _RaceFailed.

        The second provider only starts if the first one is still running
        after hedge_after_seconds. The first valid answer wins; the loser
        is ignored (its daemon thread just finishes in the background).
        A hedge summary line records which provider won.
        """
        results: queue.Queue = queue.Queue()

        def leg(name: str) -> None:
            try:
                data, info = self._attempt_provider(
                    name, self._providers[name], role, messages, schema,
                    route.index(name) > 0,
                )
            except _InvalidResponse as exc:
                results.put((name, None, None, str(exc)))
            except Exception as exc:  # noqa: BLE001 - captured, not raised
                results.put((name, None, None, f"{type(exc).__name__}: {exc}"))
            else:
                results.put((name, data, info, None))

        def start(name: str) -> None:
            thread = threading.Thread(target=leg, args=(name,), daemon=True)
            thread.start()

        start(first)
        try:
            name, data, info, error = results.get(
                timeout=max(0.0, self._hedge_after)
            )
        except queue.Empty:
            pass
        else:
            if error is None:
                return data, info
            errors[name] = error
            try:
                return self._attempt_provider(
                    second, self._providers[second], role, messages, schema,
                    route.index(second) > 0,
                )
            except _InvalidResponse as exc:
                errors[second] = str(exc)
            except Exception as exc:
                errors[second] = f"{type(exc).__name__}: {exc}"
            raise _RaceFailed
        start(second)
        try:
            name, data, info, error = results.get(
                timeout=max(1.0, 2 * self._timeout + 5)
            )
        except queue.Empty:
            errors[first] = errors[second] = "hedge leg timed out"
            raise _RaceFailed
        if error is None:
            loser = second if name == first else first
            self._log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "role": role, "event": "hedge",
                "providers": [first, second], "winner": name,
                "ignored": loser, "winner_latency_ms": info["latency_ms"],
            })
            return data, info
        errors[name] = error
        try:
            name, data, info, error = results.get(
                timeout=max(1.0, 2 * self._timeout)
            )
        except queue.Empty:
            other = second if name == first else first
            errors[other] = "hedge leg timed out"
            raise _RaceFailed
        if error is None:
            loser = second if name == first else first
            self._log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "role": role, "event": "hedge",
                "providers": [first, second], "winner": name,
                "ignored": loser, "winner_latency_ms": info["latency_ms"],
            })
            return data, info
        errors[name] = error
        raise _RaceFailed

    def call_with_info(self, role: str, messages: list, response_schema: dict):
        """Call the role's route; return (validated data, successful attempt info)."""
        routes = self._config.get("routes", {})
        if role not in routes:
            raise RouterError(
                f"unknown role {role!r} (available: {', '.join(sorted(routes))})"
            )
        route = routes[role] or []
        errors: dict[str, str] = {}
        keyed = []
        for index, name in enumerate(route):
            if self._providers[name]["api_key"]:
                keyed.append(name)
            else:
                errors[name] = "missing API key"
                self._log_missing_key(role, name, index > 0)
        rest = keyed
        if len(keyed) >= 2:
            try:
                return self._race(
                    role, keyed[0], keyed[1], messages, response_schema,
                    errors, route,
                )
            except _RaceFailed:
                rest = keyed[2:]
        for name in rest:
            try:
                return self._attempt_provider(
                    name, self._providers[name], role, messages,
                    response_schema, route.index(name) > 0,
                )
            except _InvalidResponse as exc:
                errors[name] = str(exc)
            except Exception as exc:
                errors[name] = f"{type(exc).__name__}: {exc}"
        detail = "; ".join(f"{name} ({error})" for name, error in errors.items())
        raise RouterError(f"all providers failed for role {role!r}: {detail or 'empty route'}")

    def call_parallel(self, role: str, messages: list, response_schema: dict) -> list:
        """Call the first two providers of the role's route concurrently.

        Returns one result dict per provider in route order:
        {"provider", "model", "success", "data", "info", "error"}.
        Per-provider failures are captured, never raised.
        """
        routes = self._config.get("routes", {})
        if role not in routes:
            raise RouterError(
                f"unknown role {role!r} (available: {', '.join(sorted(routes))})"
            )
        names = (routes[role] or [])[:2]

        def run(name: str) -> dict:
            provider = self._providers[name]
            if not provider["api_key"]:
                self._log({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "role": role, "provider": name, "model": provider["model"],
                    "latency_ms": 0, "prompt_tokens": 0, "completion_tokens": 0,
                    "cached_tokens": 0,
                    "success": False, "fallback_used": False,
                })
                return self._failure(role, name, "missing API key")
            try:
                data, info = self._attempt_provider(
                    name, provider, role, messages, response_schema
                )
            except _InvalidResponse as exc:
                return self._failure(role, name, str(exc))
            except Exception as exc:
                return self._failure(role, name, exc)
            return {
                "provider": name, "model": provider["model"], "success": True,
                "data": data, "info": info, "error": None,
            }

        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(run, name): name for name in names}
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        return [results[name] for name in names]


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


def call_parallel_with_info(role: str, messages: list, response_schema: dict) -> list:
    """Call the role's first two providers concurrently (lazy singleton)."""
    global _default_router
    if _default_router is None:
        _default_router = Router()
    return _default_router.call_parallel(role, messages, response_schema)


def analysis_mode(role: str) -> str:
    """Return the role's analysis mode ("second_opinion" or "single")."""
    global _default_router
    if _default_router is None:
        _default_router = Router()
    return _default_router.analysis_mode(role)
