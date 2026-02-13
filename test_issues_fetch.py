#!/usr/bin/env python3
"""
Test script for issue fetching functionality
Tests the _fetch_closed_issues_for_user method in isolation
"""
from src.config import GITHUB_ORG
from src.github_fetcher import GitHubFetcher
import sys
import os
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_fetch_closed_issues():
    """Test fetching closed issues for a user"""
    print("=" * 70)
    print("Testing Issue Fetching Functionality")
    print("=" * 70)

    # Initialize fetcher
    fetcher = GitHubFetcher()

    # Test with a date range (last 30 days)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)

    print(f"\nTest Parameters:")
    print(f"  Organization: {GITHUB_ORG}")
    print(f"  Date Range: {start_date.date()} to {end_date.date()}")
    print(f"  Users to test: saikatdas0790, gravityvi")

    # Test with first two users
    test_users = ['saikatdas0790', 'gravityvi']

    for username in test_users:
        print(f"\n{'-' * 70}")
        print(f"Testing user: {username}")
        print(f"{'-' * 70}")

        try:
            issues = fetcher._fetch_closed_issues_for_user(
                username=username,
                org=GITHUB_ORG,
                start_date=start_date,
                end_date=end_date
            )

            print(f"✓ Successfully fetched {len(issues)} closed issues")

            if issues:
                print(f"\nSample issues (first 3):")
                for i, issue in enumerate(issues[:3], 1):
                    print(
                        f"  {i}. Issue #{issue['number']}: {issue['title'][:60]}")
                    print(f"     Repository: {issue['repository']}")
                    print(f"     Closed: {issue['closed_at'][:10]}")
                    print(f"     URL: {issue['url']}")
                    print(
                        f"     Labels: {', '.join(issue['labels']) if issue['labels'] else 'None'}")
                    print()

                # Verify data structure
                print(f"✓ Data structure validation:")
                required_fields = ['number', 'title', 'closed_at',
                                   'assignee', 'repository', 'url', 'labels']
                sample = issues[0]
                for field in required_fields:
                    if field in sample:
                        print(f"  ✓ Field '{field}' present")
                    else:
                        print(f"  ✗ Field '{field}' MISSING")

                # Verify filtering
                print(f"\n✓ Filtering verification:")
                all_assigned = all(issue['assignee'] ==
                                   username for issue in issues)
                print(f"  All issues assigned to {username}: {all_assigned}")

                all_in_org = all(issue['repository'].startswith(
                    f"{GITHUB_ORG}/") for issue in issues)
                print(f"  All issues from {GITHUB_ORG}: {all_in_org}")

                print(f"\n✓ Date range verification:")
                for issue in issues[:3]:
                    closed_date = datetime.fromisoformat(
                        issue['closed_at'].replace('Z', '+00:00'))
                    in_range = start_date <= closed_date <= end_date
                    print(
                        f"  Issue #{issue['number']}: {closed_date.date()} - {'✓' if in_range else '✗'}")
            else:
                print(
                    f"  No issues found (this is okay if user has no closed issues in date range)")

        except Exception as e:
            print(f"✗ Error fetching issues: {e}")
            import traceback
            traceback.print_exc()
            return False

    print(f"\n{'=' * 70}")
    print("✓ Issue Fetching Test Complete!")
    print(f"{'=' * 70}")
    return True


if __name__ == "__main__":
    success = test_fetch_closed_issues()
    sys.exit(0 if success else 1)
