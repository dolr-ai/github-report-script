# GitHub Report Script

A configuration-driven Python script that fetches GitHub commits and lines of code metrics for specified users within an organization, and generates comparative visualizations showing daily activity.

**No command-line arguments needed** - all configuration is managed through `src/config.py` and secrets through Ansible Vault.

## Features

- **Configuration-Driven**: All settings in `src/config.py` - just edit and run
- **Secure Secret Management**: Ansible Vault for encrypted credential storage
- **Concurrent API Fetching**: Configurable thread pool (default 4 threads)
- **Smart Caching**: Day-wise JSON caching with selective refresh
- **Bot Filtering**: Automatically excludes bot commits via API type checking
- **Incremental Processing**: Skips already-processed dates unless explicitly refreshed
- **Dual Chart Output**: Interactive HTML (Plotly) + Static PNG/PDF (Matplotlib)
- **Comprehensive Metrics**: Tracks additions, deletions, total LOC, and commits separately
- **User Comparison**: Side-by-side visualization of multiple users
- **Data Persistence**: Cache, output, and reports committed to repository for tracking

## Installation

### Prerequisites

- Python 3.7 or higher
- Ansible (for secret management): `pip install ansible`
- GitHub Personal Access Token with `repo` and `read:org` scopes
- Access to the target GitHub organization (dolr-ai)

### Quick Start

```bash
# 1. Clone and install
git clone https://github.com/dolr-ai/github-report-script.git
cd github-report-script
pip install -r requirements.txt

# 2. Setup Ansible Vault (one-time setup)
cd ansible
./init_vault.sh
# Follow the prompts to set vault password and GitHub token

# 3. Configure execution
cd ../src
# Edit config.py and set:
#   MODE = ExecutionMode.FETCH
#   DATE_RANGE_MODE = DateRangeMode.LAST_N_DAYS
#   DAYS_BACK = 7

# 4. Run the script
cd ..
python src/main.py
```

## Configuration

### Execution Modes

Edit `src/config.py` to set the execution mode:

```python
from src.config import ExecutionMode, DateRangeMode

# What should the script do?
MODE = ExecutionMode.FETCH      # Fetch and process new data
# MODE = ExecutionMode.REFRESH  # Re-fetch specific dates (overwrites cache)
# MODE = ExecutionMode.CHART    # Generate visualizations
# MODE = ExecutionMode.STATUS   # Show status and rate limits
```

### Date Range Configuration

```python
# How to determine date range?
DATE_RANGE_MODE = DateRangeMode.LAST_N_DAYS
DAYS_BACK = 7

# For custom ranges:
# DATE_RANGE_MODE = DateRangeMode.CUSTOM_RANGE
# START_DATE = '2026-01-01'
# END_DATE = '2026-01-31'

# For single date:
# DATE_RANGE_MODE = DateRangeMode.SPECIFIC_DATE
# START_DATE = '2026-02-01'

# For charting all cached data:
# DATE_RANGE_MODE = DateRangeMode.ALL_CACHED
```

### User Configuration

```python
# GitHub usernames to track
USER_IDS = [
    'saikatdas0790',
    'gravityvi',
    # Add more usernames here
]
```

### Performance Settings

```python
# Number of concurrent threads
THREAD_COUNT = 4  # Conservative (default)
# THREAD_COUNT = 8  # Aggressive (faster, may hit rate limits)
# THREAD_COUNT = 1  # Debugging
```

See `src/config.py` for complete configuration options with examples.

## Usage

### Run the Script

```bash
python src/main.py
```

The script reads configuration from `src/config.py` and executes the configured mode.

### Common Workflows

#### Daily Data Collection
1. Edit `src/config.py`:
   ```python
   MODE = ExecutionMode.FETCH
   DATE_RANGE_MODE = DateRangeMode.LAST_N_DAYS
   DAYS_BACK = 1  # Yesterday only
   ```
2. Run: `python src/main.py`

#### Generate Weekly Report
1. Edit `src/config.py`:
   ```python
   MODE = ExecutionMode.FETCH
   DATE_RANGE_MODE = DateRangeMode.LAST_N_DAYS
   DAYS_BACK = 7
   ```
2. Run: `python src/main.py`
3. Edit `src/config.py`:
   ```python
   MODE = ExecutionMode.CHART
   ```
4. Run: `python src/main.py`

#### Refresh Specific Dates
1. Edit `src/config.py`:
   ```python
   MODE = ExecutionMode.REFRESH
   DATE_RANGE_MODE = DateRangeMode.CUSTOM_RANGE
   START_DATE = '2026-01-27'
   END_DATE = '2026-01-28'
   ```
