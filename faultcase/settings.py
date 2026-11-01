"""Application settings loaded from environment variables.

Values come from the process environment first; a ``.env`` file in the
project root is loaded as a fallback and never overrides variables that
are already set.

API keys are secret: this module never prints or logs a full key value,
only whether it is set and its last 4 characters.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASETEN_MODEL_DEFAULT = "meta-models/muse-spark-open-1026"


def mask_secret(value: str | None) -> str:
    """Return a safe summary of a secret: set/not set plus last 4 chars."""
    if not value:
        return "not set"
    return f"set (last4 ...{value[-4:]})"


@dataclass(frozen=True)
class Settings:
    meta_api_key: str | None
    baseten_api_key: str | None
    fireworks_api_key: str | None
    baseten_model: str
    invite_code: str | None = None

    def key_status(self) -> dict[str, str]:
        """Masked status of each API key (never the full value)."""
        return {
            "META_API_KEY": mask_secret(self.meta_api_key),
            "BASETEN_API_KEY": mask_secret(self.baseten_api_key),
            "FIREWORKS_API_KEY": mask_secret(self.fireworks_api_key),
        }


def load_settings(dotenv_path: str | Path | None = None) -> Settings:
    """Load settings from the environment, falling back to a ``.env`` file."""
    if dotenv_path is None:
        candidate = Path.cwd() / ".env"
        dotenv_path = candidate if candidate.exists() else None
    load_dotenv(dotenv_path=dotenv_path, override=False)
    return Settings(
        meta_api_key=os.environ.get("META_API_KEY") or None,
        baseten_api_key=os.environ.get("BASETEN_API_KEY") or None,
        fireworks_api_key=os.environ.get("FIREWORKS_API_KEY") or None,
        baseten_model=os.environ.get("BASETEN_MODEL") or BASETEN_MODEL_DEFAULT,
        invite_code=os.environ.get("INVITE_CODE") or None,
    )


settings = load_settings()


if __name__ == "__main__":
    loaded = load_settings()
    for name, status in loaded.key_status().items():
        print(f"{name}: {status}")
    print(f"BASETEN_MODEL: {loaded.baseten_model}")
