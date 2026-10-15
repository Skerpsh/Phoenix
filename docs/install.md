# Installation guide

This guide takes you from nothing to a working Phoenix: about 30–45 minutes, most of it waiting. You don't need to know Linux or servers: `phoenix` does the work and tells you what to type.

1. [Get a server](#1-get-a-server)
2. [Install Phoenix on your computer](#2-install-phoenix-on-your-computer)
3. [Run the setup](#3-run-the-setup)
4. [After the setup](#4-after-the-setup)

---

## 1. Get a server

Phoenix runs on a small rented server (a **VPS**), so it keeps watching when your computer is off, lost or broken.

**What to order:**

| | |
|---|---|
| Operating system | **Ubuntu 24.04** (recommended) or newer, or **Debian 12** or newer |
| Memory | 1 GB RAM is enough |
| Disk | 10 GB, plus about twice the size of the files you want to send |
| Location | anywhere; closer to you is slightly faster |

Any VPS provider works (for example Hetzner, OVHcloud, DigitalOcean, Vultr, Contabo, Scaleway). The cheapest plan is usually enough. **Prepay for as long as you can**: if the bill isn't paid, the server stops, and with it Phoenix. Phoenix reminds you before the date you give it.

> [!IMPORTANT]
> **Use a server only for Phoenix.** It will be logged into your Telegram account, so anyone who controls the server controls your Telegram. Don't share it with other projects or people. See [security](security.md).

After ordering, your host gives you (in the control panel or by email):

- the server's **IP address**, for example `203.0.113.7`;
- a **user**, usually `root` (some hosts, such as OVHcloud or AWS, use `ubuntu`);
- a **password** for it, or a way to add an SSH key.

Keep these at hand. If the host lets you add an SSH key when ordering, you may skip that: Phoenix sets one up for you in step 1 of the setup.

---

## 2. Install Phoenix on your computer

You need a computer with **Linux**. macOS should work without the password vault, but it isn't tested. Open a terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/Skerpsh/Phoenix/main/install.sh | bash
```

The installer:

1. checks for the tools Phoenix needs and, **after asking you**, installs the missing ones with your system's package manager (it may ask for your computer password, for `sudo`):

   | Tool | What it's for |
   |---|---|
   | `python3` (3.11 or newer) | runs Phoenix |
   | `git` | downloads and updates Phoenix |
   | `ssh`, `rsync` | talk to your server |
   | `age` | encrypts your packages before upload |
   | `gocryptfs` | the password vault on your computer |
2. downloads Phoenix into `~/.local/share/phoenix/app`;
3. creates the command `~/.local/bin/phoenix`, and offers to add `~/.local/bin` to your `PATH` if it isn't there yet (then open a new terminal window).

You can read [`install.sh`](../install.sh) before running it: it's short and only touches your computer.

<details>
<summary>Installing by hand instead</summary>

```bash
# 1. Tools:
#   Arch:           sudo pacman -S --needed python git openssh rsync age gocryptfs
#   Debian/Ubuntu:  sudo apt install python3 git openssh-client rsync age gocryptfs
#   Fedora:         sudo dnf install python3 git openssh-clients rsync age gocryptfs
#   openSUSE:       sudo zypper install python3 git openssh-clients rsync age gocryptfs
# 2. Phoenix:
git clone https://github.com/Skerpsh/Phoenix.git ~/.local/share/phoenix/app
# 3. The command:
mkdir -p ~/.local/bin && ln -s ~/.local/share/phoenix/app/cli/phoenix ~/.local/bin/phoenix
```

On Ubuntu 22.04 the system Python is too old: also run `sudo apt install python3.11` (Phoenix finds it automatically).

</details>

---

## 3. Run the setup

```bash
phoenix
```

The first time, `phoenix` shows the setup checklist. Choose **▶ Continue** for each step. If a step fails, it shows what went wrong and lets you try again. You can quit at any time (**Esc**), and the next `phoenix` continues where you stopped.

```
🔥 Phoenix setup
Step by step; you can quit any time and continue later.

 ✅ 1. Connect to your server
 ➜  2. Prepare the server: updates, Docker, firewall
    3. Install Phoenix on the server
    4. Connect your control bot and Telegram API keys
    5. Log the server into your Telegram account
    6. Password-protect your packages on this computer
    7. Say hello to your bot
```

### Step 1: Connect to your server

Type the server's IP address, for example `203.0.113.7`. If your host gave you a user other than `root`, type it in front: `ubuntu@203.0.113.7`.

Phoenix logs in with an **SSH key** instead of a password:

- If your computer has no SSH key yet, Phoenix creates one. It asks for a *passphrase* to protect the key: type one you'll remember, or press Enter twice for none.
- Phoenix then copies the key to the server. When asked, **type the server's password** from your host (the characters don't show up while typing; that's normal). This is the last time you need it.

> The first time you connect, you'll see `Warning: Permanently added '203.0.113.7' to the list of known hosts`. That's normal: your computer now remembers this server.

A user other than `root` needs passwordless `sudo`, which is the default on cloud images. Phoenix checks this and tells you if it's missing.

### Step 2: Prepare the server

This takes a few minutes and prints a lot of text, which is normal. It:

- installs system updates and turns on automatic security updates;
- installs Docker, which runs Phoenix on the server;
- turns on the firewall, allowing only SSH;
- installs fail2ban against password guessing;
- **turns off password login over SSH**: from now on only your key works. Keep the key safe (it's in `~/.ssh/` on your computer).

> [!NOTE]
> Existing firewall rules are kept. But if the firewall was off and the server already runs something else (a website, for example), that becomes unreachable until you allow its port: `ufw allow 443/tcp`. Phoenix itself needs no open ports, which is one more reason to use a dedicated server.

### Step 3: Install Phoenix on the server

Phoenix uploads its server part and builds it. The first time takes a few minutes. It also creates the server's encryption key: your computer encrypts packages with it, and only the server can decrypt them.

### Step 4: Connect your control bot and Telegram API keys

Phoenix asks for four things and explains each one on screen. Here's how to get them.

**1. Bot token.** The bot is your private remote control: it reminds you to check in and has the "✅ I'm OK" button.

1. In Telegram, open [@BotFather](https://t.me/BotFather) and send `/newbot`.
2. Choose a display name (anything, e.g. "My Phoenix"), then a username ending in `bot` (e.g. `alex_phoenix_bot`).
3. BotFather replies with a **token** like `123456789:AAHk3…`. Copy all of it and paste it into Phoenix. It's hidden while you type or paste.

Don't share the token with anyone. If it leaks, send `/revoke` to BotFather and enter the new token in Phoenix (Server → Change the bot token or Telegram API keys).

**2. Your user id.** This makes the bot obey only you. Open [@userinfobot](https://t.me/userinfobot), press **Start**, and copy the number after `Id`.

**3. API keys (`api_id` and `api_hash`).** These let the server use your Telegram account, the same way any Telegram app does.

1. Open [my.telegram.org](https://my.telegram.org) in a browser and log in with your phone number. The code arrives **in your Telegram app**, not by SMS.
2. Click **API development tools**.
3. Fill in the form: *App title* and *Short name* can be anything (e.g. `phoenix` and `phoenixapp`); choose platform **Desktop**; leave the URL empty. Click **Create application**.
4. Copy **App api_id** (a number) and **App api_hash** (32 letters and digits) into Phoenix.

> If my.telegram.org only says "ERROR" when you create the app, try again later, from another browser, or without a VPN or ad blocker. This is a known quirk of that site.

**4. Your time zone.** It's used for letters scheduled on a date, such as a birthday at 09:00. Phoenix suggests your computer's time zone, so press Enter to accept it.

**Optional: a heartbeat URL.** If you'd like an email when the server goes down:

1. Create a free check at [healthchecks.io](https://healthchecks.io) with a period of 5 minutes.
2. Paste its ping URL (`https://hc-ping.com/…`).

Press Enter to skip.

Everything is saved only on your server, in a file readable only by its administrator.

### Step 5: Log the server into your Telegram account

The server now logs into **your main Telegram account**, the same way a new phone or computer would, so it can later send messages as you.

1. Enter your **phone number** in international format: `+380…`, `+49…`, `+1…`.
2. Enter the **code**. Telegram sends it to your Telegram app (look for a message from "Telegram"), not by SMS.
3. If you use a **cloud password** (two-step verification), enter it too.

Telegram notifies you about the new login. That's expected. It appears in Telegram → Settings → Devices.

> [!WARNING]
> Don't press **"Terminate all other sessions"** in Telegram later: that logs Phoenix out too. If it happens, the bot warns you within 6 hours. Fix it with Server → Log in to Telegram again.

### Step 6: Password-protect your packages on this computer

Your packages will hold passwords and private letters. The vault keeps them encrypted on your computer and opens them only while the Phoenix menu runs.

1. Choose a password. You'll type it each time you work on your packages.
2. Phoenix (gocryptfs) prints a **master key**: a long line of letters and digits. **Write it on paper** and keep it somewhere safe. It's the only way to open the vault if you forget the password.

You can skip this step, but then your packages lie on your computer unencrypted. You can turn the vault on later: 🔐 Vault on this computer.

### Step 7: Say hello to your bot

Open your bot in Telegram (the username you chose in step 4) and press **Start**. It replies **"🔥 Phoenix is armed"**, and the timer is now running.

Phoenix then asks until what date your server is paid. Enter it as `2027-10-01` to get reminders 30, 14 and 7 days before; or press Enter and set it later (Server → Hosting paid until).

---

## 4. After the setup

1. **Telegram self-destruct.** Telegram deletes accounts that are inactive for a while, and a deleted account can't deliver anything. Go to Telegram → Settings → Privacy and Security → **"If away for"** and choose the longest period.
2. **Add your people:** 📦 Recipients and what they receive. → [Using Phoenix](usage.md#packages)
3. **Upload** (⬆️), then wait for the bot's **"📦 Packages updated"** message: it confirms that every person was found in Telegram.
4. **Rehearse** (🧪): everything goes to your own Saved Messages, exactly as each person will receive it. Look through it carefully.
5. **Get used to checking in.** Tap "✅ I'm OK" in the bot when it reminds you. Messages you send anywhere in Telegram count too, but the button is still needed at least every 30 days.

Something not working? → [Troubleshooting](troubleshooting.md)
