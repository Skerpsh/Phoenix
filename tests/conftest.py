"""Every test runs in a throwaway home: nothing touches your real settings, packages or vault."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = Path(tempfile.mkdtemp(prefix="phoenix-tests-"))
os.environ.update(
    HOME=str(SANDBOX / "home"),
    XDG_CONFIG_HOME=str(SANDBOX / "config"),
    XDG_CACHE_HOME=str(SANDBOX / "cache"),
    XDG_DATA_HOME=str(SANDBOX / "data"),
    PHOENIX_VAULT=str(SANDBOX / "vault"),  # never the vault of a developer's own checkout
)
sys.path[:0] = [str(ROOT / "cli"), str(ROOT / "server")]

if not shutil.which("age"):
    pytest.exit("these tests need `age` installed", returncode=1)


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A fresh server data folder with its age key, created the way the real server does it.

    Returns (server config, public key, data folder).
    """
    import contextlib
    import io

    from phoenix import config, keygen

    data = tmp_path / "server" / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        keygen.main()
    return config.load(), out.getvalue().strip(), data
