# 🔥 Phoenix

**A self-hosted dead man's switch for Telegram.**

If you stop checking in, or press a panic button, Phoenix delivers messages you prepared in advance (letters, passwords, instructions, photos, voice and video messages) to the people you choose. They arrive **from your own Telegram account**, in your existing private chats, so recipients see them from someone they know rather than from an unknown bot or a "you've got mail" link.

```
Your computer                           Your VPS (only SSH is exposed)
encrypted vault ── phoenix push ─────►  encrypted packages
                                        timer + control bot ◄──► you: "✅ I'm OK"
                                        your Telegram account ──► recipients, on trigger
```

> ⚠️ **Status: early.** The core logic is covered by an end-to-end test against a simulated Telegram account with a fast-forwarded clock, but the project has not had much real-world use yet. Read the [Security model](#security-model), run `/test` and do a full rehearsal before you rely on it.

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Writing packages](#writing-packages)
- [Account actions after a trigger](#account-actions-after-a-trigger)
- [Commands](#commands)
- [Security model](#security-model)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Development](#development)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Features

- **Delivery from your own account:** text, files in original quality, voice messages and round video messages.
- **Escalating reminders** before anything happens, with protection against firing right after server downtime.
- **Two triggers:** *silence* (you stopped checking in) and *panic* (a button with a cancel window). Each package chooses which triggers it reacts to.
- **Activity check-ins:** messages you write anywhere in Telegram count as proof of life, but an explicit check-in is still required periodically.
- **Delayed and dated letters:** "one year later", "on 12 May 2034". Anything due within about a year is handed to Telegram's own scheduled messages, so it is delivered even if the server is gone by then.
- **Backup recipients:** if a package isn't read in time, or the recipient can't be found, it goes to someone else.
- **Account actions:** a one-time auto-reply to people who message you, a new profile bio, and posts to groups or channels.
- **Undo:** `/abort` stops delivery, cancels already-scheduled messages and restores your bio.
- **Rehearsal:** `/test` sends everything to your own Saved Messages, exactly as recipients would see it.
- **Encryption:** packages are encrypted on your computer before upload (age), and on your computer they are kept in an encrypted vault (gocryptfs).
- **Housekeeping:** warnings if the Telegram session dies, hosting payment reminders, and periodic "are your packages still up to date?" prompts.

## How it works

### Check-ins

You prove you're alive by:

- tapping **"✅ I'm OK"** or sending **any message** to your Phoenix control bot;
- **writing messages anywhere in Telegram**, from any device (can be turned off with `/activity off`).

Activity alone is not enough forever. An explicit check-in is required at least every `button_every` (default **30 days**), so that someone using your phone afterwards can't postpone delivery indefinitely.

### Timeline

Defaults; every value can be changed from the bot with `/set`.

| When | What happens | Settings |
|---|---|---|
| 7 days after your last check-in | check-in missed: reminder every 12 h | `checkin_interval`, `reminder_every` |
| 7 days after the missed check-in | 🚨 **alarm**: reminder every 2 h | `alarm_after`, `alarm_every` |
| 14 days after the missed check-in | **trigger**: packages are delivered | `trigger_after` |

With the defaults, delivery happens after **21 days of total silence**. If the server was offline for a while, it never fires immediately on restart: the alarm phase always runs for at least `alarm_min` (default 1 day) first. `/status` shows the exact time left.

### Triggers

- **silence**: you stopped checking in;
- **panic**: you pressed `/panic`. Delivery starts after `panic_delay` (default 1 hour), and `/cancel` stops it until then.

Example: a "here's what to do right now" note for one person on `panic`, and everything else only on `silence`.

### Delayed items

Every item has a due time: the trigger time, plus an optional package `delay`, plus an optional per-item offset or fixed date.

- **Due now:** sent immediately.
- **Due within ~1 year:** handed to Telegram's built-in scheduled messages. The server can disappear afterwards.
- **Due later:** kept by the server and handed to Telegram once it is within a year. The server must stay alive and paid until then; `phoenix push` and `/verify` tell you for how long.

If Telegram refuses to schedule a message (for example, there are too many scheduled messages in one chat), the server keeps it and sends it itself at the due time.

### Backup recipients

If the recipient hasn't read the package within `backup_after` (default 7 days) after its first message was due, or can't be found at all, the same package is sent to the backup recipient, starting with a short note that explains why.

### Delivery guarantees

Progress is stored per item. An interrupted delivery resumes where it stopped and never sends anything twice. Failed deliveries are retried every 30 minutes.

---

## Requirements

**Server**

- A small VPS with **Ubuntu 24.04+ or Debian 12+**, 1 GB RAM, and disk space for your packages.
- Root SSH access with a key.
- Docker is installed for you by `phoenix bootstrap`.

**Your computer (Linux)**

- Python 3.11+, `ssh`, `rsync`, [`age`](https://github.com/FiloSottile/age), [`gocryptfs`](https://github.com/rfjakob/gocryptfs) (optional, for the local vault).

| Distro | Install |
|---|---|
| Arch | `sudo pacman -S python age rsync openssh gocryptfs` |
| Debian / Ubuntu | `sudo apt install python3 age rsync openssh-client gocryptfs` |
| Fedora | `sudo dnf install python3 age rsync openssh-clients gocryptfs` |

**Telegram**

- A bot token from [@BotFather](https://t.me/BotFather), used for your control bot.
- Your numeric user id, for example from [@userinfobot](https://t.me/userinfobot).
- `api_id` and `api_hash` from [my.telegram.org](https://my.telegram.org) → *API development tools*.

---

## Installation

### 1. Get the CLI

```bash
git clone https://github.com/<you>/Project_PHOENIX.git
cd Project_PHOENIX
mkdir -p ~/.local/bin && ln -s "$PWD/cli/phoenix" ~/.local/bin/phoenix
```

### 2. Prepare the server

Make sure key-based login works (`ssh root@SERVER_IP` without a password). If you only have a password:

```bash
ssh-copy-id root@SERVER_IP
```

> `phoenix bootstrap` enables a firewall that leaves **only SSH** open, and disables password login. Use a dedicated server, or check that nothing else running on it needs open ports.

### 3. Set up Phoenix

```bash
phoenix init --server root@SERVER_IP   # remember the server
phoenix bootstrap                      # updates, Docker, firewall, key-only SSH (once)
phoenix deploy                         # upload and build the server
phoenix configure                      # bot token, your user id, api_id, api_hash, time zone
phoenix login                          # log the server into your Telegram account
phoenix vault-init                     # optional: keep packages encrypted on this computer
```

`vault-init` asks for a password and prints a **master key**. Store the key offline: it is the only way to recover the vault if you forget the password.

Open your control bot in Telegram and press **Start** (a bot can't message you before that). It replies **"🔥 Phoenix is armed"**.

### 4. Recommended

- Telegram → Settings → Privacy → **"Delete my account if away for"**: set the longest period.
- Prepay your hosting and tell the bot the date: `/paiduntil 2027-12-31`.
- Create a free check at [healthchecks.io](https://healthchecks.io) (5-minute period) and paste its URL in `phoenix configure`. You'll get an email if the server goes down.

---

## Writing packages

One folder per recipient:

```bash
phoenix new alice
```

```
alice/
├── recipient.toml          who receives it, when, backup
├── 01-letter.txt           → text message
├── 02-accounts.md          → text message
├── 03-hello.ogg            → voice message
├── 04-hug.round.mp4        → round video message
├── 05-photos/              → files, original quality
│   └── beach.jpg
├── @+1y/                   → sent one year after the package starts
│   └── one-year-later.txt
└── @2034-05-12/            → sent on 12 May 2034 at 09:00 (your time zone)
    └── happy-birthday.txt
```

Items are sent in alphabetical order of their path, so number them. Folders whose names start with `_` or `.` are ignored.

| File | Sent as |
|---|---|
| `.txt`, `.md` | text message, split automatically if long |
| `.ogg`, `.oga`, `.opus` | voice message (Opus audio) |
| `.round.mp4` | round video message (square, up to 60 s) |
| anything else | document, up to 2 GB each |

**Scheduled folders.** `@+30d`, `@+1y`, `@+1y6m`... mean "this long after the package starts". Durations use `m` (minutes), `h`, `d`, `w`, `y`. `@2034-05-12` or `@2034-05-12T18:30` mean a date in your time zone; a date that has already passed is sent right away. The deepest `@` folder in a path wins.

### `recipient.toml`

```toml
name = "Alice"
telegram = "@alice"                # @username, +phone (must be in your contacts) or numeric id

# Optional
on = ["silence", "panic"]          # which triggers send this package (default: both)
delay = "3d"                       # wait after the trigger before sending anything
backup = "@bob"                    # if Alice hasn't read it…
backup_after = "7d"                # …within this time, send the same package to Bob
backup_note = "This was meant for Alice, but she could not be reached."
```

To send different packages to the same person on different triggers, make two folders with the same `telegram`.

### Upload and check

```bash
phoenix edit     # unlock the vault, open the folder; when done → upload → lock
phoenix push     # upload (only changed files are re-encrypted)
```

`push` refuses to upload broken packages: template text left in, placeholder usernames, files over 2 GB, non-UTF-8 text, or unreadable `@` folder names. Within a minute the bot reports whether every recipient was found, along with delays, backups and warnings. Then run **`/test`**.

**Writing tip:** the first message should explain immediately what is going on, for example *"If you're reading this, something has happened to me. This was sent automatically; I prepared it in advance."* For anything that needs action, write down concrete steps: where to log in, what to do, who to contact.

---

## Account actions after a trigger

```bash
phoenix account   # creates _account.toml next to the package folders
```

```toml
on = ["silence"]          # which triggers run these actions

# Sent once to each person who messages you in a private chat.
# Never sent to your recipients, bots or groups.
autoreply = """
This is an automatic message. I can no longer reply here.
"""

about = "..."             # new profile bio (70 chars, 140 with Premium); restored by /abort

[[post]]                  # repeat for each group, channel or person
chat = "@some_group"      # you must be able to write there
text = "..."
delay = "1d"              # optional
```

Every field is optional. Posts show up in `/verify` and `/test` like packages.

---

## Commands

### Control bot

| Command | Description |
|---|---|
| `/checkin` or any message | "I'm OK": reset the timer |
| `/status` | state, time left, account health |
| `/pause 14d`, `/resume` | going offline for a while |
| `/activity on\|off` | count your Telegram activity as a check-in |
| `/settings`, `/set <name> <duration>` | show or change timings |
| `/verify` | check packages and recipients |
| `/test` | rehearsal: everything goes to your Saved Messages |
| `/panic`, `/cancel` | trigger now (with a cancel window) / cancel |
| `/abort` | undo a trigger: stop, cancel scheduled messages, restore bio |
| `/rearm` | arm again after a completed delivery |
| `/paiduntil YYYY-MM-DD` | hosting payment reminders |
| `/log` | recent events |
| `/help` | help |

The bot ignores everyone except the owner.

**Settings** (defaults): `checkin_interval` 7d · `button_every` 30d · `reminder_every` 12h · `alarm_after` 7d · `alarm_every` 2h · `trigger_after` 14d · `alarm_min` 1d · `panic_delay` 1h · `review_every` 90d.

### CLI

| Command | Description |
|---|---|
| `phoenix init --server root@IP` | connect to a server (`--remote-dir`, default `/opt/phoenix`) |
| `phoenix bootstrap` | prepare a fresh server (once) |
| `phoenix deploy` | upload the server code and (re)start it |
| `phoenix configure` | write the server's `.env` |
| `phoenix login` | log the server into your Telegram account |
| `phoenix new <name>` | create a package |
| `phoenix account` | create `_account.toml` |
| `phoenix edit` / `phoenix push` | edit / upload packages |
| `phoenix vault-init` / `phoenix lock` | create / lock the local vault |
| `phoenix status` / `log` / `logs` | server state / events / raw logs |

---

## Security model

**What Phoenix protects:**

- **Packages in transit and at rest on the server.** They are encrypted on your computer with the server's age public key and stored under anonymous file names. Leaked disks or provider backups reveal nothing readable.
- **Packages on your computer.** With the vault enabled, they are readable only while `phoenix edit` or `phoenix push` runs.
- **Exposure.** The server exposes only SSH (key-only), and the control bot answers only to the owner's user id.

**What it does not protect against:**

- **A compromised server.** The server must be able to decrypt packages and act on your behalf without you, so its decryption key and your **Telegram session** live on it. Whoever controls the server controls your Telegram account. Keep it dedicated, patched and accessible only to you.
- **A compromised computer.** It sees your packages while the vault is open.
- **Recipients.** Once something is delivered, it can't be taken back.

**Operational notes:**

- Don't use **"Terminate all other sessions"** in Telegram: it logs Phoenix out. The bot warns you within 6 hours, and `phoenix login` fixes it.
- Scheduled messages are visible in your account's "Scheduled" list in each chat after a trigger.
- The server's `data/` folder (key, session, database) is not backed up by Phoenix. If the server is lost while you are alive, set up a new one: `init`, `bootstrap`, `deploy`, `configure`, `login`, `push`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Bot doesn't answer | Press **Start** in the bot, check the token and user id (`phoenix configure`), see `phoenix logs`. |
| "Telegram account problem" | The session ended: `phoenix login`. |
| `❌ cannot find …` in `/verify` | Check the username; phone numbers must be in your contacts. |
| `push`: "fix these first" | Each line names the file and the problem. |
| "Could not lock the vault" | Close windows and terminals inside the vault folder, then `phoenix lock`. |
| Forgot the vault password | `gocryptfs -passwd -masterkey=<master key> vault/` |
| Dated items arrive at the wrong hour | Set `TIMEZONE` with `phoenix configure`, then `phoenix deploy`. |

---

## Project layout

```
cli/phoenix            CLI for your computer (Python standard library only)
server/phoenix/
  main.py              entry point: control bot, Telegram account, timer loop
  engine.py            check-ins, escalation, triggers, backups, reminders
  delivery.py          sending and scheduling items
  account.py           Telegram user account (Telethon)
  bot.py               control bot (aiogram)
  packages.py          encrypted package format
  state.py, db.py      state views and SQLite storage
  login.py, keygen.py, ctl.py   helpers run by the CLI over SSH
deploy/bootstrap.sh    one-time server preparation
docker-compose.yml     the service; data lives in <remote-dir>/data
```

## Development

The server targets Python 3.12 (see `server/Dockerfile`):

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r server/requirements.txt
```

The engine can be tested without Telegram by passing a fake account object to `Engine` and moving `time.time` forward. Contributions and bug reports are welcome, especially reports from real-world setups.

## Disclaimer

Phoenix automates your **personal** Telegram account through the official API. Use it only for your own account and for its intended purpose; sending spam or bulk messages can get an account restricted under Telegram's terms. The software is provided as is, without any warranty. Don't make it the only place where important information or instructions are kept, and pair it with proper legal arrangements (such as a will) where those matter.

## License

[MIT](LICENSE)
