# Security model

Phoenix has to do something unusual: **act on your behalf when you can't.** That shapes everything below. Read this page before trusting Phoenix with anything sensitive.

## What Phoenix protects

| Threat | Protection |
|---|---|
| Someone gets hold of the uploaded package files, or watches the upload | Packages are encrypted **on your computer** with the server's [age](https://github.com/FiloSottile/age) public key; upload goes over SSH. Folder and file names on the server are hashed with a secret that stays on your computer, so the package files alone reveal neither who receives them nor what they are. |
| Someone reads your packages on your computer | The [gocryptfs](https://github.com/rfjakob/gocryptfs) vault keeps them encrypted; they're readable only while the Phoenix menu (or `phoenix push`) runs, and the vault locks when the menu exits, even if the terminal is closed. |
| Someone attacks the server over the network | Nothing listens except SSH, with password login switched off and fail2ban on. The firewall is enabled and security updates are installed automatically. |
| Someone else uses your control bot | The bot ignores everyone except your Telegram user id. |
| Someone who has your phone keeps postponing delivery just by using Telegram | Telegram activity alone isn't enough: an explicit check-in is required at least every 30 days (`button_every`). |
| Someone who has your phone switches Phoenix off through the bot | The bot can only make the delaying timers shorter and pause for 30 days at a time, and it can stop a delivery only within 2 days of its start. Everything beyond that needs the menu on your computer (your SSH key). All timers have upper limits. |
| An old server keeps running after a move | Moving stops the old server first; if two programs ever read your bot at once, Phoenix warns you in the bot and in the menu. |
| The server was down and fires the moment it's back | The alarm phase always runs for at least a day (`alarm_min`) before delivery. |
| Someone forces you to check in or to cancel | The duress code looks like an ordinary check-in but quietly starts the panic delivery; the bot keeps showing a normal status and ignores attempts to cancel. Only a salted hash of the code is stored. |
| A mistake: wrong person, wrong text | The `t.me` link check while typing usernames; the recipient check after every upload; the rehearsal; **Stop the delivery** cancels anything still scheduled. |

## What Phoenix does **not** protect against

- **A copy of the whole server.** To deliver without you, the server must hold the age private key that decrypts your packages, and **a logged-in session of your Telegram account**. It also keeps a database with your recipients' names and usernames, for the status and the event log. So anyone with the whole server can read your packages and use your Telegram account as you. That includes a hacked server, and **also a full hosting backup or snapshot**, or the provider's staff. Treat server backups like your Telegram password. So:
  - use a server **only for Phoenix**;
  - keep your SSH key safe and protect it with a passphrase;
  - choose a hosting provider you trust, and don't turn on its backups or snapshots unless you trust where they're kept;
  - don't give anyone else access.
- **A compromised computer.** Malware on your computer can read your packages while the vault is open, and can use your SSH key.
- **Telegram itself.** Delivered messages are ordinary Telegram cloud chats. They aren't end-to-end encrypted, so Telegram can technically read them. For the most sensitive things, such as master passwords, consider handing over access to a password manager (many offer "emergency access") instead of the passwords themselves.
- **Recipients.** Once something is delivered, it can't be taken back. Messages still scheduled in Telegram can be cancelled with **Stop the delivery**.
- **Pressure on you,** partly. The [duress code](usage.md#duress-code) lets you raise a silent alarm while appearing to check in. It doesn't help if you're forced to use your computer, or if the attacker knows about the duress code and watches your Telegram for outgoing messages.

## Things that can stop delivery

Phoenix warns you about each of these when it can. Check in on them yourself now and then.

- **The server isn't paid.** Prepay, and set the paid-until date: you get reminders 30, 14 and 7 days before.
- **Your Telegram session ends.** "Terminate all other sessions" in Telegram, or removing the session under Settings → Devices, logs Phoenix out. The bot warns you within 6 hours; fix it with Server → Log in to Telegram again.
- **Telegram deletes your account for inactivity.** Set Settings → Privacy and Security → **"If away for"** to the longest period. If nothing is sent from your account for that long after a trigger, Telegram may delete it, including scheduled messages that haven't been delivered yet.
- **A person can't be found** (a deleted account, or a typo). The recipient check after each upload shows this. Add a backup person to be safe.
- **Telegram restricts the account** for unusual activity. Phoenix sends calmly, one person at a time, but very large deliveries to many people carry some risk.

## Recommendations

1. Enable **two-step verification** (a cloud password) in Telegram.
2. Use a **dedicated server**, and an SSH key with a passphrase.
3. Turn on the **vault**, and keep its **master key** on paper, somewhere safe.
4. Run the **rehearsal** after every important change.
5. Choose timers that fit your life: long enough not to fire during an illness or a trip (use **Pause**), short enough to be useful.
6. Don't let Phoenix be the only place where important information exists.

Found a vulnerability? Please report it privately: see [SECURITY.md](../SECURITY.md).
