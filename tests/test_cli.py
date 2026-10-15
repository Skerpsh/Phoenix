"""The `phoenix` command: package checks, the encrypted upload, and the menu driven like a user would."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import push_locally, write_meta
from phx import packages as pk
from phx import ui
from phx.core import Failed

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("raw, expected", [
    ("@alice_1", "@alice_1"), ("alice_1", "@alice_1"), ("https://t.me/alice_1", "@alice_1"), ("t.me/alice_1/", "@alice_1"),
    ("+380 50 123-45-67", "+380501234567"), ("123456789", "123456789"), ("al", None), ("hello world", None),
])
def test_telegram_input(raw, expected):
    assert ui.normalize_telegram(raw) == expected


@pytest.mark.parametrize("seconds", [60, 3600, 86400, 90000, 365 * 86400 + 6 * 86400])
def test_durations_round_trip(seconds):
    from phoenix import durations
    assert durations.parse(pk.dur_str(seconds)) == seconds


def test_problems_are_explained(tmp_path):
    d = tmp_path / "mom"
    write_meta(d, name="Mom")
    problems = pk.read_package(d)[2]
    assert any("Telegram is not set" in p for p in problems)
    assert any("nothing to send" in p for p in problems)

    write_meta(d, name="Mom", telegram="@mom")
    (d / "01-letter.txt").write_text(f"{pk.TEMPLATE_MARK} delete me\nHi")
    assert any("template" in p for p in pk.read_package(d)[2])
    (d / "01-letter.txt").write_text("Hi")
    assert pk.read_package(d)[2] == []


def test_old_settings_file_is_hidden(tmp_path):
    d = tmp_path / "mom"
    d.mkdir()
    (d / "recipient.toml").write_text('# comment\nname = "Mom"\ntelegram = "@mom"\ndelay = "3d"\n')
    pk.migrate(tmp_path)
    assert not (d / "recipient.toml").exists() and (d / pk.RECIPIENT_FILE).exists()
    meta = pk.load_meta(d)
    assert meta["telegram"] == "@mom" and meta["delay"] == 3 * 86400


def test_upload_is_encrypted_and_incremental(server, tmp_path, capsys):
    cfg, public_key, data = server
    packages = tmp_path / "packages"
    write_meta(packages / "mom", name="Mom", telegram="@mom")
    (packages / "mom" / "01-passwords.txt").write_text("bank: 1234")
    push_locally(packages, public_key, data)
    assert "encrypting" in capsys.readouterr().out

    files = list((data / "packages").rglob("*"))
    assert files and not any("mom" in str(f) or "passwords" in str(f) for f in files)
    assert all(b"1234" not in f.read_bytes() for f in files if f.is_file())

    from phoenix.crypto import Crypto
    from phoenix.packages import load_all
    loaded = load_all(data / "packages", Crypto(cfg.identity_path))
    assert [p.name for p in loaded.packages] == ["Mom"] and not loaded.errors

    push_locally(packages, public_key, data)
    assert "encrypting" not in capsys.readouterr().out, "unchanged files are not encrypted again"
    assert pk.is_uploaded(packages)


def test_upload_refuses_problems(server, tmp_path):
    _, public_key, data = server
    write_meta(tmp_path / "packages" / "mom", name="Mom")
    with pytest.raises(Failed, match="Telegram is not set"):
        push_locally(tmp_path / "packages", public_key, data)


def test_menu_end_to_end(server, tmp_path):
    """Drive the menu with typed answers; ssh/rsync are stubs that run the server side locally."""
    cfg, public_key, data = server
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ssh").write_text(f"""#!/bin/sh
for last; do :; done
cmd=$(printf '%s' "$last" | sed -e 's#^cd [^ ]* && ##' \\
  -e 's#docker compose exec -T phoenix python#{sys.executable}#' -e 's#docker compose#echo docker#g')
