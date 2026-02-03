#!/bin/bash
set -e

echo "Setting up CI environment..."

# Check if ANSIBLE_VAULT_PASSWORD is set
if [ -z "$ANSIBLE_VAULT_PASSWORD" ]; then
    echo "Error: ANSIBLE_VAULT_PASSWORD environment variable is not set"
    exit 1
fi

# Decrypt the GitHub token from vault
echo "Decrypting GitHub token..."
if [ -f "secrets.yml.vault" ]; then
    # Create temporary password file
    echo "$ANSIBLE_VAULT_PASSWORD" > /tmp/vault_pass.txt
    
    # Decrypt the vault file
    ansible-vault decrypt secrets.yml.vault --vault-password-file=/tmp/vault_pass.txt --output=secrets.yml
    
    # Clean up password file
    rm -f /tmp/vault_pass.txt
    
    echo "GitHub token decrypted successfully"
else
    echo "Warning: secrets.yml.vault not found, skipping decryption"
fi

# Configure git for the CI environment
echo "Configuring git..."
git config --global user.email "github-actions[bot]@users.noreply.github.com"
git config --global user.name "GitHub Actions Bot"

# Install Python dependencies if not already installed
if [ -f "requirements.txt" ]; then
    echo "Installing Python dependencies..."
    pip install -q -r requirements.txt
fi

echo "CI environment setup complete"
