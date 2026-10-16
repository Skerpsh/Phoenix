"""Paths, settings on this PC, SSH to the server, server setup steps and the local vault."""

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # this copy of Phoenix (the code)
CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "phoenix" / "config.json"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "phoenix"
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "phoenix"  # your packages
# Older versions kept the vault next to the code; keep using it there if it exists.
VAULT = Path(os.environ.get("PHOENIX_VAULT") or (
    ROOT / "vault" if (ROOT / "vault" / "gocryptfs.conf").exists() else DATA / "vault"))
DEFAULT_PACKAGES = DATA / "packages"

REQUIRED_TOOLS = ("ssh", "ssh-copy-id", "rsync", "age")
PACKAGE_NAMES = {  # tool -> package name, per package manager
    "pacman": {"ssh": "openssh", "ssh-copy-id": "openssh", "git": "git"},
    "apt": {"ssh": "openssh-client", "ssh-copy-id": "openssh-client", "git": "git"},
    "dnf": {"ssh": "openssh-clients", "ssh-copy-id": "openssh-clients", "git": "git"},
    "zypper": {"ssh": "openssh-clients", "ssh-copy-id": "openssh-clients", "git": "git"},
    "brew": {"ssh": None, "ssh-copy-id": "ssh-copy-id", "gocryptfs": None, "git": "git"},
}
INSTALL_COMMANDS = {
    "pacman": "sudo pacman -S --needed", "apt": "sudo apt install", "dnf": "sudo dnf install",
    "zypper": "sudo zypper install", "brew": "brew install",
}


class Failed(Exception):
    """Something the user should read; the menu shows it and carries on."""


def install_hint(tools) -> str:
    """The command that installs these tools on this system."""
    manager = next((m for m in INSTALL_COMMANDS if shutil.which(m)), None)
    if manager is None:
        return "install with your package manager: " + ", ".join(tools)
    names = PACKAGE_NAMES[manager]
    packages = dict.fromkeys(names.get(t, t) for t in tools)
    if None in packages:
        if manager == "brew" and "gocryptfs" in tools:
            return "the vault isn't available on macOS (gocryptfs needs Linux)"
        packages.pop(None)
    return f"{INSTALL_COMMANDS[manager]} {' '.join(packages)}"


def missing(*tools: str) -> list[str]:
    return [t for t in tools if not shutil.which(t)]


def need(*tools: str) -> None:
    if lacking := missing(*tools):
        raise Failed(f"{', '.join(lacking)} not installed. Install with:\n  {install_hint(lacking)}")


def open_path(path: Path) -> None:
    """Show a folder or file in the desktop's file manager / default app."""
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


# ------------------------------------------------------------------------- settings
def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}


