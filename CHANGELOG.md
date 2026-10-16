# Changelog

All notable changes to Phoenix. Versions follow [semantic versioning](https://semver.org); dates are YYYY-MM-DD.

## Unreleased

### Security
- After you change who receives a package, the Telegram id found for the previous person is never used again. Before, a new recipient that couldn't be found meant the letters still went to the old one.
- Files decrypted for sending are removed when Phoenix stops (`docker compose stop` included), and anything left over from a crash is removed at start.
- Removing Phoenix from a server tells you if the server could not log out of your Telegram account, and how to end that session yourself.
- The settings file on your computer is private from the moment it's written, and the container runs without any special permissions.

### Fixed
- **Moving to another server** now takes your timers, duress code, pause and paid-until date along. Before, the new server started with the defaults, and the duress code stopped working without a word.
- **Stop the delivery** really stops: an item stuck for over a minute (a big upload, or Telegram making Phoenix wait) is cut off, and you're told it may still have arrived.
- Phoenix reconnects to Telegram within a minute when the connection is down at start, instead of up to 6 hours later.
- A delivery starts before the bio change, so a slow bio update can't hold it up.
- One database hiccup can no longer stop Phoenix from answering the menu. When an action takes longer than the menu waits, it says so instead of "Is it running?".
- The history and the payment reminders use your time zone.
- Phoenix's own messages (time capsules, the rehearsal) are never taken for a sign of life.
- The secret that hides names on the server is kept in the vault, so a vault restored on a new computer gives the same names, and nothing already delivered is sent twice.

## 1.1.0 — 2026-10-15

### Added
- **Time capsules:** messages that go out on a date you choose, whatever happens: to someone on a future birthday, or to yourself in years. They wait encrypted on your server and don't count as signs of life.
- **Timeline:** one screen with everything that goes out after a trigger, and when, plus your time capsules.
- **Letter guide:** a few questions help you write a letter; only your answers go into it, in your own language.
- **Weekly self-check:** the server makes sure every recipient can still be found and every file can still be decrypted, and tells you only when something breaks or is fixed.
- **Account deletion warning** when Telegram's "If away for" period is under a year.
- **Vault backup** to a USB stick or any folder, checked after copying, with restore instructions.

### Fixed
- Deleted Telegram accounts are recognized as "can't be found" instead of looking fine.

## 1.0.0 — 2026-10-15

The first release.

### The switch
- Check-ins with one tap in your private control bot. Messages you send anywhere in Telegram count too, but an explicit check-in is still needed every 30 days.
- Escalation before anything happens: reminders, then an alarm, then delivery. With the defaults, delivery comes after 21 days of silence. The alarm always lasts at least a day, so the switch never fires right after the server was down.
- A **panic button** with a cancel window, and a **duress code**: a phrase that looks like an ordinary check-in but quietly starts the panic delivery. The bot keeps showing a normal status, and only the menu on your computer can stop it.
- Pause for trips or hospital stays.

### Delivery
- Everything is sent from **your own Telegram account**: text, files in original quality, voice messages and round video messages. Each person gets only what you prepared for them.
- Delayed and dated letters. Anything due within a year is handed to Telegram's own scheduled messages, so it arrives even if the server is gone by then.
- A backup person for anyone who doesn't read their package in time, or can't be found.
- Account actions after a trigger: a one-time auto-reply, a new bio, posts to groups or channels.
- A rehearsal that sends everything to your Saved Messages, and a way to stop a delivery and cancel what's already scheduled.
- Progress is stored per item: an interrupted delivery resumes and never sends anything twice.

### The `phoenix` menu
- One arrow-key menu for everything, with a splash and a farewell screen and a live status at the top. Below 80×24 it shows the size it needs, like btop.
- A step-by-step setup. It explains where to get each key, checks it, creates an SSH key if needed, and can be resumed later.
- Recipients, messages and files (drag them into the terminal), scheduling, backups and account actions, with no config files to edit.
- Timers, time zone (with city search), hosting paid-until date, updates, logs, logging in to Telegram again, moving to another server, and removing Phoenix from a server.
- `install.sh` installs the tools Phoenix needs (after asking) and the `phoenix` command.

### Security and safety
- Packages are encrypted on your computer before upload (age). On the server their names are hashed with a secret that stays on your computer, and on your computer they're kept in a password vault (gocryptfs) that locks when the menu exits.
- The server exposes only SSH with key login; the firewall, fail2ban and automatic security updates are set up for you. Servers with a sudo user such as `ubuntu` work too.
- The control bot answers only you. From the bot, someone holding your phone can't quietly switch Phoenix off: delaying timers can only get shorter, a pause lasts at most 30 days, and a delivery can be stopped only within 2 days of its start.
- The switch runs apart from anything that talks to Telegram, so a slow Telegram call or a broken bot can't hold it up. Moving to another server stops the old one first, and Phoenix warns you if two programs ever read your bot.
- An honest [security model](docs/security.md): a copy of the whole server includes the key to your packages and your Telegram session.

### Project
- Documentation in `docs/`: installation, usage, how it works, security, troubleshooting.
- 55 automated tests, including a full simulated life of the switch and the menu driven like a user would. CI runs ruff, shellcheck, the tests, a dependency vulnerability scan, the CLI on Python 3.11 and 3.13, and the Docker build.