cd {ROOT / "server"} && sh -c "$cmd"
""")
    (bin_dir / "rsync").write_text("#!/bin/sh\necho rsync-stub\n")
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)

    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", DATA_DIR=str(data),
               XDG_CONFIG_HOME=str(home / "config"), XDG_CACHE_HOME=str(home / "cache"),
               XDG_DATA_HOME=str(home / "data"), PYTHONPATH="")
    config = home / "config" / "phoenix" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"server": "root@test", "remote_dir": "/opt/phoenix", "public_key": public_key,
                                  "packages_dir": str(home / "packages")}))

    answers = [
        "1",                         # I'm OK
        "9", "1", "5d", "",          # Timers → check in every 5d → back
        "8", "2w",                   # Pause for 2 weeks
        "8",                         # End the pause
        "2", "1", "Mom", "mom_test",  # Recipients → add
        "1", "1", "Hi mom", "", "", "1",  # write a message myself, send together with the rest
        "", "",                      # back, back
        "4", "1", "Bye", "", "", "",  # account → auto-reply → back
        "11", "1", "Future me", "1", "2099-01-01",  # time capsules → new → to myself, on a date
        "1", "1", "Hello future", "", "",  # write a message in it (no scheduling question)
        "", "",                      # back, back
        "3", "1", "",                # timeline if I stop checking in
        "5", "",                     # upload
        "12", "1", "all good", "all good", "",  # duress code → set it (typed twice) → back
        "13", "",                    # history
        "16",                        # quit
    ]
    r = subprocess.run([sys.executable, str(ROOT / "cli" / "phoenix")], input="\n".join(answers) + "\n",
                       env=env, capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    for expected in ["Check-in recorded", "Saved: 5d", "Paused for 14d", "Pause ended", "Added Mom",
                     "Message saved", '"Bye"', "Uploaded", "check-in from the CLI", "Mom: 1 message",
                     "Auto-reply turns on", "time capsule “Future me” → me", "on 2099-01-01 at 09:00"]:
        assert expected in out, f"{expected!r} missing in:\n{out}"
    from phx import art
    assert any(phrase in out for phrase in art.FAREWELLS), "a farewell phrase on the way out"
    assert (home / "packages" / "Mom" / "01-message.txt").read_text() == "Hi mom\n"

    from phoenix import duress
    from phoenix.db import Store
    store = Store(data / "phoenix.db")
    assert "Duress code saved" in out
    assert duress.is_code(store, "All Good") and not duress.is_code(store, "all good!")


def test_legacy_vault_moves_out_of_the_code(tmp_path, monkeypatch):
    from phx import core

    code, data = tmp_path / "code", tmp_path / "data"
    (code / "vault").mkdir(parents=True)
    (code / "vault" / "gocryptfs.conf").write_text("{}")
    (code / "vault" / "encrypted-file").write_text("x")
    monkeypatch.delenv("PHOENIX_VAULT")
    monkeypatch.setattr(core, "ROOT", code)
    monkeypatch.setattr(core, "DATA", data)
    monkeypatch.setattr(core, "VAULT", code / "vault")
    monkeypatch.setattr(core, "mountpoint", lambda: tmp_path / "not-mounted")

    assert "moved" in core.migrate_vault()
    assert not (code / "vault").exists()
    assert (data / "vault" / "encrypted-file").read_text() == "x" and core.VAULT == data / "vault"
    assert core.migrate_vault() is None, "nothing to do the second time"


def test_readme_logo_matches_the_terminal_logo():
    import importlib.util

    spec = importlib.util.spec_from_file_location("logo_svg", ROOT / "scripts" / "logo_svg.py")
    logo_svg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(logo_svg)
    for theme, colors in logo_svg.THEMES.items():
        saved = (ROOT / "docs" / "assets" / f"logo-{theme}.svg").read_text()
        assert saved == logo_svg.svg(colors), f"run: python3 scripts/logo_svg.py ({theme} logo is out of date)"
