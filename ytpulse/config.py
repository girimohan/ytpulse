from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

DATA_DIR = Path(__file__).parent / "data"


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings(path: str | os.PathLike | None = None) -> dict:
    base = yaml.safe_load((DATA_DIR / "default_settings.yaml").read_text(encoding="utf-8"))
    if path:
        base = _merge(base, yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
    return base


def load_entities(path: str | os.PathLike | None = None) -> list[dict]:
    p = Path(path) if path else DATA_DIR / "entities.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))["entities"]


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: str = ".env") -> None:
    """Tiny .env loader so the API key never has to live in code or shell history.

    Looks in the current directory first, then in the project folder, so the tool
    works no matter where it is launched from.
    """
    for p in (Path(path), PROJECT_ROOT / ".env"):
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api_key() -> str:
    load_dotenv()
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "YOUTUBE_API_KEY is not set. Create a key (YouTube Data API v3) and put it in "
            "a .env file as YOUTUBE_API_KEY=... or set the environment variable."
        )
    return key
