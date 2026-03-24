#!/bin/bash
# VPS setup script for podflow
# Usage: curl -fsSL https://raw.githubusercontent.com/botrosmark/podflow/main/scripts/vps-setup.sh | bash

set -e

echo "=== Installing GitHub CLI ==="
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli-stable.list > /dev/null
sudo apt update -qq && sudo apt install -y -qq gh

echo ""
echo "=== Installing uv ==="
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo ""
echo "=== Authenticate with GitHub ==="
gh auth login

echo ""
echo "=== Cloning podflow ==="
cd ~
gh repo clone botrosmark/podflow
cd podflow

echo ""
echo "=== Installing dependencies ==="
uv sync

echo ""
echo "=== Done! ==="
echo ""
echo "Next steps:"
echo "  1. cd ~/podflow"
echo "  2. cp .env.example .env && nano .env    # add your AssemblyAI key"
echo "  3. mkdir -p credentials && nano credentials/client_secret.json  # paste your Google OAuth JSON"
echo "  4. uv run podflow setup-drive"
echo "  5. Set up cron:"
echo "     crontab -e"
echo "     */30 * * * * cd ~/podflow && /root/.local/bin/uv run podflow run >> /var/log/podflow.log 2>&1"
