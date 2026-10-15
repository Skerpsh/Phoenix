# Contributing

Thanks for helping! Bug reports from real-world setups are especially valuable, since Phoenix is young.

## Reporting bugs and ideas

Use the issue templates. Please never paste tokens, API hashes, phone numbers, the contents of `.env`, or anything from your packages. For security problems, see [SECURITY.md](SECURITY.md) instead.

## Development setup

The server targets Python 3.12 (see `server/Dockerfile`); the CLI needs Python 3.11+ and only the standard library.

```bash
git clone https://github.com/Skerpsh/Phoenix.git && cd Phoenix
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
sudo apt install age rsync      # or your system's equivalent

ruff check .                    # lint
pytest                          # tests
```

The tests run everything in a throwaway home directory (`tests/conftest.py`), so they never touch your real configuration, packages or vault. They include:

- **`tests/test_engine.py`:** the full life of a switch against a fake Telegram account with a fast-forwarded clock: check-ins, escalation, both triggers, scheduling, backups, auto-reply, abort, the rehearsal, and requests from the CLI.
- **`tests/test_cli.py`:** package checks, the encrypted upload, and the whole menu driven with typed answers, where `ssh`/`rsync` are stubs that run the server side locally.

To try your changes on a real server, use a test Telegram account and a throwaway VPS. Run the CLI from your checkout (`./cli/phoenix`); it uploads the server code from the same checkout.

## Guidelines

- Keep the CLI dependency-free: Python standard library only, so `install.sh` stays simple.
- Every user-facing text is English and tells the user what to do next, in terms of the menu ("Server → Update Phoenix"), not internal commands.
- If the CLI starts using a new server command (`server/phoenix/ctl.py`) or request (`Engine.handle_request`), bump `PROTOCOL` in `server/phoenix/__init__.py`, so the menu asks people to update their server.
- Changes to timing, delivery or the package format need a test in `tests/test_engine.py`.
- Update `CHANGELOG.md` and the docs in `docs/` along with the code.
- CI must pass: ruff, shellcheck, pytest, the CLI on Python 3.11 and 3.13, and the Docker build.
