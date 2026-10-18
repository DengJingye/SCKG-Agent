"""Explicitly unlocked local credentials; never imports legacy configuration."""
from __future__ import annotations

import base64
import json
import os
import secrets
import tempfile
from contextlib import contextmanager
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class VaultError(ValueError):
    pass


class VaultLockedError(VaultError):
    pass


class SecretVault:
    """AES-256-GCM vault, with fixed Scrypt parameters and atomic private writes."""

    _AAD = b"sckg-workbench-credential-vault-v1"

    def __init__(self, path: Path):
        self.path = Path(path)
        self._unlocked: dict[str, str] | None = None

    @property
    def locked(self) -> bool:
        return self._unlocked is None

    def lock(self) -> None:
        self._unlocked = None

    @staticmethod
    def _key(passphrase: str, salt: bytes) -> bytes:
        if not isinstance(passphrase, str) or len(passphrase) < 8:
            raise VaultError("Vault passphrase must contain at least 8 characters")
        return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(passphrase.encode())

    def _read(self, passphrase: str) -> dict[str, str]:
        if self.path.is_symlink():
            raise VaultError("Vault symlinks are not permitted")
        if not self.path.exists():
            self._key(passphrase, b"validation-only!")
            return {}
        try:
            payload = json.loads(self.path.read_text())
            if payload["version"] != 1:
                raise ValueError("version")
            salt = base64.b64decode(payload["salt"], validate=True)
            nonce = base64.b64decode(payload["nonce"], validate=True)
            ciphertext = base64.b64decode(payload["ciphertext"], validate=True)
            if len(salt) != 16 or len(nonce) != 12:
                raise ValueError("length")
            clear = AESGCM(self._key(passphrase, salt)).decrypt(nonce, ciphertext, self._AAD)
            records = json.loads(clear)
            if not isinstance(records, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in records.items()
            ):
                raise ValueError("records")
            return records
        except InvalidTag as exc:
            raise VaultLockedError("Incorrect passphrase or damaged vault") from exc
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise VaultError("Vault could not be read or authenticated") from exc

    def unlock(self, passphrase: str) -> None:
        self.lock()
        self._unlocked = self._read(passphrase)

    def get_secret(self, secret_id: str) -> str:
        if self.locked:
            raise VaultLockedError("Vault is locked")
        if secret_id not in self._unlocked:
            raise VaultError("Credential reference does not exist")
        return self._unlocked[secret_id]

    @contextmanager
    def _write_lock(self):
        # Supported local desktop hosts provide fcntl; no network lock service.
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def set_secret(self, secret_id: str, value: str, passphrase: str) -> None:
        if not isinstance(secret_id, str) or not secret_id or not isinstance(value, str) or not value:
            raise VaultError("A credential reference and nonempty secret are required")
        self.lock()
        with self._write_lock():
            records = self._read(passphrase)
            if secret_id in records and records[secret_id] != value:
                raise VaultError("Credential revisions are immutable; create a new reference")
            records[secret_id] = value
            salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
            ciphertext = AESGCM(self._key(passphrase, salt)).encrypt(
                nonce, json.dumps(records, separators=(",", ":")).encode(), self._AAD
            )
            payload = {"version": 1, "salt": _b64(salt), "nonce": _b64(nonce), "ciphertext": _b64(ciphertext)}
            descriptor, temporary = tempfile.mkstemp(prefix=".vault-", dir=self.path.parent)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w") as handle:
                    json.dump(payload, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")
