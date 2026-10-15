# How it works

- [The parts](#the-parts)
- [Check-ins and the timeline](#check-ins-and-the-timeline)
- [Triggers](#triggers)
- [Delivery and scheduling](#delivery-and-scheduling)
- [Backup people](#backup-people)
- [Guarantees](#guarantees)
- [Safety nets](#safety-nets)
- [Packages on disk](#packages-on-disk)
- [Project layout](#project-layout)

---

## The parts

```
 Your computer                                  Your server (Docker, /opt/phoenix)
┌──────────────────────────────┐   SSH only    ┌──────────────────────────────────────┐
│ phoenix (menu, stdlib only)  │ ────────────► │ phoenix service                      │
│  • vault (gocryptfs)         │  rsync: age-  │  • timer loop, every minute          │
│  • encrypts with the server's│  encrypted    │  • control bot (aiogram) ◄──► you    │
│    public key (age)          │  packages     │  • your Telegram session (Telethon)  │
│  • runs server commands      │  ssh: ctl     │      ──► your people, on trigger     │
│    over SSH (ctl)            │  commands     │  • data/: key, session, SQLite, pkgs │
└──────────────────────────────┘               └──────────────────────────────────────┘
```

- **Your computer** prepares packages, encrypts them with the server's [age](https://github.com/FiloSottile/age) public key and uploads them with `rsync` over SSH. Plaintext never leaves your computer. The menu controls the server by running `python -m phoenix.ctl …` inside its container over SSH. Nothing on the server listens on the network.
- **The server** runs one Docker container:
  - a minute-by-minute timer;
  - your private control bot;
  - a Telegram client logged into your account.

  Its `data/` folder holds the age private key, the Telegram session, a SQLite database and the encrypted packages.

## Check-ins and the timeline

You prove you're alive with the bot's button, any message to the bot, the menu, or any message you send in Telegram (activity). The **deadline** is:

```
min( max(last check-in, last activity) + checkin_interval,   last explicit check-in + button_every )
```

so activity postpones it, but an explicit check-in is still needed every `button_every`.

After a missed deadline:

| Phase | When | Reminders |
|---|---|---|
| 🟡 overdue | the deadline passed | every `reminder_every` (12h) |
| 🔴 alarm | `alarm_after` (7d) after the deadline | every `alarm_every` (2h) |
| 🔥 triggered | `trigger_after` (14d) after the deadline, **and** the alarm has lasted at least `alarm_min` (1d) | — |
| ⚫ delivered | everything is sent or handed to Telegram | — |

The `alarm_min` rule protects against downtime: if the server was off for weeks, it never delivers the moment it comes back, so you always get at least a day of alarms first. A **pause** moves the deadline past its end. Any check-in in the overdue or alarm phase resets everything.

## Triggers

- **silence:** the timeline above ran out.
- **panic:** `/panic` in the bot, or 🚨 in the menu. Delivery starts after `panic_delay` (1h) unless you cancel.

Each package, and the account actions, says which triggers send it.

The **duress code** is a panic in disguise. It sets a pending panic due after the duress delay, plus a *silent* flag. While the flag is on:

- the engine sends no notifications;
- the bot's status and log are computed as if nothing happened;
- `/cancel`, `/abort` and `/rearm` pretend to do nothing.

The menu on your computer sees the real state, because `ctl` reveals it, and clears the flag when you cancel, stop or re-arm.

## Delivery and scheduling

Every item has a due time: the trigger time, plus the package's delay, plus the item's own offset (`@+1y`) or a fixed date (`@2034-05-12`). Then:

| Due | What happens |
|---|---|
| now (within 90 seconds) | sent immediately |
| within ~1 year (364 days) | handed to **Telegram's own scheduled messages**. Telegram delivers it even if the server is gone by then. |
| later | kept by the server and handed to Telegram once it's within a year. The server must stay alive and paid until then; the upload warns you how long. |

If Telegram refuses to schedule (for example, too many scheduled messages in one chat), the server keeps those items and sends them itself when they're due.

Messages scheduled by Phoenix show up in each chat's **Scheduled messages** list in your Telegram after a trigger. **Stop the delivery** deletes them again.

## Backup people

From the moment a package's first item was due, Phoenix waits `backup_after` (7d by default) and then checks whether the person has read the chat. If they haven't, or if they couldn't be found in Telegram at all, the same package goes to the backup person, starting with a short note.

## Guarantees

- **Progress is stored per item.** An interrupted delivery (a restart, a network error) resumes where it stopped and never sends anything twice.
- **Failed deliveries are retried** every 30 minutes, and you're told what failed.
- **People are resolved once and remembered by their account id.** A username changed later doesn't break delivery.

## Safety nets

The switch runs in its own loop, apart from anything that talks to Telegram. A slow Telegram call (a flood wait can last hours) or a broken control bot can't hold it up: Phoenix keeps watching your activity and delivering, and the menu on your computer shows what's wrong.

The server also:

- checks every 6 hours that the Telegram session still works, and warns you if it doesn't;
- reminds you 30, 14 and 7 days before the hosting paid-until date;
- asks every 90 days whether your packages are still up to date;
- tells you when packages change, with the result of the recipient check;
- optionally pings a [healthchecks.io](https://healthchecks.io) URL every minute, so you get an email if the server goes down.

## Packages on disk

On your computer, packages are plain folders, one per person, inside the vault, which is mounted while the menu runs. The menu manages them, but you can also edit them with a file manager:

```
alice/
├── .recipient.toml         settings (written by the menu)
├── 01-message.txt          → text message
├── 02-hello.ogg            → voice message
├── 03-hug.round.mp4        → round video message
├── 04-photo.jpg            → file
├── @+1y/                   → sent one year after the rest
│   └── 05-message.txt
└── @2034-05-12/            → sent on 12 May 2034 at 09:00 (@2034-05-12T18:30 for a time)
    └── 06-birthday.jpg
_account.toml               account actions (written by the menu)
```

- Items are sent in alphabetical order of their path, and the deepest `@` folder decides when.
- Names starting with `.` are never sent, and folders starting with `_` are ignored.

On the server, each package becomes a folder with a hashed name holding `manifest.json.age` plus one `<hash>.age` per item. The names are hashed with a secret kept in your computer's Phoenix settings, so the package files alone reveal neither names nor contents. Be aware of two other things on the server:

- the database next to the package files does contain your recipients' names and usernames, for the status and the event log;
- the server holds the key that decrypts everything (see [security](security.md)).

| Where | What |
|---|---|
| `~/.config/phoenix/config.json` | server address, setup progress, the server's public key |
| `~/.local/share/phoenix/vault` | your packages, encrypted (the vault) |
| `~/.local/share/phoenix/app` | Phoenix itself (installed with `install.sh`) |
| `~/.cache/phoenix` | encrypted copies ready for upload, the SSH connection |
| server: `/opt/phoenix/data` | key, Telegram session, database, encrypted packages |
| server: `/opt/phoenix/.env` | bot token, API keys, time zone |

## Project layout

```
install.sh             installer for your computer
cli/phoenix            the `phoenix` command
cli/phx/
  screens.py           the menus: setup, recipients, check-ins, timers, server, vault
  ui.py                arrow-key menus, questions, splash, terminal size check
  art.py               the logo
  packages.py          package folders, checks, encryption and upload
  core.py              settings, SSH, server setup steps, vault
server/phoenix/
  main.py              entry point: control bot, Telegram account, timer loop
  engine.py            check-ins, escalation, triggers, backups, reminders, requests from the menu
  delivery.py          sending and scheduling items
  account.py           your Telegram account (Telethon)
  bot.py               control bot (aiogram)
  packages.py          the encrypted package format
  state.py, db.py      state views and SQLite storage
  ctl.py               commands the menu runs over SSH
  duress.py            the duress code (salted scrypt hash) and the silent alarm
  login.py, logout.py, keygen.py   Telegram login/logout, the encryption key
deploy/bootstrap.sh    server preparation (setup step 2)
docker-compose.yml     the service; data lives in /opt/phoenix/data
tests/                 automated tests (pytest)
docs/                  this documentation
```
