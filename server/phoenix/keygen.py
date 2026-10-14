"""Create the server's age key (once) and print its public key for the CLI."""

import subprocess

from . import config


def main() -> None:
    path = config.load().identity_path
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        subprocess.run(["age-keygen", "-o", str(path)], check=True, capture_output=True)
        path.chmod(0o600)
    public = subprocess.run(["age-keygen", "-y", str(path)], check=True, capture_output=True, text=True)
    print(public.stdout.strip())


if __name__ == "__main__":
    main()
