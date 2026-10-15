<div align="center">

# 🔥 Phoenix

**A self-hosted dead man's switch for Telegram.**

[![CI](https://github.com/Skerpsh/Phoenix/actions/workflows/ci.yml/badge.svg)](https://github.com/Skerpsh/Phoenix/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Your computer: Linux](https://img.shields.io/badge/your%20computer-Linux-informational)
![Server: Ubuntu | Debian](https://img.shields.io/badge/server-Ubuntu%20%7C%20Debian-informational)

</div>

If you stop checking in, or press a panic button, Phoenix delivers what you prepared in advance (letters, passwords, instructions, photos, voice and video messages) to the people you choose. Everything arrives **from your own Telegram account**, in your existing private chats, so they hear from you, not from an unknown bot or a "you've got mail" link.

Nobody needs to know about it beforehand, and each person receives only what you prepared for them.

```
 Your computer                         Your server (VPS)
┌───────────────────────┐             ┌──────────────────────────────────────────┐
│ phoenix (menu)        │  encrypted  │ timer + your control bot ◄─► you: I'm OK │
│ packages in a         │ ──────────► │ encrypted packages                       │
│ password vault        │     SSH     │ your Telegram session ──► your people    │
└───────────────────────┘             └──────────────────────────────────────────┘
```

> [!WARNING]
> **Early software.** The logic is covered by automated tests against a simulated Telegram account with a fast-forwarded clock, but Phoenix hasn't had much real-world use yet. Read the [security model](docs/security.md) and run a full **rehearsal** before you rely on it. Don't make it the only place where something important is kept.

## Contents

- [How it works](#how-it-works)
- [Features](#features)
- [What you need](#what-you-need)
- [Quick start](#quick-start)
- [Everyday use](#everyday-use)
- [Security at a glance](#security-at-a-glance)
- [Documentation](#documentation)
- [Contributing](#contributing) · [Disclaimer](#disclaimer) · [License](#license)

## How it works

1. **You prepare packages** on your computer: for each person, messages and files, and when to send them. They are kept in a password-protected vault.
2. **Phoenix encrypts them** and uploads them to your own small server. The server is logged into your Telegram account, like one more device.
3. **You check in** now and then: one tap on **"✅ I'm OK"** in your private control bot. Messages you write anywhere in Telegram count too.
4. **If you go silent,** Phoenix reminds you, then raises an alarm, and finally delivers each package to its person. A **panic button** starts delivery right away, with a time window to cancel.

With the default settings:

| After your last check-in | What happens |
|---|---|
| 7 days | check-in missed: a reminder every 12 hours |
| 14 days | 🚨 alarm: a reminder every 2 hours |
| 21 days | delivery |

Every interval can be changed. → [How it works in detail](docs/how-it-works.md)

## Features

- 📨 **Sent from your own account:** text, files in original quality, voice messages and round video messages.
- 🧑‍🤝‍🧑 **Different content for each person,** and nobody needs to know in advance.
- ⏰ **Delayed and dated letters:** "a year later", "on her birthday in 2034". Anything due within a year is handed to Telegram's own scheduled messages, so it arrives even if the server is gone by then.
- 🔁 **Backup person:** if someone doesn't read their package in time, or can't be found, it goes to someone else.
- 🚨 **Two triggers:** silence, and a panic button. Each package chooses which one sends it.
- 👤 **Account actions:** a one-time auto-reply to people who write to you, a new profile bio, and posts to groups or channels.
- 🧪 **Rehearsal:** sends everything to your own Saved Messages, exactly as your people would receive it.
- ⏹ **Undo:** stops a delivery, cancels messages already scheduled in Telegram and restores your bio.
- 🔐 **Encryption:** packages are encrypted on your computer before upload, and kept in an encrypted vault on your computer.
- 🛟 **Safety nets:**
  - warnings if the Telegram session dies;
  - hosting payment reminders;
  - "are your packages still up to date?" prompts;
  - no firing right after the server was down.
- 🧭 **One menu for everything:** setup, packages, check-ins, timers and the server, all with the arrow keys. No config files to edit.

## What you need

- **A computer with Linux** (Ubuntu, Debian, Fedora, Arch…) to prepare your packages. Nothing has to keep running on it.
- **A small server (VPS)** with Ubuntu 24.04+ or Debian 12+ and 1 GB RAM, plus disk space for your files. It costs a few euros a month. → [Choosing a server](docs/install.md#1-get-a-server)
- **Your Telegram account.** During setup you also create three things, which takes about 10 minutes, and the setup explains each one:
  - a bot, via @BotFather;
  - your user id;
  - API keys from my.telegram.org.
- **About 30–45 minutes** for the first setup.

## Quick start

**1. Install Phoenix on your computer**

```bash
curl -fsSL https://raw.githubusercontent.com/Skerpsh/Phoenix/main/install.sh | bash
```

The installer:

1. asks before installing the tools Phoenix needs (`python3`, `git`, `ssh`, `rsync`, `age`, `gocryptfs`);
2. downloads Phoenix;
3. creates the `phoenix` command.

It never touches your server.

<details>
<summary>Prefer to do it by hand?</summary>

```bash
# Arch:           sudo pacman -S --needed python git openssh rsync age gocryptfs
# Debian/Ubuntu:  sudo apt install python3 git openssh-client rsync age gocryptfs
# Fedora:         sudo dnf install python3 git openssh-clients rsync age gocryptfs
git clone https://github.com/Skerpsh/Phoenix.git ~/.local/share/phoenix/app
mkdir -p ~/.local/bin && ln -s ~/.local/share/phoenix/app/cli/phoenix ~/.local/bin/phoenix
```

</details>

**2. Run it**

```bash
phoenix
```

The first run walks you through setup, one step at a time. You can stop at any point and continue later:

| | Step | What you do |
|---|---|---|
| 1 | Connect to your server | type its IP address (and its password, once) |
| 2 | Prepare the server | wait a few minutes: updates, Docker, firewall |
| 3 | Install Phoenix on the server | wait |
| 4 | Connect your bot and API keys | follow the on-screen instructions |
| 5 | Log in to Telegram | your phone number, then the code from the Telegram app |
| 6 | Password-protect your packages | choose a password; **write down the master key** |
| 7 | Say hello to your bot | press **Start** in your bot |

→ [Installation guide](docs/install.md), with every step explained

**3. Add your people, then rehearse**

In the menu:

1. **📦 Recipients** → add a person → write messages and add files.
2. **⬆️ Upload**.
3. **🧪 Rehearsal**.

Then open Telegram → Saved Messages to see exactly what they will receive.

## Everyday use

Run `phoenix`. The top of the screen shows how things stand. Move with **↑/↓**, choose with **Enter**, go back with **Esc**.

```
🔥 Phoenix  root@203.0.113.7
🟢 armed · next check-in in 6d 23h
If you stay silent, delivery starts in 20d 23h
Telegram: ✅ logged in as Alex (@alex)
Packages on the server: 3

What do you want to do?
 ❯ ✅ I'm OK: check in
   📦 Recipients and what they receive
   👤 Your account after the trigger: auto-reply, bio, posts
   ⬆️ Upload changes to the server
   🧪 Rehearsal: send everything to my Saved Messages
   🔎 Check that every recipient can be found
   ⏸ Pause: going offline for a while
   ⏱ Timers and reminders
   🚨 Panic button
   📜 History
   🖥 Server
   🔐 Vault on this computer
   ← Quit
```

Day to day, you don't need the computer at all. Your control bot in Telegram has the **"✅ I'm OK"** button and commands such as `/status`, `/pause 14d` and `/panic`.

→ [Using Phoenix](docs/usage.md): packages, scheduling, backups, timers, the bot, updating, moving and uninstalling

## Security at a glance

- 🔒 **Packages are encrypted on your computer** before they leave it, and stored on the server under anonymous names. A leaked disk or hosting backup reveals nothing readable.
- 🔐 **On your computer they're kept in a password vault**, which is open only while the menu runs.
- 🚪 **The server exposes only SSH, with key login.** The bot answers only you.
- ⚠️ **The server holds your Telegram session and the key to your packages.** That's what lets it act when you can't, but it also means whoever controls the server controls your Telegram account. Use a dedicated server and keep it to yourself.

→ [Security model](docs/security.md) · [Reporting a vulnerability](SECURITY.md)

## Documentation

| Guide | What's inside |
|---|---|
| [Installation guide](docs/install.md) | choosing a server, every setup step, getting the bot token and API keys |
| [Using Phoenix](docs/usage.md) | packages, delays, backups, account actions, timers, the bot, updates, uninstalling |
| [How it works](docs/how-it-works.md) | timeline, triggers, scheduling, guarantees, architecture |
| [Security model](docs/security.md) | what is protected, and what isn't |
| [Troubleshooting & FAQ](docs/troubleshooting.md) | when something doesn't work |

## Contributing

Bug reports and pull requests are welcome, especially reports from real-world setups. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup and tests.

## Disclaimer

Phoenix automates **your own** Telegram account through Telegram's official API. Use it only for your account and its intended purpose: sending spam or bulk messages can get an account restricted under Telegram's terms. The software is provided as is, without warranty. Pair it with proper legal arrangements, such as a will, where those matter.

## License

[MIT](LICENSE) © 2026 Skerpsh
