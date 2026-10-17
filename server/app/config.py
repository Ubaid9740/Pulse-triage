"""Settings (from environment or server/.env) and the shared constants file."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = SERVER_DIR.parent
SHARED_DIR = REPO_DIR / "shared"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines; existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    db_path: Path
    keys_dir: Path
    shared_dir: Path = SHARED_DIR
    dashboard_dir: Path = REPO_DIR / "dashboard" / "dist"
    backups_dir: Path = SERVER_DIR / "backups"
    scenario_dir: Path = REPO_DIR / "scenario"
    port: int = 8000
    public_url: str | None = None
    # Development switches. Both become true once phones sign and seal (build hours 28-33).
    require_signatures: bool = False
    require_sealing: bool = False
    anthropic_api_key: str | None = None
    ai_enabled: bool = True                     # PT_AI=off: keyword rules only, never call the API

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(SERVER_DIR / ".env")
        return cls(
            db_path=Path(os.environ.get("PT_DB_PATH", SERVER_DIR / "pulsetriage.db")),
            keys_dir=Path(os.environ.get("PT_KEYS_DIR", SERVER_DIR / "keys")),
            backups_dir=Path(os.environ.get("PT_BACKUPS_DIR", SERVER_DIR / "backups")),
            scenario_dir=Path(os.environ.get("PT_SCENARIO_DIR", REPO_DIR / "scenario")),
            port=int(os.environ.get("PT_PORT", "8000")),
            public_url=os.environ.get("PT_PUBLIC_URL") or None,
            require_signatures=_flag("PT_REQUIRE_SIGNATURES", False),
            require_sealing=_flag("PT_REQUIRE_SEALING", False),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            ai_enabled=_flag("PT_AI", True),
        )


def load_constants(shared_dir: Path = SHARED_DIR) -> dict:
    return json.loads((shared_dir / "constants.json").read_text(encoding="utf-8"))
