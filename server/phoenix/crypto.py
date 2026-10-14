import subprocess
from pathlib import Path


class CryptoError(Exception):
    pass


class Crypto:
    """Decrypts files that the CLI encrypted with this server's age public key."""

    def __init__(self, identity: Path):
        self.identity = identity

    def _run(self, *args: str) -> bytes:
        r = subprocess.run(["age", "-d", "-i", str(self.identity), *args], capture_output=True)
        if r.returncode:
            raise CryptoError(r.stderr.decode(errors="replace").strip() or "age failed")
        return r.stdout

    def decrypt_bytes(self, src: Path) -> bytes:
        return self._run(str(src))

    def decrypt_to(self, src: Path, dst: Path) -> None:
        self._run("-o", str(dst), str(src))
