#!/bin/bash
# Krypton Droplet Setup Script
# Run as root on a fresh Ubuntu 24.04 Droplet
#
# Usage: ssh root@<droplet-ip> 'bash -s' < setup-droplet.sh

set -euo pipefail

DEPLOY_USER="deploy"
REPO_URL="https://github.com/<YOUR_GITHUB_USERNAME>/krypton.git"
APP_DIR="/opt/krypton"

echo "============================================"
echo "  Krypton Droplet Setup"
echo "============================================"

# -----------------------------------------------
# 1. System updates
# -----------------------------------------------
echo "--- Updating system packages ---"
apt-get update && apt-get upgrade -y

# -----------------------------------------------
# 2. Create deploy user
# -----------------------------------------------
echo "--- Creating deploy user ---"
if id "$DEPLOY_USER" &>/dev/null; then
  echo "User $DEPLOY_USER already exists, skipping"
else
  adduser --disabled-password --gecos "" "$DEPLOY_USER"
  usermod -aG sudo "$DEPLOY_USER"
  echo "$DEPLOY_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$DEPLOY_USER
fi

# Copy root SSH keys to deploy user
mkdir -p /home/$DEPLOY_USER/.ssh
cp /root/.ssh/authorized_keys /home/$DEPLOY_USER/.ssh/authorized_keys
chown -R $DEPLOY_USER:$DEPLOY_USER /home/$DEPLOY_USER/.ssh
chmod 700 /home/$DEPLOY_USER/.ssh
chmod 600 /home/$DEPLOY_USER/.ssh/authorized_keys

# -----------------------------------------------
# 3. Harden SSH
# -----------------------------------------------
echo "--- Hardening SSH ---"
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

# -----------------------------------------------
# 4. Firewall (UFW)
# -----------------------------------------------
echo "--- Configuring firewall ---"
apt-get install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp   # SSH
ufw allow 80/tcp   # HTTP (redirect to HTTPS)
ufw allow 443/tcp  # HTTPS
ufw --force enable

# -----------------------------------------------
# 5. Install Docker
# -----------------------------------------------
echo "--- Installing Docker ---"
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add deploy user to docker group
usermod -aG docker $DEPLOY_USER

# -----------------------------------------------
# 6. Install Git
# -----------------------------------------------
echo "--- Installing Git ---"
apt-get install -y git

# -----------------------------------------------
# 7. Clone repository
# -----------------------------------------------
echo "--- Cloning repository ---"
if [ -d "$APP_DIR" ]; then
  echo "$APP_DIR already exists, skipping clone"
else
  git clone "$REPO_URL" "$APP_DIR"
  chown -R $DEPLOY_USER:$DEPLOY_USER "$APP_DIR"
fi

# -----------------------------------------------
# 8. Set up swap (helps on 2GB Droplet)
# -----------------------------------------------
echo "--- Setting up 2GB swap ---"
if [ -f /swapfile ]; then
  echo "Swap already exists, skipping"
else
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl vm.swappiness=10
  echo 'vm.swappiness=10' >> /etc/sysctl.conf
fi

# -----------------------------------------------
# 9. Reminder: manual steps
# -----------------------------------------------
echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "Remaining manual steps:"
echo ""
echo "1. Update REPO_URL in this script (or re-clone):"
echo "   Current: $REPO_URL"
echo ""
echo "2. Create .env file:"
echo "   nano $APP_DIR/backend/.env"
echo ""
echo "   Required variables:"
echo "   KRYPTON_API_KEY=<your-api-key>"
echo "   OPENROUTER_API_KEY=<your-openrouter-key>"
echo "   POSTGRES_PASSWORD=<strong-password>"
echo "   OKX_API_KEY=<your-okx-key>"
echo "   OKX_API_SECRET=<your-okx-secret>"
echo "   OKX_PASSPHRASE=<your-okx-passphrase>"
echo "   VAPID_PRIVATE_KEY=<your-vapid-private-key>"
echo "   VAPID_PUBLIC_KEY=<your-vapid-public-key>"
echo "   VAPID_CLAIMS_EMAIL=<your-email>"
echo "   CRYPTOPANIC_API_KEY=<your-key>"
echo "   CRYPTOQUANT_API_KEY=<your-key>"
echo ""
echo "3. Run SSL setup (replace with your domain and email):"
echo "   cd $APP_DIR/backend"
echo "   chmod +x nginx/init-letsencrypt.sh"
echo "   ./nginx/init-letsencrypt.sh <your-domain> <your-email>"
echo ""
echo "4. Start services:"
echo "   cd $APP_DIR/backend"
echo "   docker compose -f docker-compose.prod.yml up -d"
echo ""
echo "5. Generate SSH key for GitHub Actions:"
echo "   su - $DEPLOY_USER"
echo "   ssh-keygen -t ed25519 -C 'github-actions' -f ~/.ssh/github_actions -N ''"
echo "   cat ~/.ssh/github_actions.pub >> ~/.ssh/authorized_keys"
echo "   cat ~/.ssh/github_actions  # copy this as SSH_PRIVATE_KEY secret"
echo ""
echo "6. Add GitHub repo secrets:"
echo "   DROPLET_IP = $(curl -s ifconfig.me)"
echo "   SSH_PRIVATE_KEY = (from step 5)"
echo ""
