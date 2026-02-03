# GitHub Report Script

A Python script that fetches GitHub commits and lines of code metrics for specified users within an organization, and generates comparative visualizations showing daily activity.

## Features

- **Concurrent API Fetching**: Uses configurable thread pool (default 4 threads) for efficient data collection
- **Smart Caching**: Day-wise JSON caching with selective refresh to minimize API calls
- **Bot Filtering**: Automatically excludes bot commits (Dependabot, GitHub Actions, etc.) via API type checking
- **Incremental Processing**: Skips already-processed dates unless explicitly refreshed
- **Dual Chart Output**: Generates both interactive HTML (Plotly) and static PNG/PDF (Matplotlib) charts
- **Comprehensive Metrics**: Tracks additions, deletions, total LOC, and commit counts separately and combined
- **User Comparison**: Side-by-side visualization of multiple users on the same charts

## Installation

### Prerequisites

- Python 3.7 or higher
- GitHub Personal Access Token with `repo` and `read:org` scopes
- Access to the target GitHub organization

### Setup

#### Quick Start (Recommended)

```bash
git clone https://github.com/dolr-ai/github-report-script.git
cd github-report-script
pip install -r requirements.txt
./quickstart.sh
```

The quickstart script will guide you through configuration.

#### Manual Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/dolr-ai/github-report-script.git
   cd github-report-script
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env and add your GitHub token
   ```

4. **Configure users to track**:
   Edit `src/config.py` and add GitHub usernames to the `USER_IDS` list:
   ```python
   USER_IDS = [
       'octocat',
       'torvalds',
       'your-username',
   ]
   ```

## Usage

### Basic Commands

#### Fetch Data (Last 7 Days)
```bash
python report.py fetch
# or: python -m src.main fetch
```

Fetches commits from the dolr-ai organization for the last 7 days, caches raw data, and processes metrics per user.

#### Fetch Specific Date Range
```bash
python report.py fetch --start-date 2026-01-01 --end-date 2026-01-31
```

#### Refresh Cache
```bash
python report.py refresh --start-date 2026-01-27 --end-date 2026-01-28
```

Forces re-fetch and overwrites existing cache for the specified date range.

#### Generate Charts
```bash
python report.py chart
```

Generates interactive HTML and static PNG/PDF charts from processed data for the last 7 days.

#### Generate Charts for Specific Range
```bash
python report.py chart --start-date 2026-01-01 --end-date 2026-01-31
```

#### Check Status
```bash
python report.py status
```

Shows GitHub API rate limit, cached dates, and processed data summary.

### Advanced Options

#### Custom Thread Count
```bash
python report.py fetch --threads 8
```

Adjusts concurrent thread count (useful if rate limits are hit or faster fetching is needed).

## Configuration

### GitHub Token

Create a Personal Access Token at: https://github.com/settings/tokens

Required scopes:
- `repo` (for private repositories) or `public_repo` (for public only)
- `read:org` (to list organization repositories)

Add to `.env` file:
```env
GITHUB_TOKEN=your_token_here
GITHUB_ORG=dolr-ai
```

### User Configuration

Edit `src/config.py`:

```python
# Users to track
USER_IDS = [
    'user1',
    'user2',
    'user3',
]

# Default settings
DEFAULT_THREAD_COUNT = 4
DEFAULT_DAYS_BACK = 7
```

### Bot Filtering

Bot commits are automatically filtered using GitHub API's user type check. Known bots are also filtered by name pattern:
- dependabot[bot]
- github-actions[bot]
- renovate[bot]
- And others (see `src/config.py`)

## Data Structure

### Cache Structure
```
cache/
├── commits/
│   ├── 2026-01-27.json
│   ├── 2026-01-28.json
│   └── 2026-01-29.json
└── metadata.json
```

Each daily cache file contains:
```json
{
  "date": "2026-01-27",
  "cached_at": "2026-02-03T10:30:00Z",
  "commits": [
    {
      "sha": "abc123...",
      "author": "username",
      "repository": "dolr-ai/repo-name",
      "timestamp": "2026-01-27T14:23:00Z",
      "message": "commit message",
      "stats": {
        "additions": 45,
        "deletions": 12,
        "total": 57
      }
    }
  ],
  "commit_count": 1
}
```

### Output Structure
```
output/
├── user1/
│   ├── 2026-01-27.json
│   ├── 2026-01-28.json
│   └── 2026-01-29.json
└── user2/
    ├── 2026-01-27.json
    └── 2026-01-29.json
