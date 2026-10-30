"""Smoke test: one minimal chat call to each configured provider.

Reads model endpoints from config/providers.yaml and credentials from
faultcase.settings (environment variables with .env fallback). Each model
is asked to reply with only the word "ok".

Usage (from the project root):
    python scripts/smoke_test.py

Exit code is 1 if any provider failed, 0 if all succeeded.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import yaml
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from faultcase.settings import load_settings  # noqa: E402

PROVIDERS = ("meta", "baseten", "fireworks")
PROMPT = 'Reply with only the word "ok".'


def main() -> int:
    settings = load_settings()
    env_values = {
        "META_API_KEY": settings.meta_api_key,
        "BASETEN_API_KEY": settings.baseten_api_key,
        "FIREWORKS_API_KEY": settings.fireworks_api_key,
        "BASETEN_MODEL": settings.baseten_model,
    }
    with open(ROOT / "config" / "providers.yaml", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    timeout = float(config.get("settings", {}).get("timeout_seconds", 90))

    failures = 0
    for name in PROVIDERS:
        spec = config["providers"][name]
        model = spec.get("model") or env_values.get(spec.get("model_env", ""), "")
        api_key = env_values.get(spec["api_key_env"])
        print(f"=== {name} ===")
        print(f"model: {model}")
        if not api_key:
            print(f"status: ERROR (missing {spec['api_key_env']})")
            print(f"error: {type(KeyError).__name__}: no value for {spec['api_key_env']}")
            failures += 1
            continue
        client = OpenAI(base_url=spec["base_url"], api_key=api_key, timeout=timeout)
        start = time.perf_counter()
        try:
            raw = client.chat.completions.with_raw_response.create(
                model=model,
                messages=[{"role": "user", "content": PROMPT}],
                temperature=0,
                max_tokens=256,  # reasoning models need room beyond thinking tokens
            )
            completion = raw.parse()
        except Exception as exc:  # one provider must not stop the others
            latency_ms = int((time.perf_counter() - start) * 1000)
            print("status: ERROR")
            print(f"latency_ms: {latency_ms}")
            print(f"error: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        latency_ms = int((time.perf_counter() - start) * 1000)
        usage = completion.usage
        reply = ""
        if completion.choices:
            reply = (completion.choices[0].message.content or "").strip()
        print(f"status: {raw.status_code}")
        print(f"finish_reason: {completion.choices[0].finish_reason if completion.choices else 'n/a'}")
        print(f"latency_ms: {latency_ms}")
        print(f"prompt_tokens: {usage.prompt_tokens if usage else 'n/a'}")
        print(f"completion_tokens: {usage.completion_tokens if usage else 'n/a'}")
        print(f"reply: {reply}")

    print(f"--- {len(PROVIDERS) - failures}/{len(PROVIDERS)} providers OK ---")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
