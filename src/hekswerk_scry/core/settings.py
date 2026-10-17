"""Settings from the environment, with a `.env` file as a fallback.

    OPENROUTER_API_KEY   needed for the AI helper (`scry chat`)
    OPENROUTER_BASE_URL  default https://openrouter.ai/api/v1
    SCRY_MODEL           default anthropic/claude-opus-5.5
    SCRY_EFFORT          how hard the model thinks: low, medium, high, xhigh, max (default high)

Variables already set in the environment win over the `.env` file. The `.env` file is
read from the current folder or the nearest folder above it that has one.
"""

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "anthropic/claude-opus-5.5"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


class SettingsError(ValueError):
    """A setting is missing or not usable. The message says how to fix it."""


def read_dotenv(path: Path) -> dict[str, str]:
    """Read KEY=value lines. Blank lines and lines starting with # are ignored."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def find_dotenv(start: Path) -> Path | None:
    here = start.resolve()
    for folder in (here, *here.parents):
        candidate = folder / ".env"
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class AISettings:
    api_key: str
    base_url: str
    model: str
    effort: str

    def __repr__(self) -> str:  # never print the key
        return (f"AISettings(model={self.model!r}, effort={self.effort!r}, "
                f"base_url={self.base_url!r})")


def load_ai_settings(start: Path | None = None) -> AISettings:
    dotenv = find_dotenv(start or Path.cwd())
    file_values = read_dotenv(dotenv) if dotenv else {}

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key) or file_values.get(key) or default

    api_key = get("OPENROUTER_API_KEY")
    if not api_key:
        raise SettingsError(
            "OPENROUTER_API_KEY is not set. Put `OPENROUTER_API_KEY=...` in a `.env` file "
            "at the repository root (it is ignored by git), or set it in the environment."
        )
    effort = get("SCRY_EFFORT", "high").lower()
    if effort not in EFFORT_LEVELS:
        raise SettingsError(
            f"SCRY_EFFORT is '{effort}', but it should be one of: {', '.join(EFFORT_LEVELS)}."
        )
    return AISettings(
        api_key=api_key,
        base_url=get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        model=get("SCRY_MODEL", DEFAULT_MODEL),
        effort=effort,
    )