def save_config(cfg: dict) -> None:
    """Written to a private file first and then swapped in: never readable by others, never half-written."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    part = CONFIG_PATH.with_name(CONFIG_PATH.name + ".part")
    part.unlink(missing_ok=True)
    with os.fdopen(os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        f.write(json.dumps(cfg, indent=2))
    part.replace(CONFIG_PATH)


def require_server(cfg: dict) -> dict:
    if not cfg.get("server"):
        raise Failed("Phoenix isn't set up yet: run `phoenix` and follow the setup.")
    return cfg


# ------------------------------------------------------------------------------ SSH
def ssh_opts(*, shared: bool = True) -> list[str]:
    """One SSH connection is reused for 15 minutes, so a key passphrase is asked once, not per action."""
    CACHE.mkdir(parents=True, exist_ok=True)
    opts = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30"]
    if shared:
        opts += ["-o", "ControlMaster=auto", "-o", f"ControlPath={CACHE}/ssh-%C", "-o", "ControlPersist=15m"]
    return opts


def ssh(cfg: dict, command: str, *, tty: bool = False, capture: bool = False, input: str | None = None):
    sys.stdout.flush()
    remote = f"cd {shlex.quote(cfg.get('remote_dir', '/opt/phoenix'))} && {command}"
    if cfg.get("sudo"):  # logged in as a normal user with passwordless sudo (e.g. "ubuntu")
        remote = f"sudo -n sh -c {shlex.quote(remote)}"
    args = ["ssh", *ssh_opts(), *(["-t"] if tty else []), cfg["server"], remote]
    return subprocess.run(args, text=True, capture_output=capture, input=input)


def sh(*args: str) -> None:
    sys.stdout.flush()
    if subprocess.run(args).returncode:
        raise Failed(f"command failed: {' '.join(args)}")


def rsync(cfg: dict, *args: str) -> None:
    need("rsync")
    sudo = ["--rsync-path=sudo -n rsync"] if cfg.get("sudo") else []
    sh("rsync", "-e", shlex.join(["ssh", *ssh_opts()]), *sudo, *args)


def ssh_target(host: str, *, config: Path | None = None) -> str:
    """What to connect to: "user@host" as typed; a Host alias from ~/.ssh/config that sets its own User as is;
    otherwise root@host."""
    if "@" in host:
        return host
    import getpass

    r = subprocess.run(["ssh", *(["-F", str(config)] if config else []), "-G", host], capture_output=True, text=True)
    user = next((line.split(None, 1)[1] for line in r.stdout.splitlines() if line.startswith("user ")), "")
    return host if r.returncode == 0 and user and user != getpass.getuser() else f"root@{host}"


def key_login_works(cfg: dict) -> bool:
    """True if the server accepts our SSH key (password login is about to be switched off)."""
    args = ["ssh", *ssh_opts(shared=False), "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
            cfg["server"], "true"]
    return subprocess.run(args).returncode == 0


def check_admin(cfg: dict) -> None:
    """Root is used directly; any other user needs passwordless sudo (the default on most cloud images)."""
    r = subprocess.run(["ssh", *ssh_opts(), cfg["server"], "id -u && sudo -n true && echo sudo-ok"],
                       text=True, capture_output=True)
    lines = r.stdout.split()
    if lines[:1] == ["0"]:
        cfg["sudo"] = False
    elif "sudo-ok" in lines:
        cfg["sudo"] = True
    else:
        raise Failed(f"{cfg['server']} is not root and can't use sudo without a password. "
                     "Log in as root, or give this user passwordless sudo.")


def public_ssh_key() -> Path | None:
    for name in ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub"):
        path = Path.home() / ".ssh" / name
        if path.exists():
            return path
    return None


def ctl(cfg: dict, *args: str, input: str | None = None) -> str:
    """Run a server-side command (phoenix/ctl.py) inside the running service."""
    r = ssh(cfg, "docker compose exec -T phoenix python -m phoenix.ctl " + shlex.join(args), capture=True, input=input)
    if r.returncode:
        text = (r.stderr.strip() or r.stdout.strip()).splitlines()
        message = text[-1] if text else "the server did not answer"
        if "is not running" in message or "no such service" in message:
            message = "Phoenix is not running on the server (Server → Restart Phoenix)."
        elif r.returncode == 255:
            message = f"Cannot connect to the server {cfg['server']}."
        raise Failed(message)
    return r.stdout.strip()


# --------------------------------------------------------------------- server setup
def bootstrap(cfg: dict) -> None:
    script = (ROOT / "deploy" / "bootstrap.sh").read_text()
    sudo = "sudo -n " if cfg.get("sudo") else ""
    # Copy the script over first and run it from a file: run from stdin, any command that reads
    # stdin (an apt question, say) would swallow the rest of the script.
    remote = (f'f=$(mktemp) && cat > "$f" && {sudo}bash "$f" {shlex.quote(cfg["remote_dir"])} </dev/null; '
              'rc=$?; rm -f "$f"; exit $rc')
    sys.stdout.flush()
    if subprocess.run(["ssh", *ssh_opts(), cfg["server"], remote], input=script, text=True).returncode:
        raise Failed("preparing the server failed (see the output above)")


def deploy(cfg: dict) -> bool:
    """Upload and build the server code. Returns True if it's (re)started (needs keys in .env)."""
    dest = f"{cfg['server']}:{cfg['remote_dir']}/"
    rsync(cfg, "-a", "--delete", "--exclude", "__pycache__", str(ROOT / "server"), dest)
    rsync(cfg, "-a", str(ROOT / "docker-compose.yml"), dest)
    print("Building (the first time takes a few minutes)…")
    if ssh(cfg, "docker compose build -q").returncode:
        raise Failed("building Phoenix on the server failed (see the output above)")
    fetch_public_key(cfg)
    if ssh(cfg, "test -s .env").returncode:
        return False
    if ssh(cfg, "docker compose up -d").returncode:
        raise Failed("starting Phoenix failed (see the output above)")
    return True


def fetch_public_key(cfg: dict) -> str:
    r = ssh(cfg, "docker compose run --rm -T phoenix python -m phoenix.keygen", capture=True)
    keys = [line.strip() for line in r.stdout.splitlines() if line.strip().startswith("age1")]
    if r.returncode or not keys:
        raise Failed(f"cannot get the server's encryption key:\n{r.stderr}")
    if cfg.get("public_key") != keys[-1]:
        cfg["public_key"] = keys[-1]
        save_config(cfg)
    return keys[-1]


def read_env(cfg: dict) -> dict:
    """The server's .env ({} if it doesn't exist yet). Fails loudly if the server can't be read,
    so a later write can never replace your keys with an empty file."""
    r = ssh(cfg, "cat .env 2>/dev/null || true", capture=True)
    if r.returncode:
        raise Failed(f"cannot read the settings on {cfg['server']}")
    return dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)


