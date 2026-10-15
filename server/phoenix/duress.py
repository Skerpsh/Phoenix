"""The duress code: a phrase that looks like an ordinary check-in but quietly starts the panic delivery.

Only a salted hash is stored. While the silent alarm is on, the bot keeps acting as if nothing happened.
"""

import hashlib
import hmac
import secrets

from .db import Store

DEFAULT_DELAY = 3600


def normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _digest(salt: str, phrase: str) -> str:
    return hashlib.scrypt(normalize(phrase).encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()


def set_code(store: Store, phrase: str) -> None:
    salt = secrets.token_hex(16)
    store.set("duress", {"salt": salt, "hash": _digest(salt, phrase)})


def clear_code(store: Store) -> None:
    store.delete("duress")


def is_code(store: Store, text: str | None) -> bool:
    saved = store.get("duress")
    if not saved or not text or not normalize(text):
        return False
    return hmac.compare_digest(saved["hash"], _digest(saved["salt"], text))


def delay(store: Store) -> int:
    return store.get("duress_delay", DEFAULT_DELAY)


def silent(store: Store) -> bool:
    """True while a silent alarm is on: the bot must look normal."""
    return store.get("silent_since") is not None
