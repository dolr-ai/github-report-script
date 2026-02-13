#!/usr/bin/env python3
"""
Detailed test for issue fetching with more information about why no issues are found
"""
from config import GITHUB_ORG
from github_fetcher import GitHubFetcher
import sys
import os
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def test_issues_with_details():
    """Test issue fetching and show detailed information"""
    print("="*70)
    print("Detailed Issue Fetching Test")
    print("="*70)

    fetcher = GitHubFetcher()

    # Test with a longer date range (last 90 days)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)

    print(f"\nTest Parameters:")
    print(f"  Organization: {GITHUB_ORG}")
    print(f"  Date Range: {start_date.date()} to {end_date.date()}")
    print(f"  Looking back: 90 days")

    # Test with the primary user
    test_user = "saikatdas0790"

    print(f"\n{'='*70}")
    print(f"Testing user: {test_user}")
    print(f"{'='*70}")

    # First, let's check what GraphQL returns without filtering
    query = """
    query($username: String!) {
      user(login: $username) {
        login
        issues(
          first: 5,
          filterBy: {states: CLOSED},
          orderBy: {field: UPDATED_AT, direction: DESC}
        ) {
          totalCount
          nodes {
            number
            title
            closedAt
            repository {
              nameWithOwner
              owner {
                login
              }
            }
            assignees(first: 10) {
              nodes {
                login
              }
            }
          }
        }
      }
    }
    """

    variables = {'username': test_user}
    print(f"\nFetching first 5 closed issues from GitHub...")
    response = fetcher._graphql_request(query, variables)

    if response and response.get('user'):
        user_data = response['user']
        issues_data = user_data.get('issues', {})
        total_count = issues_data.get('totalCount', 0)
        nodes = issues_data.get('nodes', [])

        print(f"✓ Total closed issues for {test_user}: {total_count}")
        print(f"✓ Fetched {len(nodes)} sample issues")

        if nodes:
            print(f"\nSample issues (checking why they might be filtered):")
            for i, issue in enumerate(nodes, 1):
                print(f"\n  Issue {i}:")
                print(f"    #{issue['number']}: {issue['title'][:50]}...")
                print(f"    Closed: {issue['closedAt']}")
                print(f"    Repo: {issue['repository']['nameWithOwner']}")
                print(
                    f"    Repo Owner: {issue['repository']['owner']['login']}")

                assignees = issue['assignees']['nodes']
                assignee_logins = [a['login'] for a in assignees]
                print(
                    f"    Assignees: {', '.join(assignee_logins) if assignee_logins else 'None'}")

                # Check filtering criteria
                repo_owner = issue['repository']['owner']['login']
                is_assigned = test_user in assignee_logins

                closed_at = datetime.fromisoformat(
                    issue['closedAt'].replace('Z', '+00:00'))
                in_date_range = start_date.replace(
                    tzinfo=closed_at.tzinfo) <= closed_at <= end_date.replace(tzinfo=closed_at.tzinfo)

                print(f"    Filters:")
                print(
                    f"      ✓ Org match ({GITHUB_ORG}): {repo_owner == GITHUB_ORG}")
                print(f"      ✓ Assigned to {test_user}: {is_assigned}")
                print(f"      ✓ In date range: {in_date_range}")

                passes_all = (
                    repo_owner == GITHUB_ORG) and is_assigned and in_date_range
                print(
                    f"      {'✓ PASSES all filters' if passes_all else '✗ FAILS at least one filter'}")
        else:
            print(f"\n✗ No issues found at all for {test_user}")
    else:
        print(f"✗ Failed to fetch issues from GraphQL")

    # Now test with our method
    print(f"\n{'='*70}")
    print(f"Testing _fetch_closed_issues_for_user method")
    print(f"{'='*70}")

    issues = fetcher._fetch_closed_issues_for_user(
        username=test_user,
        org=GITHUB_ORG,
        start_date=start_date,
        end_date=end_date
    )

    print(f"\n✓ Method returned {len(issues)} issues after filtering")

    if issues:
        print(f"\nIssues that passed all filters:")
        for i, issue in enumerate(issues[:5], 1):
            print(f"\n  {i}. #{issue['number']}: {issue['title'][:50]}...")
            print(f"     Closed: {issue['closed_at']}")
            print(f"     Repo: {issue['repository']}")
            print(f"     URL: {issue['url']}")
    else:
        print(f"\nNo issues passed all filters:")
        print(f"  - Must be closed")
        print(f"  - Must be assigned to {test_user}")
        print(f"  - Must be from {GITHUB_ORG} organization repos")
        print(f"  - Must be closed in last 90 days")

    print(f"\n{'='*70}")
    print("✓ Detailed Test Complete!")
    print(f"{'='*70}")


if __name__ == '__main__':
    test_issues_with_details()
