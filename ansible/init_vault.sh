#!/bin/bash
# Ansible Vault Initialization Script
# This script guides you through setting up Ansible vault for the first time

set -e

echo "========================================"
echo "Ansible Vault Initialization"
echo "========================================"
echo

# Check if we're in the ansible directory
if [ ! -f "ansible.cfg" ]; then
    echo "❌ Error: Must run from ansible/ directory"
    echo "   cd ansible && ./init_vault.sh"
    exit 1
fi

# Check if vault is already initialized
if [ -f ".vault_pass" ] && [ -f "vars/vault.yml" ]; then
    echo "⚠️  Vault appears to be already initialized"
    echo "   Files exist: .vault_pass, vars/vault.yml"
    echo
    read -p "Do you want to reinitialize? This will backup existing files. (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    
    # Backup existing files
    timestamp=$(date +%Y%m%d_%H%M%S)
    [ -f ".vault_pass" ] && mv .vault_pass ".vault_pass.backup_${timestamp}"
    [ -f "vars/vault.yml" ] && mv vars/vault.yml "vars/vault.yml.backup_${timestamp}"
    echo "✓ Existing files backed up"
    echo
fi

# Step 1: Create vault password
echo "Step 1: Create Vault Password"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Enter a strong password for encrypting secrets."
echo "This password will be stored in .vault_pass (gitignored)."
echo
read -s -p "Vault password: " vault_pass
echo
read -s -p "Confirm password: " vault_pass_confirm
echo

if [ "$vault_pass" != "$vault_pass_confirm" ]; then
    echo "❌ Passwords don't match. Aborting."
    exit 1
fi

if [ ${#vault_pass} -lt 8 ]; then
    echo "❌ Password too short. Use at least 8 characters."
    exit 1
fi

# Save password
echo "$vault_pass" > .vault_pass
chmod 600 .vault_pass
echo "✓ Vault password saved to .vault_pass"
echo

# Step 2: Get GitHub token
echo "Step 2: GitHub Personal Access Token"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Enter your GitHub Personal Access Token."
echo "Create one at: https://github.com/settings/tokens"
echo "Required scopes: repo, read:org"
echo
read -s -p "GitHub token: " github_token
echo

if [ -z "$github_token" ]; then
    echo "❌ GitHub token cannot be empty"
    exit 1
fi

# Step 3: Confirm GitHub org
echo
echo "Step 3: GitHub Organization"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
default_org="dolr-ai"
read -p "GitHub organization (default: $default_org): " github_org
github_org=${github_org:-$default_org}
echo "✓ Organization set to: $github_org"
echo

# Step 4: Create vars/main.yml
echo "Step 4: Creating Configuration Files"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cat > vars/main.yml << EOF
---
# Visible variable names that reference vault secrets
# This file is committed to version control

# GitHub Configuration
github_token: "{{ vault_github_token }}"
github_org: "$github_org"
EOF

echo "✓ Created vars/main.yml"

# Step 5: Create and encrypt vars/vault.yml
cat > vars/vault.yml << EOF
---
# Encrypted secrets - actual values
# This file is encrypted with ansible-vault

vault_github_token: "$github_token"
EOF

echo "✓ Created vars/vault.yml"

# Encrypt the vault file
ansible-vault encrypt vars/vault.yml --vault-password-file=.vault_pass
echo "✓ Encrypted vars/vault.yml"
echo

# Step 6: Test by generating .env
echo "Step 5: Testing Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Running playbook to generate .env file..."
echo

if ansible-playbook setup_env.yml -v; then
    echo
    echo "========================================"
    echo "✓ Vault Initialization Complete!"
    echo "========================================"
    echo
    echo "Created files:"
    echo "  ✓ .vault_pass (gitignored)"
    echo "  ✓ vars/main.yml (committed)"
    echo "  ✓ vars/vault.yml (encrypted, committed)"
    echo "  ✓ ../.env (generated)"
    echo
    echo "Next steps:"
    echo "  1. Verify .env file: cat ../.env"
    echo "  2. Edit configuration: vim ../src/config.py"
    echo "  3. Run script: cd .. && python src/main.py"
    echo
    echo "Vault management commands:"
    echo "  View secrets:  ansible-vault view vars/vault.yml"
    echo "  Edit secrets:  ansible-vault edit vars/vault.yml"
    echo "  Regenerate .env: ansible-playbook setup_env.yml"
    echo
    echo "See ansible/README.md for more information."
    echo "========================================"
else
    echo
    echo "❌ Playbook execution failed."
    echo "   Check the error messages above."
    echo "   You may need to install Ansible: pip install ansible"
    exit 1
fi
