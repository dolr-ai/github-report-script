# Leaderboard Setup Instructions

This guide will help you set up the GitHub commits leaderboard with Google Chat integration.

## What Was Implemented

1. **Daily & Weekly Leaderboards**: Automatically posts commit leaderboards to Google Chat
   - **Daily**: Monday-Saturday at 12:00 AM IST (posts yesterday's stats)
   - **Weekly**: Sundays at 12:00 AM IST (posts last 7 days' stats)

2. **Two Ranking Metrics**: Each leaderboard shows:
   - 🏆 Top 3 contributors by commit count
   - 📈 Top 3 contributors by lines changed (additions + deletions)
   - Ties share the same rank emoji (🥇🥈🥉)

3. **Google Chat Integration**: Posts formatted messages to your Google Chat space
   - Simple text format with emojis
   - Link to full reports: https://dolr-ai.github.io/github-report-script/
   - "No activity" message if no commits found

## Setup Steps

### Step 1: Update Ansible Vault

You need to add the Google Chat webhook credentials to your encrypted Ansible vault.

```bash
cd ansible

# Edit the encrypted vault file
ansible-vault edit vars/vault.yml
```

When prompted for the vault password, enter your existing Ansible vault password.

Add these two lines to the vault file (the GitHub token should already be there):

```yaml
vault_github_token: "your_existing_github_token"
vault_google_chat_key: "AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI"
vault_google_chat_token: "aYAXEGJf90ZokFzgmpy6-aXipaS2C-uN1rEhdIWRly4"
```

Save and exit the editor (for vim: press `Esc`, then type `:wq` and press `Enter`).

### Step 2: Generate .env File

Run the Ansible playbook to generate the `.env` file with the new credentials:

```bash
cd ansible
ansible-playbook setup_env.yml
```

This will create/update the `.env` file in the project root with the Google Chat credentials.

### Step 3: Verify Configuration

Check that the credentials are properly loaded:

```bash
cd ..
python -c "
from src.config import GOOGLE_CHAT_KEY, GOOGLE_CHAT_TOKEN, GOOGLE_CHAT_WEBHOOK_BASE_URL
print('✓ Webhook URL:', GOOGLE_CHAT_WEBHOOK_BASE_URL)
print('✓ Key configured:', 'Yes' if GOOGLE_CHAT_KEY else 'No')
print('✓ Token configured:', 'Yes' if GOOGLE_CHAT_TOKEN else 'No')
"
```

You should see:
```
✓ Webhook URL: https://chat.googleapis.com/v1/spaces/AAAA90FUe6M/messages
✓ Key configured: Yes
✓ Token configured: Yes
```

### Step 4: Test Manually

Test the leaderboard posting manually:

```bash
# This will check if today is Sunday and post appropriate leaderboard
python src/main.py --mode leaderboard
```

**Expected behavior:**
- **Monday-Saturday**: Posts daily leaderboard for yesterday
- **Sunday**: Posts weekly leaderboard for last 7 days
- If no cached data: Posts "No activity" message

### Step 5: CI/CD Setup

The GitHub Actions workflow is already configured to run the leaderboard posting after each nightly report generation.

**Workflow file**: `.github/workflows/nightly-report.yml`

**What it does:**
1. Runs at 12:00 AM IST daily (6:30 PM UTC)
2. Fetches commits and generates reports
3. Posts leaderboard to Google Chat (daily Mon-Sat, weekly Sun)
4. Continues workflow even if posting fails

**Required GitHub Secret:**
- `ANSIBLE_VAULT_PASSWORD` - Already configured in your repository

The workflow uses `continue-on-error: true` for the leaderboard step, so CI won't fail if Google Chat is unavailable.

## Manual Usage

You can manually run the leaderboard posting anytime:

```bash
# Post leaderboard (respects day of week - daily vs weekly)
python src/main.py --mode leaderboard

# Or run other modes
python src/main.py --mode status          # Check cache status
python src/main.py --mode fetch           # Fetch new commits
python src/main.py --mode chart           # Generate charts
python src/main.py --mode fetch_and_chart # Fetch and chart (default)
```

## Configuration

All configuration is in `src/config.py`:

- **Webhook URL**: `GOOGLE_CHAT_WEBHOOK_BASE_URL` (hardcoded)
- **Credentials**: `GOOGLE_CHAT_KEY` and `GOOGLE_CHAT_TOKEN` (from .env)
- **Reports URL**: `REPORTS_BASE_URL` (hardcoded)
- **Timezone**: `IST_TIMEZONE` for all date calculations

## Troubleshooting

### "No cached data found"

The leaderboard needs cached commit data. Run a fetch first:

```bash
python src/main.py --mode fetch
```

### "GOOGLE_CHAT_KEY not configured"

The .env file is missing or doesn't have the Google Chat credentials. Re-run:

```bash
cd ansible
ansible-playbook setup_env.yml
```

### "Failed to post to Google Chat"

Check the logs for HTTP error details. Common issues:
- Invalid webhook URL (check GOOGLE_CHAT_WEBHOOK_BASE_URL)
- Invalid key or token (check vault.yml values)
- Network connectivity issues
- Google Chat space permissions

### Webhook returns 400/401 errors

Verify your webhook URL format:
```
https://chat.googleapis.com/v1/spaces/AAAA90FUe6M/messages?key=<KEY>&token=<TOKEN>
```

The base URL, key, and token are combined automatically by the code.

## Message Format Example

**Daily Leaderboard (Monday-Saturday):**
```
📊 Daily Leaderboard (Feb 8, 2026)

🏆 Top Contributors by Commits
🥇 username1: 25 commits
🥈 username2: 18 commits
🥉 username3: 12 commits

📈 Top Contributors by Lines Changed
🥇 username1: 1,250 lines
🥈 username4: 980 lines
🥉 username2: 756 lines

🔗 View all reports: https://dolr-ai.github.io/github-report-script/
```

**Weekly Leaderboard (Sunday):**
```
📊 Weekly Leaderboard (Feb 2-8, 2026)

🏆 Top Contributors by Commits
🥇 username1: 142 commits
🥈 username2: 98 commits
🥉 username3: 76 commits

📈 Top Contributors by Lines Changed
🥇 username1: 8,450 lines
🥈 username4: 6,230 lines
🥉 username2: 4,890 lines

🔗 View all reports: https://dolr-ai.github.io/github-report-script/
```

## Files Modified/Created

### New Files:
- `src/leaderboard_generator.py` - Generates leaderboards from cached data
- `src/google_chat_poster.py` - Posts messages to Google Chat webhook
- `LEADERBOARD_SETUP.md` - This setup guide

### Modified Files:
- `src/config.py` - Added Google Chat config and LEADERBOARD mode
- `src/main.py` - Added cmd_leaderboard() function and mode handling
- `requirements.txt` - Added requests and pytz dependencies
- `ansible/vars/vault.yml.example` - Added Google Chat credentials template
- `ansible/vars/main.yml.example` - Added Google Chat variable references
- `ansible/vars/main.yml` - Added Google Chat variable references
- `ansible/templates/env.j2` - Added Google Chat env vars
- `.github/workflows/nightly-report.yml` - Added leaderboard posting step

## Architecture

```
┌─────────────────────────────────────────────────┐
│  GitHub Actions (Nightly at 12 AM IST)         │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│  1. Fetch commits & generate charts (existing)  │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│  2. Run: python src/main.py --mode leaderboard  │
└────────────────┬────────────────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ Check day of │  │ Read cached  │
│ week (IST)   │  │ commit data  │
└──────┬───────┘  └──────┬───────┘
       │                 │
       │                 ▼
       │         ┌──────────────┐
       │         │ Aggregate:   │
       │         │ - Commits    │
       │         │ - LOC        │
       │         └──────┬───────┘
       │                │
       ▼                ▼
┌──────────────────────────────┐
│  Generate Leaderboards:      │
│  - Top 3 by commits          │
│  - Top 3 by LOC              │
│  - Handle ties (same rank)   │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Format Message:             │
│  - Emojis (📊🏆📈🥇🥈🥉)     │
│  - Simple text               │
│  - Reports link              │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  POST to Google Chat         │
│  - Retry logic (3 attempts)  │
│  - Exponential backoff       │
│  - Error logging             │
└──────────────────────────────┘
```

## Support

If you encounter issues:
1. Check the logs: GitHub Actions workflow logs show detailed error messages
2. Test manually: Run `python src/main.py --mode leaderboard` locally
3. Verify credentials: Ensure vault.yml has correct key/token values
4. Check cache: Ensure cache/ directory has recent commit data

---

**Implementation complete!** ✅

The leaderboard system is production-ready and will automatically post to Google Chat daily at 12:00 AM IST once the vault credentials are configured.
