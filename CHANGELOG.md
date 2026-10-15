# Changelog

All notable changes to Phoenix. Dates are in YYYY-MM-DD.

## Unreleased

### Added
- **Duress code:** a phrase that looks like an ordinary check-in, but quietly starts the panic delivery after a delay. The bot keeps showing a normal status, sends no alerts and pretends there's nothing to cancel; only the menu on your computer can stop it.
- **A new look:** a splash with the phoenix logo, colored states, a farewell screen; menus scroll, cut or wrap long lines and redraw when the window is resized.
- The logo at the top of the README, drawn from the same dots as in the terminal (light and dark versions).
- **Terminal size check** like btop: below 80×24, Phoenix shows the current and needed size until the window is big enough.
- A vault kept next to the code (early versions) is moved to `~/.local/share/phoenix/vault` automatically.
- **One menu for everything:** `phoenix` without arguments opens an arrow-key menu.
  - A step-by-step **setup** that explains where to get each key and checks its format. It creates and installs an SSH key if needed, and can be resumed later.
  - **Recipients:** add people, write messages, drag in files, choose when to send, settings and backup people, with no config files to edit.
  - **Check-ins, rehearsal, recipient check, pause, timers and panic** directly from the menu, plus a live status summary at the top.
  - A **Server** menu: update, restart, logs, hosting paid-until date, new keys, logging in to Telegram again, moving to another server, and removing Phoenix from a server (logs out of Telegram first).
- `install.sh`: installs the needed tools (after asking), downloads Phoenix and creates the `phoenix` command.
- Servers with a non-root user and passwordless `sudo` (e.g. `ubuntu` on OVHcloud and AWS).
- The vault locks when the menu exits, even if the terminal window is closed.
- One SSH connection per session, so a key passphrase is asked only once.
- Automated tests (pytest), CI, and documentation in `docs/`.

### Changed
- Packages and the vault now live in `~/.local/share/phoenix`, separate from the code. Existing vaults next to the code keep working.
- Recipient settings are stored in a hidden `.recipient.toml` managed by the menu. Existing `recipient.toml` files are converted automatically.

## 2026-10-14

- First public version: the server (timer, control bot, delivery from your Telegram account, scheduling, backups, account actions), the CLI, server bootstrap, and the README.
