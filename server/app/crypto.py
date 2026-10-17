"""Command post keys, signatures and sealed boxes (libsodium via PyNaCl).

Phones sign the exact UTF-8 bytes of the body text with Ed25519 and seal private payloads
to the command post's X25519 box key. The server signs alerts, jobs and revocations.
"""
from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass
from pathlib import Path

from nacl.exceptions import BadSignatureError, CryptoError
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey, VerifyKey

log = logging.getLogger("pulsetriage.crypto")

SIGN_FILE = "cp_sign.key"
BOX_FILE = "cp_box.key"


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    """Strict base64 decode. Raises ValueError on bad input."""
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("not valid base64") from exc


@dataclass
class CommandPostKeys:
    signing: SigningKey
    box: PrivateKey

    @property
    def sign_pk(self) -> str:
        return b64e(bytes(self.signing.verify_key))

    @property
    def box_pk(self) -> str:
        return b64e(bytes(self.box.public_key))

    def sign(self, text: str) -> str:
        return b64e(self.signing.sign(text.encode("utf-8")).signature)

    def unseal(self, sealed_b64: str) -> bytes:
        """Raises ValueError if the payload was not sealed to this command post."""
        try:
            return SealedBox(self.box).decrypt(b64d(sealed_b64))
        except CryptoError as exc:
            raise ValueError("cannot unseal") from exc

    @classmethod
    def generate(cls) -> "CommandPostKeys":
        return cls(SigningKey.generate(), PrivateKey.generate())

    def save(self, keys_dir: Path) -> None:
        keys_dir.mkdir(parents=True, exist_ok=True)
        (keys_dir / SIGN_FILE).write_text(b64e(bytes(self.signing)), encoding="ascii")
        (keys_dir / BOX_FILE).write_text(b64e(bytes(self.box)), encoding="ascii")

    @classmethod
    def load(cls, keys_dir: Path) -> "CommandPostKeys":
        signing = SigningKey(b64d((keys_dir / SIGN_FILE).read_text(encoding="ascii").strip()))
        box = PrivateKey(b64d((keys_dir / BOX_FILE).read_text(encoding="ascii").strip()))
        return cls(signing, box)

    @classmethod
    def load_or_create(cls, keys_dir: Path) -> "CommandPostKeys":
        if (keys_dir / SIGN_FILE).exists() and (keys_dir / BOX_FILE).exists():
            return cls.load(keys_dir)
        keys = cls.generate()
        keys.save(keys_dir)
        log.warning("Created new command post keys in %s. Phones must scan the new setup QR.", keys_dir)
        return keys


def verify(pubkey_b64: str, body_text: str, sig_b64: str) -> bool:
    try:
        VerifyKey(b64d(pubkey_b64)).verify(body_text.encode("utf-8"), b64d(sig_b64))
        return True
    except (BadSignatureError, ValueError, CryptoError):
        return False


def seal(box_pk_b64: str, data: bytes) -> str:
    """What a phone does: seal a payload to the command post. Used by tests and dev tools."""
    return b64e(SealedBox(PublicKey(b64d(box_pk_b64))).encrypt(data))
