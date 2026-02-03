"""
Configuration settings for GitHub Report Script
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# GitHub Configuration
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_ORG = os.getenv('GITHUB_ORG', 'dolr-ai')

# User IDs to track
# Add GitHub usernames here
USER_IDS = [
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

# Default Settings
DEFAULT_THREAD_COUNT = 4
DEFAULT_DAYS_BACK = 7

# Bot usernames to check (for fallback if API type check fails)
KNOWN_BOTS = [
    'dependabot[bot]',
    'dependabot-preview[bot]',
    'github-actions[bot]',
    'renovate[bot]',
    'greenkeeper[bot]',
    'snyk-bot',
    'pyup-bot',
]

# Paths
CACHE_DIR = 'cache'
CACHE_COMMITS_DIR = os.path.join(CACHE_DIR, 'commits')
CACHE_METADATA_FILE = os.path.join(CACHE_DIR, 'metadata.json')
OUTPUT_DIR = 'output'
REPORTS_DIR = 'reports'

# Validate configuration


def validate_config():
    """Validate that required configuration is present"""
    errors = []

    if not GITHUB_TOKEN:
        errors.append(
            "GITHUB_TOKEN environment variable is not set. Please create a .env file based on .env.example")

    if not USER_IDS:
        errors.append(
            "USER_IDS list is empty in src/config.py. Please add GitHub usernames to track.")

    if errors:
        raise ValueError("\n".join(["Configuration errors:"] + errors))

    return True
