#!/bin/bash
#
# Hiddify Manager Bootstrap Installer
# Usage: bash <(curl -Ls https://raw.githubusercontent.com/Ghost-falcon00/Hiddify-Manager/Beta/bootstrap.sh) [branch]
#
# This script clones the repository and runs the actual install script.
#

set -e

# Default branch
BRANCH="${1:-Beta}"
REPO_URL="https://github.com/Ghost-falcon00/Hiddify-Manager.git"
INSTALL_DIR="/opt/hiddify-manager"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           Hiddify Manager Installer (Custom Fork)            ║"
echo "║                    Branch: $BRANCH                           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    exit 1
fi

# Check for git
if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}Installing git...${NC}"
    apt-get update -qq
    apt-get install -y git
fi

# Remove old installation if exists
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Removing existing installation...${NC}"
    rm -rf "$INSTALL_DIR"
fi

# Clone repository
echo -e "${GREEN}Cloning repository (branch: $BRANCH)...${NC}"
git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"

# Navigate to install directory
cd "$INSTALL_DIR"

# Make scripts executable
echo -e "${GREEN}Setting permissions...${NC}"
chmod +x install.sh
find . -name "*.sh" -exec chmod +x {} \;

# Run install script
echo -e "${GREEN}Starting installation...${NC}"
bash install.sh

echo -e "${GREEN}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    Installation Complete!                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
