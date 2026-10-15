#!/usr/bin/env bash
# Installs Phoenix on your computer (Linux or macOS): the tools it needs, the code, and the `phoenix` command.
#
#   curl -fsSL https://raw.githubusercontent.com/Skerpsh/Phoenix/main/install.sh | bash
#
# Or, from a copy you already downloaded:  ./install.sh
# Running it again updates Phoenix. Nothing here touches your server; `phoenix` does that later, with you.
set -euo pipefail

REPO="${PHOENIX_REPO:-https://github.com/Skerpsh/Phoenix.git}"
APP_DIR="${PHOENIX_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/phoenix/app}"
BIN_DIR="$HOME/.local/bin"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!!  %s\033[0m\n' "$*"; }
die() { printf '\033[31mxx  %s\033[0m\n' "$*" >&2; exit 1; }

# Questions must work even when this script is piped into bash.
ask_yes() {
    local answer
    if { : </dev/tty; } 2>/dev/null; then read -r -p "$1 [Y/n] " answer </dev/tty || answer=n; else answer=n; fi
    case "$answer" in [nN]*) return 1 ;; *) return 0 ;; esac
}

# ---------------------------------------------------------------- tools
if command -v pacman >/dev/null; then
    PM="sudo pacman -S --needed"; PKGS=(python git openssh rsync age gocryptfs)
elif command -v apt-get >/dev/null; then
    PM="sudo apt-get install -y"; PKGS=(python3 git openssh-client rsync age gocryptfs)
elif command -v dnf >/dev/null; then
    PM="sudo dnf install -y"; PKGS=(python3 git openssh-clients rsync age gocryptfs)
elif command -v zypper >/dev/null; then
    PM="sudo zypper install -y"; PKGS=(python3 git openssh-clients rsync age gocryptfs)
elif command -v brew >/dev/null; then
    PM="brew install"; PKGS=(python git rsync age ssh-copy-id)  # no gocryptfs on macOS: the vault is Linux-only
else
    PM=""; PKGS=()
fi

need_tools=(python3 git ssh ssh-copy-id rsync age)
[ "$(uname)" = Darwin ] || need_tools+=(gocryptfs)
missing=()
for tool in "${need_tools[@]}"; do command -v "$tool" >/dev/null || missing+=("$tool"); done

if [ ${#missing[@]} -gt 0 ]; then
    say "Missing tools: ${missing[*]}"
    if [ -z "$PM" ]; then
        die "Install them with your package manager (python3 ≥ 3.11, git, openssh, rsync, age, gocryptfs), then run this again."
    fi
    echo "    $PM ${PKGS[*]}"
    if ask_yes "Install them now?"; then
        [[ "$PM" == sudo\ apt-get* ]] && sudo apt-get update
        # shellcheck disable=SC2086  # $PM is a command with its arguments
        $PM "${PKGS[@]}"
    else
        die "Install them, then run this again."
    fi
fi

python_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; }
if ! python_ok python3 && ! { command -v python3.11 >/dev/null && python_ok python3.11; }; then
    die "Phoenix needs Python 3.11 or newer (Ubuntu 22.04: sudo apt install python3.11)."
fi

# ----------------------------------------------------------------- code
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/cli/phoenix" ]; then
    APP_DIR="$SELF_DIR"  # run from a downloaded copy: use it as is
    say "Using Phoenix in $APP_DIR"
elif [ -d "$APP_DIR/.git" ]; then
    say "Updating Phoenix in $APP_DIR"
    git -C "$APP_DIR" pull --ff-only
else
    say "Downloading Phoenix into $APP_DIR"
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --depth 1 "$REPO" "$APP_DIR"
fi
chmod +x "$APP_DIR/cli/phoenix"

# -------------------------------------------------------------- command
mkdir -p "$BIN_DIR"
ln -sfn "$APP_DIR/cli/phoenix" "$BIN_DIR/phoenix"
say "Installed the command: $BIN_DIR/phoenix"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        case "${SHELL##*/}" in
            zsh) rc="$HOME/.zshrc" ;;
            fish) rc="" ;;
            *) rc="$HOME/.bashrc" ;;
        esac
        if [ -n "$rc" ] && ask_yes "Add $BIN_DIR to your PATH in $rc?"; then
            # shellcheck disable=SC2016  # written literally, expanded when the shell starts
            printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >>"$rc"
            warn "Open a new terminal window for this to take effect."
        else
            warn "$BIN_DIR is not in your PATH: run Phoenix as $BIN_DIR/phoenix, or add it to PATH."
        fi
        ;;
esac

say "Done. Start with:  phoenix"
