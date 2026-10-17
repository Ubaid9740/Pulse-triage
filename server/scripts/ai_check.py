"""Check the AI reader against the real API (Gemini or Claude): one message in, the reading out.

    python server/scripts/ai_check.py
    python server/scripts/ai_check.py "Family of 6 on the roof near the old bridge, water rising"

Needs GEMINI_API_KEY (or ANTHROPIC_API_KEY with PT_AI_PROVIDER=claude) in the environment or
server/.env. Uses a throwaway database, so the server's data is untouched. One call.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai_reader import AIReader  # noqa: E402
from app.cases import CaseBook  # noqa: E402
from app.config import SHARED_DIR, Settings, load_constants  # noqa: E402
from app.db import Database  # noqa: E402
from app.profiles import Profiles  # noqa: E402
from app.reader import KeywordReader  # noqa: E402
from app.schemas import Schemas  # noqa: E402

SAMPLE = "Old man alone behind the green mosque, house 14. Water up to his chest now and rising, his oxygen is nearly out"


def main(argv: list[str] | None = None) -> int:
    text = " ".join(argv if argv is not None else sys.argv[1:]) or SAMPLE
    settings = Settings.from_env()                       # loads server/.env into the environment
    constants = load_constants(SHARED_DIR)
    profiles = Profiles(SHARED_DIR, Schemas(SHARED_DIR))
    with tempfile.TemporaryDirectory() as folder:
        db = Database(Path(folder) / "check.db")
        ai = AIReader(db, profiles, CaseBook(db, profiles, constants), constants, provider=settings.ai_provider)
        print(f"Provider: {ai.backend.name} ({ai.backend.model})")
        print("Keywords:", json.dumps(KeywordReader(profiles).read(text).__dict__, default=str))
        print("Health:  ", "online" if ai.check() else f"offline ({ai.last_error})")
        answer = ai.read(text)
        db.close()
    if answer is None:
        print(f"AI:       no reading ({ai.last_error or 'declined or nothing usable'})")
        return 1
    print("AI:      ", json.dumps(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
