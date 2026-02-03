# Ansible Vault Setup Guide

This directory contains Ansible configuration for securely managing secrets using Ansible Vault.

## Quick Start

1. **Initialize vault** (first time setup):
   ```bash
   cd ansible
   ./init_vault.sh
   ```

2. **Generate .env file**:
   ```bash
   cd ansible
   ansible-playbook setup_env.yml
   ```

3. **Run the script**:
   ```bash
   cd ..
   python src/main.py
   ```

## Directory Structure

```
ansible/
├── ansible.cfg              # Ansible configuration
├── .vault_pass             # Password file (gitignored)
├── inventory/
│   └── hosts               # Local inventory
├── vars/
│   ├── main.yml            # Visible variable names (committed)
│   ├── main.yml.example    # Template for main.yml
│   ├── vault.yml           # Encrypted secrets (committed)
│   └── vault.yml.example   # Template for vault.yml
├── templates/
│   └── env.j2              # Template for .env file
├── setup_env.yml           # Playbook to generate .env
└── init_vault.sh           # Helper script for initial setup
```

## Variable Naming Convention

- **Visible variables** (`vars/main.yml`): Reference vault variables
  ```yaml
  github_token: "{{ vault_github_token }}"
  ```

- **Vault variables** (`vars/vault.yml`): Actual secret values with `vault_` prefix
  ```yaml
  vault_github_token: "ghp_1234567890abcdef..."
  ```

## Common Commands

### Viewing Vault Content
```bash
# View encrypted vault file
ansible-vault view vars/vault.yml

# Decrypt to stdout
ansible-vault decrypt vars/vault.yml --output=-
```

### Editing Vault
```bash
# Edit encrypted file (decrypts, opens editor, re-encrypts)
ansible-vault edit vars/vault.yml
```

### Creating New Vault
```bash
# Create new encrypted file
ansible-vault create vars/vault.yml

# Or encrypt existing file
ansible-vault encrypt vars/vault.yml
```

### Changing Vault Password
```bash
# Rekey vault with new password
ansible-vault rekey vars/vault.yml
```

### Running Playbook
```bash
# With password file (configured in ansible.cfg)
ansible-playbook setup_env.yml

# With explicit password file
ansible-playbook setup_env.yml --vault-password-file=.vault_pass

# With interactive password prompt
ansible-playbook setup_env.yml --ask-vault-pass
```

## Security Best Practices

1. **Never commit** `.vault_pass` file
2. **Always commit** encrypted `vault.yml` file
3. **Use restrictive permissions**: `chmod 600 .vault_pass`
4. **Rotate passwords** periodically
5. **Share vault password** securely (1Password, LastPass, etc.)

## Adding New Secrets

1. **Edit main.yml** to add variable reference:
   ```yaml
   new_api_key: "{{ vault_new_api_key }}"
   ```

2. **Edit vault.yml** to add actual value:
   ```bash
   ansible-vault edit vars/vault.yml
   ```
   
   Add:
   ```yaml
   vault_new_api_key: "your_secret_value"
   ```

3. **Update template** (`templates/env.j2`):
   ```
   NEW_API_KEY={{ new_api_key }}
   ```

4. **Regenerate .env**:
   ```bash
   ansible-playbook setup_env.yml
   ```

## Troubleshooting

### "Vault password file not found"
Create `.vault_pass` file:
```bash
echo "your-strong-password" > .vault_pass
chmod 600 .vault_pass
```

### "Decryption failed"
Wrong password in `.vault_pass`. Verify with:
```bash
ansible-vault view vars/vault.yml
```

### ".env file not created"
Check playbook output for errors:
```bash
ansible-playbook setup_env.yml -v
```

## Example: Complete Workflow

```bash
# 1. Initial setup
cd ansible
./init_vault.sh
# Follow prompts to set vault password

# 2. Edit vault with your actual secrets
ansible-vault edit vars/vault.yml
# Add: vault_github_token: "ghp_YOUR_ACTUAL_TOKEN"

# 3. Generate .env file
ansible-playbook setup_env.yml
# Output: ✓ .env file generated successfully!

# 4. Run the script
cd ..
python src/main.py
```

## CI/CD Integration

For automated deployments, use environment variables:

```bash
# Set vault password in CI/CD environment variable
export ANSIBLE_VAULT_PASSWORD="your-vault-password"

# Create password file from environment
echo "$ANSIBLE_VAULT_PASSWORD" > ansible/.vault_pass

# Run playbook
cd ansible && ansible-playbook setup_env.yml
```

## Multiple Environments

For dev/staging/prod environments:

1. Create environment-specific vault files:
   ```
   vars/vault_dev.yml
   vars/vault_staging.yml
   vars/vault_prod.yml
   ```

2. Use vault IDs in `ansible.cfg`:
   ```ini
   [defaults]
   vault_identity_list = dev@.vault_pass_dev, prod@.vault_pass_prod
   ```

3. Run with specific vault:
   ```bash
   ansible-playbook setup_env.yml --vault-id dev@.vault_pass_dev
   ```
