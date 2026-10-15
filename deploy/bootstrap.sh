#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu/Debian server: updates, Docker, firewall, SSH hardening.
# Run from your computer by `phoenix` (setup step 2, or Server → Prepare the server again).
set -euo pipefail

REMOTE_DIR="${1:-/opt/phoenix}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Updating system"
apt-get update -y
apt-get upgrade -y
apt-get install -y ca-certificates curl rsync ufw unattended-upgrades fail2ban

echo "==> Automatic security updates"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

if ! command -v docker >/dev/null; then
    echo "==> Installing Docker"
    if ! curl -fsSL https://get.docker.com | sh; then
        echo "==> Docker's script doesn't support this release yet, using Ubuntu's packages"
        apt-get install -y docker.io docker-compose-v2
    fi
fi
systemctl enable --now docker
docker compose version

echo "==> Firewall: allow SSH (existing rules are kept; Phoenix itself needs no open ports)"
ufw allow OpenSSH
ufw --force enable

# The account you log in with (also when this runs through sudo as a normal user).
LOGIN_HOME="$(getent passwd "${SUDO_USER:-$(id -un)}" | cut -d: -f6)"
if [ -s "$LOGIN_HOME/.ssh/authorized_keys" ]; then
    echo "==> SSH: key login only"
    cat > /etc/ssh/sshd_config.d/00-phoenix.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
    sshd -t
    systemctl restart ssh 2>/dev/null || systemctl restart sshd
else
    echo "!! No SSH key in $LOGIN_HOME/.ssh/authorized_keys: password login left ENABLED. Add a key and re-run."
fi

mkdir -p "$REMOTE_DIR/data"
chmod 700 "$REMOTE_DIR"
echo "==> Server ready"