```

Each user/date file contains pre-aggregated metrics:
```json
{
  "date": "2026-01-27",
  "username": "user1",
  "additions": 150,
  "deletions": 30,
  "total_loc": 180,
  "commit_count": 5,
  "repositories": ["dolr-ai/repo1", "dolr-ai/repo2"],
  "repo_count": 2,
  "processed_at": "2026-02-03T10:35:00Z"
}
```

### Reports Structure
```
reports/
├── report_2026-01-27_to_2026-02-03_20260203_103545.html
├── report_2026-01-27_to_2026-02-03_20260203_103545.png
└── report_2026-01-27_to_2026-02-03_20260203_103545.pdf
```

Reports are timestamped to prevent overwrites.

## Workflow

### Typical Usage Pattern

1. **Initial fetch**:
   ```bash
   python report.py fetch
   ```
   Fetches last 7 days, caches raw data, processes metrics.

2. **Generate visualizations**:
   ```bash
   python report.py chart
   ```
   Creates interactive HTML and static PNG/PDF charts.

3. **Daily updates** (run next day):
   ```bash
   python report.py fetch
   ```
   Only fetches new date (today), skips cached dates.

4. **Periodic refresh** (if data needs updating):
   ```bash
   python report.py refresh --start-date 2026-01-27
   ```
   Re-fetches specific dates, overwrites cache and output.

### Cache Behavior

- **Incremental fetching**: `fetch` command skips dates already in cache
- **Force refresh**: `refresh` command overwrites existing cache for specified dates
- **Incremental processing**: Output files are skipped unless refresh is used
- **Zero-commit handling**: Users with no commits on a date show 0 for all metrics

## Chart Features

### Interactive HTML (Plotly)
- Hover tooltips showing exact values
- Zoom and pan capabilities
- Legend toggling to focus on specific users
- Responsive design
- Single-file output (no external dependencies)

### Static PNG/PDF (Matplotlib)
- High resolution (300 DPI for PNG)
- Publication-quality output
- Suitable for reports and documentation
- Multiple formats for flexibility

### Chart Layout
Each report contains a 2x2 grid showing:
1. **Daily Additions**: Lines of code added per day
2. **Daily Deletions**: Lines of code removed per day
3. **Daily Total LOC**: Total lines changed (additions + deletions)
4. **Daily Commit Count**: Number of commits per day

All charts show users side-by-side with grouped bars for easy comparison.

## Rate Limiting

GitHub API limits:
- **Authenticated**: 5,000 requests per hour
- **Unauthenticated**: 60 requests per hour (not supported)

The script:
- Monitors rate limits automatically
- Waits when limit is low (<100 remaining)
- Uses concurrent threads efficiently
- Caches aggressively to minimize API calls

## Troubleshooting

### "GITHUB_TOKEN environment variable is not set"
Create a `.env` file based on `.env.example` and add your token.

### "USER_IDS list is empty"
Edit `src/config.py` and add GitHub usernames to track.

### Rate limit exceeded
- Reduce thread count: `--threads 2`
- Wait for rate limit reset (check with `python report.py status`)
- Use cached data: avoid `refresh` command

### No data found for user
- Verify username spelling in `src/config.py`
- Check if user has commits in dolr-ai organization
- Ensure date range includes their commit activity

### Charts show all zeros
- Run `fetch` command first to collect data
- Verify date range matches available data
- Check if users have commits in the specified period

## Examples

### Monthly Report
```bash
# Fetch entire month
python report.py fetch --start-date 2026-01-01 --end-date 2026-01-31

# Generate charts
python report.py chart --start-date 2026-01-01 --end-date 2026-01-31
```

### Update Yesterday's Data
```bash
python report.py refresh --start-date 2026-02-02 --end-date 2026-02-02
python report.py chart --start-date 2026-01-27 --end-date 2026-02-03
```

### Fast Fetching with More Threads
```bash
python report.py fetch --threads 8 --start-date 2026-01-01 --end-date 2026-01-31
```

## Development

### Project Structure
```
github-report-script/
├── src/
│   ├── __init__.py
│   ├── main.py              # CLI entry point
│   ├── config.py            # Configuration
│   ├── cache_manager.py     # Caching logic
│   ├── github_fetcher.py    # GitHub API interaction
│   ├── data_processor.py    # Data aggregation
│   └── chart_generator.py   # Visualization
├── cache/                   # Cached raw data (gitignored)
├── output/                  # Processed metrics (gitignored)
├── reports/                 # Generated charts (gitignored)
├── examples/                # Sample outputs (committed)
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions welcome! Please open an issue or pull request.