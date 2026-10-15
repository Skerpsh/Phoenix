# Using Phoenix

- [The menu](#the-menu)
- [Checking in](#checking-in)
- [Packages](#packages)
- [Your account after the trigger](#your-account-after-the-trigger)
- [Upload, check, rehearse](#upload-check-rehearse)
- [Timers and reminders](#timers-and-reminders)
- [Pause, panic, stop](#pause-panic-stop)
- [The control bot](#the-control-bot)
- [The server menu](#the-server-menu)
- [Updating Phoenix](#updating-phoenix)
- [Backups](#backups)
- [Uninstalling](#uninstalling)

---

## The menu

Run `phoenix` in a terminal. Move with **↑/↓** (or `j`/`k`), choose with **Enter** (or the item's number), go back with **Esc** (or `q`).

The top of the screen shows:

- the state: 🟢 armed, 🟡 check-in overdue, 🔴 alarm, 🔥 delivering, or ⚫ delivered;
- the time to your next check-in, and when delivery would start if you stayed silent;
- whether the Telegram session works;
- how many packages are on the server;
- whether you have changes that aren't uploaded yet.

The first time you open your packages, Phoenix asks for the vault password. The vault stays open until you quit the menu, then locks again, even if you just close the terminal window. Your SSH key's passphrase, if it has one, is asked once per session.

## Checking in

Any of these resets the timer:

- **"✅ I'm OK"** in your control bot, or **any message** you send to the bot;
- **✅ I'm OK: check in** in the menu, or `phoenix checkin` in a terminal;
- **any message you send anywhere in Telegram**, from any device.

Your Telegram activity alone isn't enough forever: an explicit check-in (the button, or a message to the bot) is still needed at least every 30 days. Otherwise someone with access to your phone could postpone delivery indefinitely just by using Telegram. You can turn activity check-ins off in ⏱ Timers and reminders.

## Packages

A **package** is everything one person receives. Open **📦 Recipients and what they receive**.

### Adding a person

Choose **➕ Add a recipient**, then type:

- **their name.** Only you see it.
- **their Telegram**, in any of these forms:
  - `@username`, or just `username`;
  - a link: `t.me/username`;
  - a phone number: `+380501234567`. It must be saved in your Telegram contacts.

Phoenix prints a `https://t.me/…` link. Open it to make sure it's the right person: a typo would send your letter to a stranger.

### Adding content

Choose a person to see what they'll receive, in order, and what you can do:

| Action | What it does |
|---|---|
| ✍️ **Write a message** | Type or paste text right in the terminal. To finish, press Enter on two empty lines in a row. Long messages are split automatically. |
| 📎 **Add files** | **Drag** files or folders from your file manager into the terminal window (this pastes their paths), then press Enter. |
| 📝 **Edit a message** | Opens it in a text editor (`nano` by default: save with Ctrl+O, Enter; exit with Ctrl+X). |
| 🗑 **Remove something** | Removes one item from the list. |
| ⚙️ **Settings** | Name, Telegram, when to send, delay, backup person (see below). |
| 📂 **Open their folder** | Opens the folder in your file manager. You can add or rename files there too. |
| ❌ **Delete this recipient** | Deletes the person and everything prepared for them. |

How things arrive:

| What you add | Arrives as |
|---|---|
| a written message, or a `.txt` / `.md` file | a text message |
| `.ogg`, `.oga`, `.opus` | a **voice message** |
| an `.mp4` you mark as round | a **round video message**. Must be square and up to 60 seconds; Phoenix asks for each `.mp4` |
| anything else: photos, videos, documents, archives | a file in original quality, up to 2 GB each |

> [!TIP]
> **Recording voice or round video messages.** The easiest way is in Telegram itself: record one in your own Saved Messages. Then, in Telegram Desktop, right-click it → **Save As**. A voice message saves as `.ogg` and a round video as `.mp4`, ready to add.

### When things are sent

Whenever you add a message or files, Phoenix asks:

- **Together with the rest:** right when the package is sent.
- **Some time later:** for example `1y` for a year later, or `30d`.
- **On a specific date:** for example a birthday, `2034-05-12`, at 09:00 in your time zone, or at a time you give (`2034-05-12 18:30`). A date that has already passed by then is sent right away.

Items are sent in the order shown in the list.

### Settings for a person

| Setting | Meaning |
|---|---|
| **When should this be sent?** | If you stop checking in, or on the panic button, or both (the default). For example: a "what to do right now" note on panic, and everything else on silence. |
| **Wait after the trigger** | Hold the whole package back for a while, e.g. `3d`. |
| **Backup person** | If they haven't read the package within the time you choose (default 7 days), or can't be found at all, the same package goes to the backup person. It starts with a short note explaining why; you can write your own note. |

### Writing tips

- **The first message should explain what is happening,** for example: *"If you're reading this, something has happened to me. This was sent automatically; I prepared it in advance."*
- **For anything that needs action, write concrete steps:** where to log in, what to do first, who to contact.
- **Passwords:** consider giving access to a password manager (many have an "emergency access" feature) instead of listing every password. Delivered messages sit in an ordinary Telegram chat.
- **Review your packages now and then.** Phoenix reminds you every 90 days.

## Your account after the trigger

**👤 Your account after the trigger** lists optional things Phoenix does with your account once it's triggered:

- **Auto-reply:** sent once to each person who writes to you in a private chat. It's never sent to your recipients, bots or groups.
- **New profile bio:** up to 70 characters (140 with Telegram Premium). It's restored if you stop the delivery.
- **Posts:** messages to groups, channels or people, optionally delayed (`1d` after the trigger). You must be able to write there.
- **When to run:** on silence (the default), on panic, or both.

## Upload, check, rehearse

- **⬆️ Upload changes to the server.** Phoenix first checks your packages:
  - no Telegram set;
  - nothing to send;
  - files over 2 GB;
  - text that isn't UTF-8.

  It tells you exactly what to fix, then encrypts and uploads. Only changed files are encrypted again.

  Within a minute your bot sends **"📦 Packages updated"**, with every person it found in Telegram, delays, backups and warnings. When you quit, Phoenix offers to upload anything that isn't on the server yet.
- **🔎 Check that every recipient can be found** runs the same check on demand.
- **🧪 Rehearsal** sends everything to your own **Saved Messages**, exactly as each person will receive it, plus notes such as "the next items arrive 1 year later". Nothing goes to anyone else.

## Timers and reminders

**⏱ Timers and reminders** shows the current values and a summary of what happens when. Choose a line to change it. Durations are written as a number with a unit: `30m` (minutes), `12h`, `7d`, `2w`, `1y`, or combinations such as `1d12h`.

| Setting | Default | Meaning | Bot name |
|---|---|---|---|
| Check in at least every | 7d | how long you can be silent before Phoenix starts reminding you | `checkin_interval` |
| Press "I'm OK" at least every | 30d | an explicit check-in is needed this often, even if you're active in Telegram | `button_every` |
| After a missed check-in, remind me every | 12h | reminder frequency | `reminder_every` |
| Alarm starts this long after a missed check-in | 7d | when reminders turn into an alarm | `alarm_after` |
| During the alarm, remind me every | 2h | alarm frequency | `alarm_every` |
| Delivery this long after a missed check-in | 14d | when packages are sent | `trigger_after` |
| The alarm always lasts at least | 1d | if the server was down for a while, it never delivers right after coming back | `alarm_min` |
| Time to cancel after the panic button | 1h | how long you have to change your mind | `panic_delay` |
| Ask me to review my packages every | 90d | "are your packages still up to date?" | `review_every` |
| Telegram activity counts as a check-in | on | messages you send anywhere count | `/activity` |

With the defaults, delivery happens after **21 days** of total silence. Pick values that fit your life: a long hospital stay or a trip without internet shouldn't trigger it. That's what the pause is for, too.

## Pause, panic, stop

| Menu item | What it does |
|---|---|
| ⏸ **Pause** | Going offline for a while (a trip, hospital)? Nothing is sent during the pause, and the timer starts again when it ends. |
| ▶️ **End the pause** | Ends it early, and counts as a check-in. |
| 🚨 **Panic button** | Starts delivery after the cancel window (default 1 hour). Packages set to "on panic" are sent. |
| ✋ **Cancel the panic** | Shown while the cancel window is open. |
| ⏹ **Stop the delivery** | Shown while delivering: stops it, cancels messages already scheduled in Telegram, restores your bio, and arms Phoenix again. Messages already delivered can't be taken back. |
| 🔁 **Arm Phoenix again** | After a completed delivery, starts watching again. |

## The control bot

Day to day you can do everything from Telegram. The bot ignores everyone except you.

| Command | What it does |
|---|---|
| "✅ I'm OK", `/checkin`, or any message | check in |
| `/status` | state, time left, Telegram session, hosting |
| `/pause 14d`, `/resume` | pause / end the pause |
| `/panic`, `/cancel` | panic (asks to confirm) / cancel it |
| `/abort` | stop a delivery or a rehearsal |
| `/rearm` | arm again after a delivery |
| `/test` | rehearsal |
| `/verify` | check that every person can be found |
| `/settings`, `/set <name> <duration>` | show / change timers, e.g. `/set checkin_interval 5d` |
| `/activity on` or `/activity off` | count your Telegram activity as a check-in |
| `/paiduntil 2027-10-01` | hosting paid-until date, for reminders |
| `/log` | recent events |
| `/help` | help |

## The server menu

**🖥 Server**:

| Item | When to use it |
|---|---|
| 📋 Full status | everything the server knows about the switch |
| ⬆️ Update Phoenix | after a new version is released (see below) |
| 🔄 Restart Phoenix | if the bot doesn't answer |
| 📜 Live server logs | to see what's happening; Ctrl+C to stop |
| 💳 Hosting paid until… | after you renew your server |
| 🔑 Change the bot token or Telegram API keys | a new bot, new keys, another time zone, a heartbeat URL |
| 📱 Log in to Telegram again | the bot reports "Telegram account problem" |
| 🛠 Prepare the server again | re-run step 2 of the setup (safe to repeat) |
| 🚚 Move Phoenix to another server | set up a new server and upload your packages to it |
| 🧹 Remove Phoenix from this server | see [Uninstalling](#uninstalling) |

## Updating Phoenix

Choose **🖥 Server → ⬆️ Update Phoenix**. It downloads the latest version to your computer, updates the server, and restarts the menu. From a terminal you can also run `phoenix update`, or run the installer again.

If the menu says **"The server runs an older Phoenix"**, you updated your computer but not the server yet: choose Update.

## Backups

- **Your packages** live in the vault on your computer: `~/.local/share/phoenix/vault` (or `vault/` inside the Phoenix folder, if you installed an early version). Copy that folder anywhere: a USB stick, the cloud. Without your password or **master key** it's unreadable. Keep the master key on paper.
- **The server** is not backed up by Phoenix, and doesn't need to be. If it's lost while you're alive, choose 🚚 Move Phoenix to another server: the setup runs again and your packages are uploaded from your computer.

## Uninstalling

1. In the menu: **🖥 Server → 🧹 Remove Phoenix from this server.** It logs the server out of your Telegram account and deletes Phoenix, your packages, keys and settings from the server.
2. In Telegram: delete the control bot with [@BotFather](https://t.me/BotFather) (`/deletebot`). Under Settings → Devices, check that no Phoenix session is left.
3. On your computer:

   ```bash
   rm ~/.local/bin/phoenix
   rm -rf ~/.local/share/phoenix ~/.config/phoenix ~/.cache/phoenix   # deletes your packages too!
   ```

4. Cancel the server at your hosting provider.

## Command-line shortcuts

`phoenix` with no arguments opens the menu, which does everything. For scripts:

| Command | |
|---|---|
| `phoenix checkin` | check in |
| `phoenix status` / `phoenix log` | the switch state / recent events |
| `phoenix push` | upload your packages |
| `phoenix update` | update Phoenix here and on the server |
| `phoenix logs` | follow the server logs |
| `phoenix lock` | lock the vault if it stayed open |
