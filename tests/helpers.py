import subprocess
from pathlib import Path

from phx import core
from phx import packages as pk


def push_locally(packages: Path, public_key: str, server_data: Path) -> None:
    """Run the real upload, with rsync copying into a local folder instead of the server."""
    def local_rsync(cfg, *args):
        subprocess.run(["rsync", *[a.replace("local:", "") for a in args]], check=True, stdout=subprocess.DEVNULL)

    original_rsync, original_ssh = pk.rsync, pk.ssh
    pk.rsync = local_rsync
    pk.ssh = lambda cfg, command, **kw: subprocess.run(["sh", "-c", f"cd {server_data.parent} && {command}"])
    try:
        cfg = {"server": "local", "remote_dir": str(server_data.parent), "public_key": public_key}
        pk.push_from(cfg, packages)
    finally:
        pk.rsync, pk.ssh = original_rsync, original_ssh


def write_meta(d: Path, **meta) -> None:
    d.mkdir(parents=True, exist_ok=True)
    full = {"name": d.name, "telegram": "", "on": ["silence", "panic"], "delay": 0,
            "backup": "", "backup_after": 7 * 86400, "backup_note": ""}
    pk.save_meta(d, {**full, **meta})


__all__ = ["core", "push_locally", "write_meta"]
