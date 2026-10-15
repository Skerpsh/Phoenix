# Security policy

Phoenix holds very sensitive things: a logged-in Telegram session and people's last messages. Security reports are taken seriously.

## Reporting a vulnerability

**Please don't open a public issue for security problems.** Report them privately through GitHub: **Security → Report a vulnerability** on this repository ([direct link](https://github.com/Skerpsh/Phoenix/security/advisories/new)).

Please include what an attacker could do, the steps to reproduce, and the Phoenix version (the commit, or the date you installed it). You'll get an answer within a week. Fixes are released as soon as possible, and you'll be credited unless you prefer not to be.

## Supported versions

Only the latest version on the `main` branch gets fixes. Update with 🖥 Server → ⬆️ Update Phoenix, or `phoenix update`.

## Scope

What Phoenix does and does not protect against is described in [docs/security.md](docs/security.md). Especially welcome:

- ways to read packages without the server's key or the vault password;
- ways for anyone but the owner to control the bot or trigger, delay or cancel a delivery;
- ways delivery could silently fail, or send something to the wrong person;
- weaknesses in the server setup (`deploy/bootstrap.sh`) or in `install.sh`.
