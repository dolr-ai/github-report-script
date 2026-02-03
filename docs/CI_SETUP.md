# CI/CD Setup Guide

This document explains how the automated nightly GitHub activity reports are configured and how to set them up.

## Overview

The GitHub Actions workflow runs automatically every night at **12:00 AM IST (6:30 PM UTC)** to:
1. Fetch commits from all repositories in the dolr-ai organization
2. Process and aggregate the data
3. Generate visualization charts
4. Upload reports as artifacts (90-day retention)
5. Create weekly summary releases (every Sunday)

## Workflow Architecture

### Files

- `.github/workflows/nightly-report.yml` - Main workflow definition
- `.github/scripts/setup-ci.sh` - CI environment setup script
- `.devcontainer/devcontainer.json` - Dev container configuration

### Jobs

1. **generate-report**
   - Runs inside the dev container using `devcontainers/ci@v0.3`
   - Executes in FETCH_AND_CHART mode (fetches data + generates charts)
   - Uploads reports and cache as artifacts

2. **weekly-summary**
   - Only runs on Sundays
   - Downloads the latest artifacts
   - Creates a GitHub release with aggregated weekly reports

## Required Secrets

### ANSIBLE_VAULT_PASSWORD

The workflow requires access to the GitHub token stored in the encrypted `secrets.yml.vault` file.

**To set up:**

1. Go to your repository Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Name: `ANSIBLE_VAULT_PASSWORD`
4. Value: Your Ansible vault password (the one used to encrypt `secrets.yml.vault`)
5. Click "Add secret"

**Security Note:** This secret is never exposed in logs and is only used to decrypt the vault file at runtime.

## Manual Execution

The workflow can be triggered manually via the Actions tab:

1. Go to Actions → Nightly GitHub Activity Report
2. Click "Run workflow"
3. Select the branch (usually `main`)
4. Click "Run workflow"

This is useful for:
- Testing the workflow
- Generating reports on-demand
- Recovering from failed scheduled runs

## Workflow Triggers

### Automatic (Scheduled)

```yaml
schedule:
  - cron: '30 18 * * *'  # 12:00 AM IST daily
```

### Manual (Workflow Dispatch)

Available via the GitHub Actions UI

## Output Artifacts

### Daily Artifacts

- **Name:** `github-activity-report-{run_number}`
- **Retention:** 90 days
- **Contents:**
  - `reports/` - Generated reports with charts
  - `cache/` - Commit data cache

### Weekly Releases

- **Tag:** `weekly-{run_number}`
- **Schedule:** Every Sunday at 12:00 AM IST
- **Contents:** Aggregated reports from the past week

## Dev Container Integration

The workflow uses the same dev container as local development, ensuring:
- Consistent Python version (3.14)
- Same dependencies (from `requirements.txt`)
- Ansible for vault decryption
- Git configuration

### Post-Create Command

The dev container automatically installs dependencies:

```json
"postCreateCommand": "pip3 install --user -r requirements.txt"
```

## Execution Mode

The workflow sets `EXECUTION_MODE=fetch_and_chart`, which:
1. Fetches commits from GitHub API (all branches)
2. Processes and caches the data
3. Generates charts automatically

This is different from the default interactive mode used locally.

## Troubleshooting

### Workflow fails with "ANSIBLE_VAULT_PASSWORD not set"

**Cause:** The secret is not configured in repository settings.

**Solution:** Add the `ANSIBLE_VAULT_PASSWORD` secret as described above.

### Workflow fails with "secrets.yml.vault not found"

**Cause:** The encrypted secrets file is not in the repository.

**Solution:** Ensure `secrets.yml.vault` is committed to the repository.

### Workflow fails with "vault decryption failed"

**Cause:** The vault password is incorrect.

**Solution:** 
1. Verify the password locally: `ansible-vault view secrets.yml.vault`
2. Update the secret in repository settings with the correct password

### No artifacts uploaded

**Cause:** The report generation failed or produced no output.

**Solution:**
1. Check the workflow logs for errors
2. Run manually via workflow_dispatch to debug
3. Verify the `reports/` directory is created

### Weekly release not created

**Cause:** The workflow didn't run on Sunday or the condition failed.

**Solution:**
1. Check if the workflow ran on Sunday (cron runs at 6:30 PM UTC Sunday)
2. Verify the `weekly-summary` job condition in the workflow file

## Monitoring

### Viewing Reports

1. Go to Actions → Select a workflow run
2. Scroll to "Artifacts" section
3. Download the artifact ZIP file
4. Extract to view reports and charts

### Checking Logs

1. Go to Actions → Select a workflow run
2. Click on a job (e.g., "generate-report")
3. Expand steps to view detailed logs

### GitHub Notifications

You'll receive notifications for:
- Workflow failures
- Weekly release creation

Configure notification preferences in Settings → Notifications

## Local Testing

To test the workflow configuration locally:

```bash
# Install dependencies
pip install -r requirements.txt

# Set execution mode
export EXECUTION_MODE=fetch_and_chart

# Run the script
python src/main.py
```

## Performance

- **Execution time:** ~2-5 minutes (depends on number of repositories)
- **API rate limits:** ~5000 requests/hour for authenticated requests
- **Concurrent fetching:** Uses threading for parallel repository processing

## Cost

GitHub Actions minutes:
- **Public repositories:** Free (unlimited)
- **Private repositories:** Free tier includes 2,000 minutes/month

Artifact storage:
- **Free tier:** 500 MB
- **Retention:** 90 days (configurable)

## Future Enhancements

Potential improvements:
- Email notifications for weekly summaries
- Slack/Discord integration
- Configurable report formats (PDF, HTML)
- Dashboard hosting via GitHub Pages
- Historical trend analysis
