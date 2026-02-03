#!/bin/bash
# Quick start script for GitHub Report Script

set -e

echo "========================================"
echo "GitHub Report Script - Quick Start"
echo "========================================"
echo

# Check if .env exists
if [ ! -f .env ]; then
    echo "Step 1: Creating .env file..."
    cp .env.example .env
    echo "✓ Created .env file"
    echo
    echo "⚠️  IMPORTANT: Edit .env file and add your GitHub token"
    echo "   Get token from: https://github.com/settings/tokens"
    echo "   Required scopes: repo, read:org"
    echo
    read -p "Press Enter after you've added your GitHub token to .env..."
else
    echo "✓ .env file already exists"
fi

echo
echo "Step 2: Checking configuration..."

# Check if USER_IDS is configured
if grep -q "# Example:" src/config.py && ! grep -q "'[a-zA-Z].*'," src/config.py; then
    echo
    echo "⚠️  USER_IDS is not configured"
    echo "   Edit src/config.py and add GitHub usernames to track"
    echo
    read -p "Press Enter after you've added usernames to src/config.py..."
fi

echo
echo "Step 3: Testing configuration..."
python report.py status

echo
echo "========================================"
echo "Setup complete!"
echo "========================================"
echo
echo "Next steps:"
echo "  1. Fetch data:        python report.py fetch"
echo "  2. Generate charts:   python report.py chart"
echo "  3. View help:         python report.py --help"
echo
