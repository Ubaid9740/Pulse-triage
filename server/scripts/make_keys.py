"""Create the command post keys (or rotate them with --force).

    python server/scripts/make_keys.py [--force]

The server also creates keys on first start. After rotating, every phone must scan the new setup QR.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.crypto import CommandPostKeys  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="replace existing keys")
    args = parser.parse_args()
    keys_dir = Settings.from_env().keys_dir
    if (keys_dir / "cp_sign.key").exists() and not args.force:
        keys = CommandPostKeys.load(keys_dir)
        print(f"Keys already exist in {keys_dir} (use --force to rotate).")
    else:
        keys = CommandPostKeys.generate()
        keys.save(keys_dir)
        print(f"Wrote new keys to {keys_dir}. Phones must scan the new setup QR.")
    print(f"sign_pk: {keys.sign_pk}\nbox_pk:  {keys.box_pk}")


if __name__ == "__main__":
    main()
