"""Symmetric encryption for secrets that must survive a restart.

Used only for node SSH credentials. The admin chose to keep them so upgrades and
repairs can be re-run from the UI, which means the database holds root-equivalent
logins for every GPU server — so they are encrypted at rest with a key that lives
in the environment (``SECRETS_KEY``), not in the database.

The key is a passphrase of any length: it is stretched to a Fernet key so that
``openssl rand -hex 32`` output works directly and operators never have to know
what base64-urlsafe-32 means.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class SecretDecryptError(Exception):
    """The stored ciphertext could not be read with the current SECRETS_KEY."""


@lru_cache
def _fernet(key: str) -> Fernet:
    # SHA-256 of the passphrase gives exactly the 32 bytes Fernet wants.
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for storage. Returns URL-safe base64 text."""
    return _fernet(get_settings().secrets_key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Decrypt a stored secret.

    Raises SecretDecryptError when SECRETS_KEY has changed since it was written —
    a distinct failure from "there is no secret", and one worth telling the admin
    about in those terms rather than as a generic 500.
    """
    try:
        return _fernet(get_settings().secrets_key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretDecryptError(
            "Stored credential cannot be decrypted; SECRETS_KEY has changed "
            "since it was saved. Re-enter the credential for this node."
        ) from exc
