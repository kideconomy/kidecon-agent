#!/usr/bin/env bash
set -euo pipefail

# KidEconomy Agent Bootstrap Script
# Installs Hermes, places config, registers agent with hub

HERMES_VERSION="v1.2.0"
HERMES_REPO="https://github.com/Nous-Research/hermes"  # placeholder — real repo TBD
CONFIG_DIR="${HOME}/.config/kidecon"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== KidEconomy Agent Installer ==="

# 1. Check Python
if ! command -v python3.14 &>/dev/null; then
    echo "Error: Python 3.14 not found. Install it first."
    exit 1
fi

# 2. Create venv
VENV_DIR="${SCRIPT_DIR}/env"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3.14 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# 3. Install the kidecon CLI (creates 'kidecon' command in the venv)
echo "Installing kidecon-agent CLI..."
pip install --upgrade pip
pip install "${SCRIPT_DIR}"
chmod +x "${SCRIPT_DIR}/cli/kidecon.py"

# 4. Place config
mkdir -p "$CONFIG_DIR"
cp "${SCRIPT_DIR}/kidecon.yaml" "${CONFIG_DIR}/kidecon.yaml"
echo "Config placed at ${CONFIG_DIR}/kidecon.yaml"

# 5. Prompt for OpenRouter API key
echo ""
echo "OpenRouter API key (leave blank to skip, add later with 'kidecon key add'):"
read -s -p "  Key: " OPENROUTER_KEY
echo ""
if [ -n "$OPENROUTER_KEY" ]; then
    python -c "import keyring; keyring.set_password('kidecon-agent', 'api_key_openrouter', '${OPENROUTER_KEY}')"
    echo "OpenRouter key stored in keyring."
fi

# 6. Install Hermes (stub — actual install method TBD)
echo ""
echo "Installing Hermes ${HERMES_VERSION}..."
# pip install "git+${HERMES_REPO}@${HERMES_VERSION}"
echo "  (stub — Hermes installation method TBD)"

# 7. Register agent with hub
echo ""
read -p "Enter a name for your agent: " AGENT_NAME
echo "Registering with hub..."
kidecon setup --name "$AGENT_NAME"

echo ""
echo "=== Setup complete ==="
echo "Run 'kidecon start' to launch your agent."
echo "Connect via Discord: (link TBD)"
