"""
Configuration settings for GitHub Report Script

This file contains all configuration for the script. No command-line arguments needed.
Simply edit the settings below and run: python src/main.py
"""
import os
import logging
from enum import Enum
from datetime import datetime, timedelta
from typing import Optional, List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================


class LogLevel(Enum):
    """Logging levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


# Set logging level (DEBUG shows all details, INFO shows progress, WARNING/ERROR minimal)
LOG_LEVEL = LogLevel.INFO

# Configure logging format
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.value),
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


# ============================================================================
# ENUMS - All possible configuration options
# ============================================================================

class ExecutionMode(Enum):
    """
    Execution mode for the script.

    FETCH: Fetch commits from GitHub, cache them, and process to output/
    REFRESH: Force re-fetch for specified date range (overwrites cache)
    CHART: Generate visualizations from existing processed data
    STATUS: Display current status (rate limits, cached data, etc.)
    FETCH_AND_CHART: Fetch data and immediately generate charts (combined mode)
    """
    FETCH = "fetch"
    REFRESH = "refresh"
    CHART = "chart"
    STATUS = "status"
    FETCH_AND_CHART = "fetch_and_chart"


class DateRangeMode(Enum):
    """
    How to determine the date range for operations.

    LAST_N_DAYS: Last N complete days (excludes today's incomplete data)
    CUSTOM_RANGE: Use specific START_DATE and END_DATE
    SPECIFIC_DATE: Single date (use START_DATE only)
    ALL_CACHED: Use all dates that exist in cache (for CHART mode)
    """
    LAST_N_DAYS = "last_n_days"
    CUSTOM_RANGE = "custom_range"
    SPECIFIC_DATE = "specific_date"
    ALL_CACHED = "all_cached"


# ============================================================================
# PRIMARY CONFIGURATION - Edit these settings
# ============================================================================

# --- Execution Configuration ---
MODE = ExecutionMode.FETCH_AND_CHART
"""
What should the script do when run?

Examples:
    MODE = ExecutionMode.FETCH       # Fetch and process new data
    MODE = ExecutionMode.REFRESH     # Re-fetch specific date range
    MODE = ExecutionMode.CHART       # Generate charts from existing data
    MODE = ExecutionMode.STATUS      # Check status
    MODE = ExecutionMode.FETCH_AND_CHART  # Fetch data and generate charts (combined)
"""

# --- Date Range Configuration ---
DATE_RANGE_MODE = DateRangeMode.LAST_N_DAYS
"""
How to determine the date range.

Examples:
    DATE_RANGE_MODE = DateRangeMode.LAST_N_DAYS     # Last 7 days (default)
    DATE_RANGE_MODE = DateRangeMode.CUSTOM_RANGE    # Specific date range
    DATE_RANGE_MODE = DateRangeMode.SPECIFIC_DATE   # Single date
    DATE_RANGE_MODE = DateRangeMode.ALL_CACHED      # All cached dates
"""

DAYS_BACK = 7
"""Number of days to go back when DATE_RANGE_MODE = LAST_N_DAYS"""

START_DATE: Optional[str] = '2026-01-05'
"""
Start date for CUSTOM_RANGE or SPECIFIC_DATE modes.
Format: 'YYYY-MM-DD'

Examples:
    START_DATE = '2026-01-01'
    START_DATE = '2026-01-27'
"""

END_DATE: Optional[str] = '2026-01-21'
"""
End date for CUSTOM_RANGE mode.
Format: 'YYYY-MM-DD'

Examples:
    END_DATE = '2026-01-31'
    END_DATE = '2026-02-03'
"""

# --- GitHub Configuration ---
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
"""GitHub Personal Access Token (loaded from .env file)"""

GITHUB_ORG = os.getenv('GITHUB_ORG', 'dolr-ai')
"""GitHub organization to fetch commits from"""

USER_IDS: List[str] = [
    'saikatdas0790',
    'gravityvi',
    'jay-dhanwant-yral',
    'joel-medicala-yral',
    'kevin-antony-yral',
    'mayank-k-yral',
    'naitik-makwana-yral',
    'ravi-sawlani-yral',
    'samarth-paboowal-yral',
    'sarvesh-sharma-yral',
    'shivam-bhavsar-yral',
]
"""
GitHub usernames to track.
Add or remove usernames as needed.
"""

# --- Performance Configuration ---
THREAD_COUNT = 4
"""
Number of concurrent threads for API requests.
Higher values = faster but may hit rate limits.

Recommended:
    - 2-4 threads: Conservative (current - good for pagination which makes many API calls)
    - 8 threads: Aggressive (faster but may hit rate limits with branch pagination)
    - 16+ threads: May exceed connection pool capacity (requires pool_size adjustment)
    - 1 thread: Debugging or rate limit issues

Note: PyGithub uses urllib3 connection pooling (default pool_size=10).
THREAD_COUNT should be <= pool_size to avoid connection pool warnings.
"""

# --- Bot Filtering Configuration ---
KNOWN_BOTS: List[str] = [
    'dependabot[bot]',
    'dependabot-preview[bot]',
    'github-actions[bot]',
    'renovate[bot]',
    'greenkeeper[bot]',
    'snyk-bot',
    'pyup-bot',
]
"""
Known bot usernames for fallback filtering.
Primary filtering uses GitHub API user type check.
"""


# ============================================================================
# PATHS - Directory structure (usually no need to change)
# ============================================================================

CACHE_DIR = 'cache'
CACHE_COMMITS_DIR = os.path.join(CACHE_DIR, 'commits')
CACHE_METADATA_FILE = os.path.join(CACHE_DIR, 'metadata.json')
OUTPUT_DIR = 'output'
REPORTS_DIR = 'reports'


# ============================================================================
# COMPUTED CONFIGURATION - Derived from settings above
# ============================================================================

def get_date_range() -> tuple:
    """
    Calculate start and end dates based on configuration.

    Returns:
        Tuple of (start_date, end_date) as datetime objects

    Raises:
        ValueError: If configuration is invalid
    """
    if DATE_RANGE_MODE == DateRangeMode.LAST_N_DAYS:
        # End date is yesterday (exclude today's incomplete data)
        end_date = datetime.now() - timedelta(days=1)
        # Set to end of day
        end_date = end_date.replace(
            hour=23, minute=59, second=59, microsecond=999999)
        # Calculate start date
        start_date = end_date - timedelta(days=DAYS_BACK - 1)
        start_date = start_date.replace(
            hour=0, minute=0, second=0, microsecond=0)
        return start_date, end_date

    elif DATE_RANGE_MODE == DateRangeMode.CUSTOM_RANGE:
        if not START_DATE or not END_DATE:
            raise ValueError(
                "CUSTOM_RANGE mode requires both START_DATE and END_DATE to be set.\n"
                f"Current: START_DATE={START_DATE}, END_DATE={END_DATE}"
            )
        start_date = datetime.strptime(START_DATE, '%Y-%m-%d')
        end_date = datetime.strptime(END_DATE, '%Y-%m-%d')

        if start_date > end_date:
            raise ValueError(
                f"START_DATE ({START_DATE}) must be before END_DATE ({END_DATE})")

        return start_date, end_date

    elif DATE_RANGE_MODE == DateRangeMode.SPECIFIC_DATE:
        if not START_DATE:
            raise ValueError(
                "SPECIFIC_DATE mode requires START_DATE to be set")
        date = datetime.strptime(START_DATE, '%Y-%m-%d')
        return date, date

    elif DATE_RANGE_MODE == DateRangeMode.ALL_CACHED:
        # Will be handled by reading actual cache
        return None, None

    else:
        raise ValueError(f"Unknown DATE_RANGE_MODE: {DATE_RANGE_MODE}")


def validate_config():
    """
    Validate that required configuration is present and valid.

    Raises:
        ValueError: If configuration is invalid with helpful error messages
    """
    errors = []

    # Check GitHub token
    if not GITHUB_TOKEN:
        errors.append(
            "❌ GITHUB_TOKEN is not set.\n"
            "   Solution: Run the Ansible playbook to generate .env file:\n"
            "   cd ansible && ansible-playbook setup_env.yml"
        )

    # Check user IDs
    if not USER_IDS:
        errors.append(
            "❌ USER_IDS list is empty.\n"
            "   Solution: Edit src/config.py and add GitHub usernames to USER_IDS list"
        )

    # Validate execution mode
    if not isinstance(MODE, ExecutionMode):
        errors.append(
            f"❌ MODE must be an ExecutionMode enum value.\n"
            f"   Current: {MODE}\n"
            f"   Valid options: {[m.value for m in ExecutionMode]}"
        )

    # Validate date range mode
    if not isinstance(DATE_RANGE_MODE, DateRangeMode):
        errors.append(
            f"❌ DATE_RANGE_MODE must be a DateRangeMode enum value.\n"
            f"   Current: {DATE_RANGE_MODE}\n"
            f"   Valid options: {[m.value for m in DateRangeMode]}"
        )

    # Validate date range configuration
    try:
        if DATE_RANGE_MODE != DateRangeMode.ALL_CACHED:
            get_date_range()
    except ValueError as e:
        errors.append(f"❌ Date range configuration error: {e}")

    # Validate thread count
    if not isinstance(THREAD_COUNT, int) or THREAD_COUNT < 1:
        errors.append(
            f"❌ THREAD_COUNT must be a positive integer.\n"
            f"   Current: {THREAD_COUNT}"
        )

    if errors:
        raise ValueError(
            "\n\n" + "="*70 + "\n"
            "Configuration Errors\n"
            "="*70 + "\n\n" +
            "\n\n".join(errors) + "\n\n" +
            "="*70 + "\n"
        )

    return True


def display_config():
    """Display current configuration in a readable format."""
    start_date, end_date = get_date_range(
    ) if DATE_RANGE_MODE != DateRangeMode.ALL_CACHED else (None, None)

    config_display = f"""
{"="*70}
GitHub Report Script - Configuration
{"="*70}

Execution Mode:       {MODE.value.upper()}
Organization:         {GITHUB_ORG}
Users to Track:       {len(USER_IDS)} user(s)
                      {', '.join(USER_IDS[:3])}{'...' if len(USER_IDS) > 3 else ''}

Date Range Mode:      {DATE_RANGE_MODE.value}"""

    if start_date and end_date:
        config_display += f"""
Start Date:           {start_date.date()}
End Date:             {end_date.date()}
Days Covered:         {(end_date - start_date).days + 1}"""
    elif DATE_RANGE_MODE == DateRangeMode.ALL_CACHED:
        config_display += """
Date Range:           All cached dates"""

    config_display += f"""

Performance:
  Concurrent Threads: {THREAD_COUNT}

{"="*70}
"""

    return config_display
