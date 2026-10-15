# Troubleshooting & FAQ

- [Installing](#installing)
- [Setup](#setup)
- [Everyday use](#everyday-use)
- [FAQ](#faq)

When something fails, Phoenix shows a line starting with ❌ that says what went wrong. **🖥 Server → 📜 Live server logs** shows what the server is doing, and **📜 History** shows recent events.

## Installing

| Problem | Fix |
|---|---|
| `phoenix: command not found` | Open a new terminal window. If it still happens, `~/.local/bin` isn't in your `PATH`: run `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc` (or `~/.zshrc`), then open a new window. |
| "Phoenix needs Python 3.11 or newer" | Ubuntu 22.04: `sudo apt install python3.11`. Other systems: install a newer Python from your package manager. |
| "… not installed. Install with: …" | Run the command Phoenix shows, then try again. |
| `gocryptfs` can't be installed | Skip the vault in setup step 6. Your packages then stay unencrypted on your computer. |

## Setup

| Problem | Fix |
|---|---|
| Step 1: `Permission denied` when copying the key | The password was wrong. Check it in your hosting panel; many hosts can reset it. |
| Step 1: `Connection timed out` / `No route to host` | Check the IP address, and that the server is running in your hosting panel. |
| Step 1: SSH on a port other than 22 | Add the server to `~/.ssh/config` (`Host myvps`, `HostName 203.0.113.7`, `Port 2222`, `User root`) and type `myvps` as the address. |
| Step 1: "is not root and can't use sudo without a password" | Log in as `root` instead, or ask your host how to enable passwordless sudo. |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | You reinstalled the server with the same IP. Run `ssh-keygen -R 203.0.113.7` (your IP), then try again. |
| Step 2 fails during `apt` | The server may still be installing updates by itself right after creation. Wait 5 minutes, then try again. |
| Step 3: building fails | Re-run the step. If it fails again, check the disk isn't full (`df -h` on the server). |
| Step 4: my.telegram.org says "ERROR" | Try later, from another browser, or without a VPN or ad blocker. |
| Step 5: no login code arrives | It comes **in the Telegram app** (from "Telegram"), not by SMS. Make sure the phone number has the `+` and country code. |
| Step 7: the bot doesn't answer Start | Wait a minute, then try again. Check the token and user id (Server → Change the bot token or Telegram API keys) and look at Server → Live server logs. |

## Everyday use

| Problem | Fix |
|---|---|
| "The server runs an older Phoenix" | Server → Update Phoenix. |
| "Control bot: …" in the menu | The bot can't connect or its token was revoked. Phoenix keeps watching your Telegram activity and still delivers, but fix it: Server → Change the bot token or Telegram API keys. |
| "Another program is reading your bot" | Phoenix probably still runs on an old server. Remove it (point the menu at it, then Server → Remove Phoenix from this server) or delete that server at your host. |
| "Unknown time zone" | Server → 🕐 Time zone, and search for your city. Until then, dated letters use UTC. |
| The bot says a timer "can only be made shorter" | That's on purpose: make timers longer from the menu on your computer (⏱ Timers and reminders). |
| "Phoenix is not running on the server" | Server → Restart Phoenix. If it stops again, look at Server → Live server logs. |
| "Cannot connect to the server" | Is the server running and paid? Is your internet working? |
| Bot reports "Telegram account problem" | The session was logged out: Server → Log in to Telegram again. |
| "Not uploaded. Fix these first" | Each line names the person, the item and what to do. |
| `❌ cannot find @someone` in the recipient check | Check the username with its `t.me` link. Phone numbers must be saved in your Telegram contacts. |
| "Could not lock the vault" | Close file manager windows and terminals that are inside the vault folder, then run `phoenix lock`. |
| Forgot the vault password | `gocryptfs -passwd -masterkey=<your master key> ~/.local/share/phoenix/vault` |
| "Terminal size too small" | Make the window at least 80×24 (maximize it, or make the font smaller). Phoenix continues by itself. |
| Dated letters arrive at the wrong hour | Fix the time zone: Server → 🕐 Time zone. |

## FAQ

**Do the people I choose need to do anything, or know about Phoenix?**
No. They just receive messages from you in Telegram.

**Does my computer need to stay on?**
No. Your computer is only for preparing packages. The server does the watching and the sending.

**What if my computer is lost or broken?**
Phoenix keeps working: everything it needs is on the server. To change your packages again, install Phoenix on another computer and restore your vault folder from a backup. Without a backup, you'd have to write your packages again. To control the server from a new computer, its SSH key must be allowed on the server: add it through your hosting provider's console, or copy your old `~/.ssh` key over.

**What if the server dies or the hosting provider closes?**
Nothing is delivered while it's down; after the server comes back, you get at least a day of alarm before any delivery. If it's gone for good: 🖥 Server → 🚚 Move Phoenix to another server.

**Can I use macOS or Windows?**
The computer side is written for Linux. On macOS it should work without the vault (gocryptfs needs Linux), but this isn't tested. On Windows, use WSL (Ubuntu) and follow the Linux instructions. The server must be Linux (Ubuntu or Debian).

**Can I run the server at home, on a Raspberry Pi?**
Technically yes, if it runs Ubuntu or Debian with Docker. But a home server goes down with your power or internet, and your family might unplug it. A rented VPS is more reliable.

**How much does it cost?**
The server, usually a few euros a month. Phoenix itself is free.

**Can I see what was sent?**
Yes: in Telegram, the chats with your people, from your account. Messages Phoenix scheduled for later are in each chat's **Scheduled messages** list. Before a trigger, the **rehearsal** shows everything in your Saved Messages.

**Is this allowed by Telegram?**
Phoenix uses Telegram's official API with your own account, like any third-party Telegram app. Telegram may restrict accounts that send spam or bulk messages; Phoenix is meant for a handful of personal messages.
