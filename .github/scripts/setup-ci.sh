#!/bin/bash
set -e

echo "Setting up CI environment..."

# Check if ANSIBLE_VAULT_PASSWORD is set
if [ -z "$ANSIBLE_VAULT_PASSWORD" ]; then
    echo "Error: ANSIBLE_VAULT_PASSWORD environment variable is not set"
    exit 1
fi

# Decrypt the GitHub token from vault and generate .env file
echo "Decrypting GitHub token..."
if [ -f "ansible/vars/vault.yml" ]; then
    # Create temporary password file
    echo "$ANSIBLE_VAULT_PASSWORD" > /tmp/vault_pass.txt
    
    # Run the Ansible playbook to generate .env file
    cd ansible
    ansible-playbook setup_env.yml --vault-password-file=/tmp/vault_pass.txt
    cd ..
    
    # Clean up password file
    rm -f /tmp/vault_pass.txt
    
    echo "GitHub token decrypted and .env file generated successfully"
else
    echo "Warning: ansible/vars/vault.yml not found, skipping decryption"
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
