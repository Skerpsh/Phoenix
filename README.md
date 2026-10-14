# 🔥 Phoenix

A dead man's switch for Telegram. If you stop checking in, or press the panic button, Phoenix delivers pre-written packages (letters, passwords, photos, voice messages) to the people you trust, **from your own Telegram account**. It can also schedule letters for years ahead, hand a package to a backup person if the main recipient doesn't read it, and set up your account (auto-reply, bio, farewell posts).

```
Your PC                                VPS (only SSH is open)
vault/ (encrypted) ── phoenix push ──► encrypted packages
                                       timer + your control bot ◄──► you (✅ I'm OK)
                                       your Telegram account ──► recipients (on trigger)
```

- [How it works](#how-it-works)
- [Setup](#setup-once)
- [Packages](#packages)
- [Account actions](#account-actions-after-trigger)
- [Day to day](#day-to-day)
- [Security](#security-what-you-need-to-know)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Status](#status)

---

## How it works

### Check-ins

You prove you're alive by:
- tapping **"✅ I'm OK"** or sending **any message to your Phoenix bot**;
- **writing messages anywhere in Telegram**, from any device. This is activity check-in; turn it off with `/activity off`.

Activity alone isn't enough forever: an explicit check-in (button or bot message) is still required at least every **30 days**. Otherwise someone using your phone after your death could postpone delivery indefinitely.

### Timeline (defaults; change with `/set`)

| When | What happens | Setting |
|---|---|---|
| **7 days** after your last check-in | check-in missed: reminder every **12 h** | `checkin_interval`, `reminder_every` |
| **7 days** after the missed check-in | 🚨 ALARM: reminders every **2 h** | `alarm_after`, `alarm_every` |
| **14 days** after the missed check-in | **trigger**: packages are delivered | `trigger_after` |

So with the defaults, delivery happens after **21 days of total silence**. `/status` always shows the exact time left.

- If the server was down for a long time, it does **not** fire right after coming back: there is always at least **1 day** of alarm reminders first.
- `/panic` triggers delivery in **1 hour**. Until then, `/cancel` stops it.
- `/abort` undoes a trigger: it stops sending, **cancels messages already scheduled in Telegram**, restores your bio and turns off the auto-reply. Messages that were already delivered can't be taken back.
- `/pause 30d`: travelling, in hospital, no connection.
- `/test` sends everything to **your own Saved Messages**, exactly as recipients would see it, with notes on when each part would arrive.

### Two kinds of triggers

- **silence**: you stopped checking in (presumably the worst happened);
- **panic**: you pressed the panic button (something happened, but you may be alive).

Each package says which triggers it reacts to. For example, a "here's what to do" note for your partner on `panic`, and everything else only on `silence`.

### Delayed letters

Items can be sent later than the trigger: "open in a year", a letter for a child's 18th birthday. Anything due within **~1 year** is handed to **Telegram's built-in scheduled messages**, so it is delivered **even if the server is gone by then**. Items further ahead are kept by the server and handed over once they come within a year, so the server must stay alive and paid until then. `phoenix push` and the bot warn you how long that is.

### Backup recipient

If the recipient hasn't read the package within N days (default 7) after its first message was due, or can't be found in Telegram at all, the same package goes to a backup person. It starts with a note; the default is in English (*"This was meant for Mom, but they could not be reached, so it is being sent to you instead."*), so write your own with `backup_note`.

### Housekeeping

- The account session is checked every **6 hours**; the bot warns you if the server got logged out of your Telegram account.
- Hosting payment (`/paiduntil`): reminders **30 and 14 days** before, then **daily** during the last 7 days.
- After **90 days** without changes, the bot asks whether your packages are still up to date (passwords change), and repeats weekly until you update them or tap "👍 Still up to date".
- Failed deliveries are retried every **30 minutes**; an interrupted delivery resumes where it stopped and never sends anything twice.

---

## Setup (once)

### 0. On your PC (Arch)

```bash
sudo pacman -S python age rsync openssh gocryptfs
mkdir -p ~/.local/bin && ln -s ~/Project_PHOENIX/cli/phoenix ~/.local/bin/phoenix
```

No SSH key yet? Create one: `ssh-keygen -t ed25519` (press Enter for every question).

### 1. Server

1. Buy a VPS (recommended: **OVHcloud VPS-1**, OS **Ubuntu 24.04**).
2. When ordering, paste your public SSH key: the output of `cat ~/.ssh/id_ed25519.pub`.
3. Check that you can log in: `ssh root@SERVER_IP`. OVH uses the `ubuntu` user by default. In that case run this once:
   `ssh ubuntu@SERVER_IP 'sudo mkdir -p /root/.ssh && sudo cp ~/.ssh/authorized_keys /root/.ssh/'`
4. **Prepay the hosting for at least a year** (longer if you schedule letters far ahead). If payments stop, the server is shut down.

### 2. Telegram

1. **Control bot:** message [@BotFather](https://t.me/BotFather), send `/newbot` and save the token.
2. **Your user id:** message [@userinfobot](https://t.me/userinfobot).
3. **Account API keys:** go to https://my.telegram.org, open *API development tools*, create an app (any name) and save `api_id` and `api_hash`.
4. Telegram Settings → Privacy → **"Delete my account if away for"**: set it to the **maximum**.
5. *(Optional)* https://healthchecks.io: create a free check with a 5-minute period and save its URL. You'll get an email if the server goes down.

### 3. Launch

```bash
phoenix init --server root@SERVER_IP   # connect to the server
phoenix bootstrap                      # Docker, firewall, auto-updates, key-only SSH
phoenix deploy                         # upload the code and build it
phoenix configure                      # bot token, your id, api_id, api_hash, time zone
phoenix login                          # log in to your Telegram (phone, code, 2FA password)
phoenix vault-init                     # keep your packages encrypted on this PC (recommended)
```

`vault-init` asks for a password and prints a **master key**. Write it on paper: it's the only way back if you forget the password. If you already created packages in `packages/`, they are moved into the vault and you're asked whether to delete the unencrypted copy.

Then open your bot in Telegram and press **Start** (a bot can't message you before that). It replies "🔥 Phoenix is armed". Send `/paiduntil 2027-10-14` (the date your hosting is paid until).

---

## Packages

One folder per recipient. Folders whose names start with `_` or `.` are ignored.

```bash
phoenix new mom          # creates mom/ with recipient.toml and a letter template
```

```
mom/
├── recipient.toml          # who, when, backup (see below)
├── 01-letter.txt           # text message
├── 02-passwords.txt        # text message
├── 03-hello.ogg            # voice message
├── 04-hug.round.mp4        # round video message
├── 05-photos/              # files, original quality
│   └── 2019-sea.jpg
├── @+1y/                   # sent 1 year after the package starts
│   └── one-year-later.txt
└── @2034-05-12/            # sent on 12 May 2034 at 09:00 (your time zone)
    └── happy-18th.txt
```

**How files are sent** (in alphabetical order of their path, so use `01-`, `02-`, ...):

| File | Arrives as |
|---|---|
| `.txt`, `.md` | text message (long text is split automatically) |
| `.ogg`, `.opus` | voice message (record one in Telegram and save it, or convert with ffmpeg to Opus) |
| `.round.mp4` | round video message: square video, up to 60 s |
| anything else | file, original quality, up to **2 GB** each (split bigger videos) |

**Scheduled folders:** `@+30d`, `@+1y`, `@+5y` mean "this long after the package starts"; `@2034-05-12` (09:00) or `@2034-05-12T18:30` mean that date in your time zone (sent right away if the date has already passed). The deepest `@` folder in a path wins.

`phoenix push` refuses to upload if something is wrong: a letter still has the template line, a username is still `@username`, a file is over 2 GB, a text file isn't UTF-8, or an `@` folder name can't be understood.

**`recipient.toml`:**

```toml
name = "Mom"
telegram = "@username"          # or "+380XXXXXXXXX" (must be in your contacts) or a numeric id

# Optional:
on = ["silence", "panic"]       # which triggers send this package (default: both)
delay = "3d"                    # wait after the trigger before sending anything
backup = "@brother"             # if Mom hasn't read it…
backup_after = "7d"             # …within this time, send the same package to @brother
backup_note = "This was meant for Mom, but she could not be reached."
```

Want two different packages for the same person (for example one for panic, one for silence)? Make two folders with the same `telegram`.

**Who can be a recipient:** anyone you can write to from your account. A username always works; a phone number works only if it's in your contacts.

### Editing and uploading

```bash
phoenix edit      # unlocks the vault, opens the folder; press Enter when done → upload → lock
phoenix push      # upload without editing (only changed files are re-encrypted)
```

Within a minute the bot reports whether it found every recipient (`✅ Mom → Jane Doe (@...)`), plus delays, backups and warnings. Then always run **`/test`** and check your Saved Messages: it shows every package, when each part would arrive, and a summary of the account actions.

Without the vault, `phoenix edit` simply opens the `packages/` folder.

**Tip for the letter:** the first message should explain right away what is happening. For example: "If you're reading this, something has happened to me. This message was sent automatically; I prepared it in advance...". For anything that needs action, add instructions: where to log in, what to do, who to contact.

---

## Account actions (after trigger)

```bash
phoenix account   # creates _account.toml next to your package folders
```

```toml
on = ["silence"]          # which triggers run these actions

# Sent once to each person who writes to you in a private chat
# (never to your recipients, bots or groups).
autoreply = """
This is an automatic message. I can no longer answer here.
"""

about = "..."             # your new bio (70 characters, 140 with Premium; restored on /abort)

[[post]]                  # repeat for each group, channel or person
chat = "@some_group"      # you must be able to write there
text = "..."
delay = "1d"              # optional
```

Leave out anything you don't need. Posts appear in `/verify` and `/test` like packages.

---

## Day to day

| Where | Command | What it does |
|---|---|---|
| Bot | `/help` | list of commands |
| | `/status` | state, time left, account health |
| | `/checkin` or any message | "I'm OK" |
| | `/pause 14d`, `/resume` | going offline |
| | `/activity on\|off` | count your Telegram activity as check-in |
| | `/settings`, `/set <name> <duration>` | change timings (`30m`, `12h`, `7d`, `2w`, `1y`) |
| | `/verify` | check recipients and packages |
| | `/test` | dry run into your Saved Messages |
| | `/panic`, `/cancel` | trigger now (1 h to cancel) |
| | `/abort`, `/rearm` | undo a trigger / arm again after delivery |
| | `/paiduntil 2027-10-14` | hosting payment reminders |
| | `/log` | recent events |
| PC | `phoenix edit`, `phoenix push` | change and upload packages |
| | `phoenix new <name>`, `phoenix account` | new recipient / account actions |
| | `phoenix status`, `phoenix log`, `phoenix logs` | server state, events, raw logs |
| | `phoenix lock` | lock the vault if it stayed unlocked |
| | `phoenix deploy` | after updating the code |
| | `phoenix vault-init` | move packages into the encrypted vault (once) |

Settings you can `/set`: `checkin_interval` (7d), `button_every` (30d), `reminder_every` (12h), `alarm_after` (7d), `alarm_every` (2h), `trigger_after` (14d), `alarm_min` (1d), `panic_delay` (1h), `review_every` (90d).

---

## Security: what you need to know

- **The server has full access to your Telegram account.** Never give anyone SSH access to it.
- **Don't tap "Terminate all other sessions"** in Telegram: it logs Phoenix out. If that happens, the bot warns you right away; fix it with `phoenix login`.
- **On your PC**, packages live in the encrypted `vault/` folder (gocryptfs) and are readable only while `phoenix edit` / `push` runs. Back up `vault/` anywhere (USB, cloud): it's useless without the password. Your **password or master key** is the only way to open it.
- **On the server**, files are encrypted (`age`) and have anonymous names. The key lives on the same server, so this protects against leaked disks or backups, not against someone breaking into the server itself.
- **Scheduled messages** sit in your account's "Scheduled" list in each chat. You can see them only after a trigger (and `/abort` deletes them).
- **Server broken or moving to a new one:** `init`, `bootstrap`, `deploy`, `configure`, `login`, `push`. Packages are automatically re-encrypted with the new key.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Bot doesn't answer | Press **Start** in the bot; check the token and `OWNER_ID` (`phoenix configure`); look at `phoenix logs`. The bot answers only you. |
| "Telegram account problem" | The session was terminated: `phoenix login`. |
| `❌ cannot find @someone` in `/verify` | Check the username; for a phone number, add it to your contacts first. |
| `phoenix push`: "fix these first" | Each line says which file and what's wrong. |
| "Could not lock the vault" | Close file manager windows and terminals inside the vault folder, then `phoenix lock`. |
| Forgot the vault password | `gocryptfs -passwd -masterkey=<key from paper> vault/` sets a new one. |
| Wrong reminder times for dated letters | Run `phoenix configure` again and set your `TIMEZONE`, then `phoenix deploy`. |

## Project layout

```
cli/phoenix            command-line tool for your PC (Python standard library only)
server/phoenix/        the server (runs in Docker)
  main.py              starts the bot, the Telegram account and the timer
  engine.py            check-ins, escalation, triggers, backups, reminders
  delivery.py          sending and scheduling items in Telegram
  account.py           your Telegram account (Telethon)
  bot.py               the control bot (aiogram)
  packages.py          reading encrypted packages
  state.py, db.py      state and SQLite storage
deploy/bootstrap.sh    one-time server setup
docker-compose.yml     server container; data lives in /opt/phoenix/data on the server
vault/                 your encrypted packages (created by vault-init)
```

## Status

The timer, escalation, triggers, scheduling, backups, auto-reply, abort and test mode are covered by an end-to-end test against a simulated Telegram account with a fast-forwarded clock. Not yet tried on a real server: the Docker build, `bootstrap.sh`, real Telegram calls (read receipts, scheduled messages, voice and round videos) and the gocryptfs vault. Expect to fix small things during the first real setup.
