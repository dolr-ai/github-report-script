#!/usr/bin/env python3
"""
Quick test of the new user-first GraphQL approach
"""
import logging
from src.github_fetcher import GitHubFetcher
from src.config import GITHUB_TOKEN, GITHUB_ORG, USER_IDS
import sys
import os
from datetime import datetime, timedelta

# Setup path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


def test_new_approach():
    """Test the new user-first approach with a single day"""

    # Test with just the last 2 days to minimize API calls
    end_date = datetime.now()
    start_date = end_date - timedelta(days=2)

    # Use only first 2 users for testing
    test_users = USER_IDS[:2]

    print("=" * 70)
    print("Testing New User-First GraphQL Approach")
    print("=" * 70)
    print(f"Organization: {GITHUB_ORG}")
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print(f"Users: {test_users}")
    print("=" * 70)
    print()

    # Create fetcher with single thread for easier debugging
    fetcher = GitHubFetcher(thread_count=1)

    # Check rate limit before starting
    rate_limit = fetcher.get_rate_limit_status()
    print(
        f"Initial rate limit: {rate_limit['remaining']}/{rate_limit['limit']}")
    print()

    # Fetch commits
    logger.info("Starting fetch...")
    results = fetcher.fetch_commits(
        start_date,
        end_date,
        test_users,
        force_refresh=True  # Force refresh to test the new code path
    )

    # Show results
    print()
    print("=" * 70)
    print("Results:")
    print("=" * 70)

    total_commits = 0
    for date_str, data in sorted(results.items()):
        commits = data.get('commits', [])
        total_commits += len(commits)
        print(f"\n{date_str}: {len(commits)} commits")

        # Group by user
        user_commits = {}
        for commit in commits:
            author = commit['author']
            if author not in user_commits:
                user_commits[author] = []
            user_commits[author].append(commit)

        for user, user_commit_list in sorted(user_commits.items()):
            repos = set(c['repository'] for c in user_commit_list)
            total_loc = sum(c['stats']['total'] for c in user_commit_list)
            print(
                f"  {user}: {len(user_commit_list)} commits, {total_loc} LOC across {len(repos)} repos")
            for commit in user_commit_list[:3]:  # Show first 3 commits
                branches = ', '.join(
                    commit['branches'][:3]) if commit['branches'] else 'no branches'
                print(
                    f"    - {commit['sha'][:7]}: {commit['message'][:60]} ({branches})")

    print(f"\nTotal commits fetched: {total_commits}")

    # Check rate limit after
    rate_limit_after = fetcher.get_rate_limit_status()
    print(
        f"Final rate limit: {rate_limit_after['remaining']}/{rate_limit_after['limit']}")
    print(
        f"API calls used: ~{rate_limit['remaining'] - rate_limit_after['remaining']}")

    print("\n" + "=" * 70)
    print("✓ Test complete!")
    print("=" * 70)


if __name__ == '__main__':
    try:
        test_new_approach()
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