def set_env_value(cfg: dict, key: str, value: str) -> None:
    """Change one setting in the server's .env, keeping all the others."""
    env = read_env(cfg)
    if not env.get("BOT_TOKEN"):
        raise Failed("the server has no settings yet: finish the setup first")
    env[key] = value
    write_env(cfg, env)


def write_env(cfg: dict, values: dict) -> None:
    content = "".join(f"{k}={v}\n" for k, v in values.items())
    if ssh(cfg, "umask 077 && cat > .env", input=content).returncode:
        raise Failed("cannot save the keys on the server")


def login(cfg: dict) -> None:
    r = ssh(cfg, "docker compose stop && docker compose run --rm phoenix python -m phoenix.login", tty=True)
    ssh(cfg, "docker compose up -d")
    if r.returncode:
        raise Failed("logging in to Telegram did not finish")


def restart(cfg: dict) -> None:
    if ssh(cfg, "docker compose up -d --force-recreate").returncode:
        raise Failed("restarting Phoenix failed (see the output above)")


def follow_logs(cfg: dict) -> None:
    ssh(cfg, "docker compose logs --tail 100 -f", tty=True)


def stop(cfg: dict) -> bool:
    """Stop Phoenix on a server (it stays stopped after a reboot). False if the server can't be reached."""
    return ssh(cfg, "docker compose stop", capture=True).returncode == 0


def safe_remote_dir(path: str) -> bool:
    """Only ever delete a folder that is clearly Phoenix's own, never something like / or /home."""
    parts = Path(path).parts
    return Path(path).is_absolute() and len(parts) >= 3 and "phoenix" in parts[-1].lower() and ".." not in parts


def uninstall(cfg: dict) -> str | None:
    """Log the server out of Telegram, then delete Phoenix and all its data from the server.
    Returns a warning if the logout didn't work (the session then stays valid at Telegram)."""
    if not safe_remote_dir(cfg["remote_dir"]):
        raise Failed(f"refusing to delete {cfg['remote_dir']!r}: it doesn't look like Phoenix's own folder")
    logout = ssh(cfg, "docker compose stop && docker compose run --rm -T phoenix python -m phoenix.logout")
    r = ssh(cfg, f"docker compose down --rmi all; cd / && rm -rf {shlex.quote(cfg['remote_dir'])}")
    if r.returncode:
        raise Failed("removing Phoenix from the server failed (see the output above)")
    if logout.returncode:
        return ("The server could not log out of your Telegram account, so that session still works. End it in "
                "Telegram → Settings → Devices (the session named after Phoenix's server).")
    return None


# --------------------------------------------------------------------- this copy
def update_code() -> bool:
    """Download the latest Phoenix into this copy (a git checkout). Returns True if anything changed."""
    if not (ROOT / ".git").exists():
        return False
    need("git")
    head = lambda: subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],  # noqa: E731
                                  capture_output=True, text=True).stdout.strip()
    before = head()
    sys.stdout.flush()
    if subprocess.run(["git", "-C", str(ROOT), "pull", "--ff-only"]).returncode:
        raise Failed(f"could not download the update into {ROOT} (did you change files there?)")
    return head() != before


# ---------------------------------------------------------------------------- vault
def migrate_vault() -> str | None:
    """Move a vault kept next to the code (older versions) to the data folder, so updating or
    deleting the code can never take your packages with it. Returns a message if it moved."""
    global VAULT
    legacy, target = ROOT / "vault", DATA / "vault"
    if (os.environ.get("PHOENIX_VAULT") or VAULT != legacy or not (legacy / "gocryptfs.conf").exists()
            or target.exists() or os.path.ismount(mountpoint())):
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy), str(target))
    VAULT = target
    return f"🔐 Your vault moved out of the code folder, to {target}. Nothing else changes."


def vault_enabled() -> bool:
    return (VAULT / "gocryptfs.conf").exists()


def mountpoint() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "phoenix-packages"


def unmount(mp: Path) -> bool:
    tool = shutil.which("fusermount3") or shutil.which("fusermount") or "fusermount3"
    if subprocess.run([tool, "-u", str(mp)], stderr=subprocess.DEVNULL).returncode:
        # Something still has a file open there: detach now, the kernel finishes once it's closed.
        if subprocess.run([tool, "-uz", str(mp)]).returncode:
            print(f"⚠️ Could not lock the vault: close every window using {mp}, then run: phoenix lock")
            return False
    with contextlib.suppress(OSError):
        mp.rmdir()
    return True