2. Run: `python src/main.py`

#### Check Status
1. Edit `src/config.py`:
   ```python
   MODE = ExecutionMode.STATUS
   ```
2. Run: `python src/main.py`

## Ansible Vault - Secret Management

### Initial Setup

```bash
cd ansible
./init_vault.sh
```

This will:
1. Create vault password file (`.vault_pass`)
2. Prompt for GitHub Personal Access Token
3. Create and encrypt secrets (`vars/vault.yml`)
4. Generate `.env` file

### Managing Secrets

```bash
# View encrypted secrets
ansible-vault view vars/vault.yml

# Edit secrets
ansible-vault edit vars/vault.yml

# Regenerate .env file
ansible-playbook setup_env.yml

# Change vault password
ansible-vault rekey vars/vault.yml
```

See [ansible/README.md](ansible/README.md) for detailed vault management guide.

### Variable Structure

**vars/main.yml** (visible, committed):
```yaml
github_token: "{{ vault_github_token }}"
github_org: "dolr-ai"
```

**vars/vault.yml** (encrypted, committed):
```yaml
vault_github_token: "ghp_1234567890abcdef..."
```

## Project Structure

```
github-report-script/
├── src/
│   ├── config.py              # ⚙️  All configuration settings (edit this!)
│   ├── main.py                # Entry point (no args needed)
│   ├── cache_manager.py       # Caching logic
│   ├── github_fetcher.py      # GitHub API interaction
│   ├── data_processor.py      # Data aggregation
│   └── chart_generator.py     # Visualization
├── ansible/
│   ├── init_vault.sh          # 🔐 Vault setup script
│   ├── setup_env.yml          # Playbook to generate .env
│   ├── vars/
│   │   ├── main.yml           # Visible variable names
│   │   └── vault.yml          # Encrypted secrets
│   └── README.md              # Vault management guide
├── cache/                     # 📦 Raw commit data (committed)
│   └── commits/
│       └── YYYY-MM-DD.json
├── output/                    # 📊 Processed metrics (committed)
│   └── {username}/
│       └── YYYY-MM-DD.json
├── reports/                   # 📈 Generated charts (committed)
│   ├── report_*.html
│   ├── report_*.png
│   └── report_*.pdf
├── requirements.txt
└── README.md
```

## Data Flow

1. **Configuration** → `src/config.py` sets MODE and date range
2. **Secrets** → Ansible Vault decrypts to `.env`
3. **Fetch** → GitHub API → `cache/commits/{date}.json`
4. **Process** → Aggregate → `output/{user}/{date}.json`
5. **Chart** → Visualize → `reports/report_*.{html,png,pdf}`

## Chart Output

Each report contains a 2×2 grid:

| **Daily Additions** (lines added) | **Daily Deletions** (lines removed) |
|-----------------------------------|-------------------------------------|
| **Daily Total LOC** (added + deleted) | **Daily Commit Count** |

All users displayed side-by-side with grouped bars for easy comparison.

### Output Formats

- **HTML** (Plotly): Interactive with hover tooltips, zoom, pan
- **PNG**: High-resolution (300 DPI) static image
- **PDF**: Print-ready document format

## Configuration Examples

### Example 1: Weekly Report for All Users

```python
# src/config.py
MODE = ExecutionMode.FETCH
DATE_RANGE_MODE = DateRangeMode.LAST_N_DAYS
DAYS_BACK = 7
THREAD_COUNT = 4

USER_IDS = [
    'saikatdas0790',
    'gravityvi',
    'jay-dhanwant-yral',
    # ... all users
]
```

### Example 2: Monthly Report

```python
MODE = ExecutionMode.FETCH
DATE_RANGE_MODE = DateRangeMode.CUSTOM_RANGE
START_DATE = '2026-01-01'
END_DATE = '2026-01-31'
THREAD_COUNT = 8  # Faster for large date ranges
```

### Example 3: Single User, Specific Date

```python
MODE = ExecutionMode.FETCH
DATE_RANGE_MODE = DateRangeMode.SPECIFIC_DATE
START_DATE = '2026-02-01'

USER_IDS = ['saikatdas0790']  # Single user only
```

### Example 4: Chart All Cached Data

```python
MODE = ExecutionMode.CHART
DATE_RANGE_MODE = DateRangeMode.ALL_CACHED
# Uses all dates found in cache/
```

## Rate Limiting