@contextlib.contextmanager
def _vault_user():
    """A shared lock held while this process uses the vault, so only the last Phoenix window locks it."""
    import fcntl

    CACHE.mkdir(parents=True, exist_ok=True)
    with open(CACHE / "vault.lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        yield lock


def _last_user(lock) -> bool:
    import fcntl

    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # succeeds only if no other window holds the vault
        return True
    except BlockingIOError:
        return False


@contextlib.contextmanager
def packages_root(cfg: dict, *, lock_existing: bool = False):
    """Yields the folder with plaintext packages; unlocks (and re-locks) the vault if it's enabled."""
    if not vault_enabled():
        path = Path(cfg.get("packages_dir") or DEFAULT_PACKAGES)
        path.mkdir(parents=True, exist_ok=True)
        yield path
        return
    need("gocryptfs")
    mp = mountpoint()
    with _vault_user() as lock:
        mounted_here = not os.path.ismount(mp)  # otherwise: another Phoenix window, or left over
        if mounted_here:
            mp.mkdir(mode=0o700, exist_ok=True)
            print("🔐 Vault password:")
            if subprocess.run(["gocryptfs", "-q", str(VAULT), str(mp)]).returncode:
                mp.rmdir()
                raise Failed("could not unlock the vault (wrong password?)")
        try:
            yield mp
        finally:
            if mounted_here or lock_existing:
                if _last_user(lock):
                    unmount(mp)
                else:
                    print("🔓 The vault stays open: another Phoenix window is still using it.")


def vault_init(cfg: dict) -> None:
    need("gocryptfs")
    if vault_enabled():
        raise Failed(f"the vault already exists: {VAULT}")
    plain = Path(cfg.get("packages_dir") or DEFAULT_PACKAGES)
    VAULT.mkdir(parents=True, exist_ok=True)
    print("Choose a vault password. You'll type it each time you open your packages.")
    print("Then gocryptfs prints a MASTER KEY: write it on paper. It's the only way back if you forget the password.\n")
    if subprocess.run(["gocryptfs", "-init", str(VAULT)]).returncode:
        shutil.rmtree(VAULT, ignore_errors=True)
        raise Failed("creating the vault failed")
    if plain.exists() and any(plain.iterdir()):
        with packages_root(cfg) as mp:
            print(f"Moving {plain} into the vault…")
            shutil.copytree(plain, mp, dirs_exist_ok=True)
        shutil.rmtree(plain)
        print("The unencrypted copy was deleted (on an SSD, traces may stay on disk until overwritten).")
    print(f"✅ Vault ready: {VAULT}\nYou can back up this folder anywhere (USB, cloud): it's useless without the password.")


def removable_drives() -> list[Path]:
    """Mounted USB sticks and external disks (the usual desktop mount places)."""
    import getpass

    user = getpass.getuser()
    roots = [Path("/run/media") / user, Path("/media") / user, Path("/Volumes")]
    return sorted(p for root in roots if root.is_dir() for p in root.iterdir() if p.is_dir() and os.access(p, os.W_OK))


RESTORE_NOTE = """This is an encrypted backup of a Phoenix vault (https://github.com/Skerpsh/Phoenix).

To use it on a new computer:
  1. Install Phoenix:  curl -fsSL https://raw.githubusercontent.com/Skerpsh/Phoenix/main/install.sh | bash
  2. Copy the "vault" folder from here to:  ~/.local/share/phoenix/vault
  3. Run phoenix. It asks for the vault password.

Forgot the password? With the master key you wrote down:
  gocryptfs -passwd -masterkey=<master key> ~/.local/share/phoenix/vault
"""


def backup_vault(target: Path) -> Path:
    """Copy the encrypted vault to `target`/phoenix-vault-<date>, with restore instructions; verify the copy."""
    if not vault_enabled():
        raise Failed("there's no vault to back up yet (🔐 Vault → Protect them with a password)")
    from datetime import datetime

    dest = target / f"phoenix-vault-{datetime.now():%Y-%m-%d-%H%M}"
    if dest.exists():
        raise Failed(f"{dest} already exists")
    sys.stdout.flush()
    print(f"Copying to {dest}…")
    shutil.copytree(VAULT, dest / "vault")
    (dest / "HOW-TO-RESTORE.txt").write_text(RESTORE_NOTE)
    original = sorted((p.relative_to(VAULT), p.stat().st_size) for p in VAULT.rglob("*") if p.is_file())
    copied = sorted((p.relative_to(dest / "vault"), p.stat().st_size) for p in (dest / "vault").rglob("*") if p.is_file())
    if original != copied:
        raise Failed(f"the copy in {dest} doesn't match the vault; try another place")
    return dest


def lock() -> bool:
    mp = mountpoint()
    return os.path.ismount(mp) and unmount(mp)