GitHub API limits:
- **Authenticated**: 5,000 requests/hour
- **Per repository**: ~1-5 requests
- **Concurrent threads**: Default 4 (adjustable)

The script automatically:
- ✓ Monitors rate limits
- ✓ Waits when limit is low (<100 remaining)
- ✓ Uses caching to minimize requests
- ✓ Skips already-processed dates

Check current status:
```python
# src/config.py
MODE = ExecutionMode.STATUS
```

Then run: `python src/main.py`

## Troubleshooting

### "GITHUB_TOKEN is not set"

**Solution**: Run Ansible playbook to generate `.env`:
```bash
cd ansible
ansible-playbook setup_env.yml
```

### "USER_IDS list is empty"

**Solution**: Edit `src/config.py` and add usernames:
```python
USER_IDS = ['username1', 'username2']
```

### "Vault password file not found"

**Solution**: Initialize vault:
```bash
cd ansible
./init_vault.sh
```

### "No cached data found"

**Solution**: Run fetch mode first:
```python
# src/config.py
MODE = ExecutionMode.FETCH
```

### Rate limit exceeded

**Solution**:
- Check status: `MODE = ExecutionMode.STATUS`
- Reduce threads: `THREAD_COUNT = 2`
- Wait for reset (shown in status output)
- Use cached data (avoid REFRESH mode)

### "Import ModuleNotFoundError"

**Solution**: Install dependencies:
```bash
pip install -r requirements.txt
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Daily Report
on:
  schedule:
    - cron: '0 0 * * *'  # Daily at midnight

jobs:
  generate-report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install ansible
      
      - name: Setup secrets
        env:
          VAULT_PASSWORD: ${{ secrets.ANSIBLE_VAULT_PASSWORD }}
        run: |
          cd ansible
          echo "$VAULT_PASSWORD" > .vault_pass
          ansible-playbook setup_env.yml
      
      - name: Run report
        run: python src/main.py
      
      - name: Commit results
        run: |
          git config user.name "GitHub Actions"
          git config user.email "actions@github.com"
          git add cache/ output/ reports/
          git commit -m "Daily report $(date +%Y-%m-%d)" || true
          git push
```

## Development

### Adding New Configuration Options

1. **Add enum** (if applicable) in `src/config.py`:
   ```python
   class NewFeature(Enum):
       OPTION_A = "option_a"
       OPTION_B = "option_b"
   ```

2. **Add configuration variable**:
   ```python
   NEW_SETTING = NewFeature.OPTION_A
   """Documentation for NEW_SETTING"""
   ```

3. **Add validation** in `validate_config()`:
   ```python
   if not isinstance(NEW_SETTING, NewFeature):
       errors.append("NEW_SETTING must be a NewFeature enum")
   ```

4. **Use in code**:
   ```python
   from src.config import NEW_SETTING, NewFeature
   
   if NEW_SETTING == NewFeature.OPTION_A:
       # Do something
   ```

### Adding New Secrets

1. **Edit** `ansible/vars/main.yml`:
   ```yaml
   new_api_key: "{{ vault_new_api_key }}"
   ```

2. **Edit vault**:
   ```bash
   ansible-vault edit ansible/vars/vault.yml
   ```
   Add:
   ```yaml
   vault_new_api_key: "your_secret"
   ```

3. **Update template** `ansible/templates/env.j2`:
   ```
   NEW_API_KEY={{ new_api_key }}
   ```

4. **Regenerate .env**:
   ```bash
   cd ansible && ansible-playbook setup_env.yml
   ```

## License

MIT License - See LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with different configurations
5. Submit a pull request

## Support

- **Issues**: https://github.com/dolr-ai/github-report-script/issues
- **Vault Guide**: [ansible/README.md](ansible/README.md)
- **Config Reference**: See comments in `src/config.py`

---

**Quick Reference:**

| Task | Configuration | Command |
|------|---------------|---------|
| Setup vault | N/A | `cd ansible && ./init_vault.sh` |
| Fetch last 7 days | `MODE = FETCH`, `DAYS_BACK = 7` | `python src/main.py` |
| Refresh specific dates | `MODE = REFRESH`, set START/END_DATE | `python src/main.py` |
| Generate charts | `MODE = CHART` | `python src/main.py` |
| Check status | `MODE = STATUS` | `python src/main.py` |
| Edit secrets | N/A | `ansible-vault edit ansible/vars/vault.yml` |
| View secrets | N/A | `ansible-vault view ansible/vars/vault.yml` |
