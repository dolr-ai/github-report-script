#!/usr/bin/env python3
"""
Debug script to test GraphQL issues query
"""
from src.github_fetcher import GitHubFetcher
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_graphql_query():
    """Test the GraphQL query directly"""
    fetcher = GitHubFetcher()

    # Simple query to test
    query = """
    query($username: String!) {
      user(login: $username) {
        login
        issues(first: 5, filterBy: {states: CLOSED}) {
          totalCount
          nodes {
            number
            title
            state
          }
        }
      }
    }
    """

    variables = {'username': 'saikatdas0790'}

    print("Testing GraphQL issues query...")
    print(f"Username: {variables['username']}")

    try:
        response = fetcher._graphql_request(query, variables)
        print("\nResponse received:")
        print(json.dumps(response, indent=2))

        if response and 'data' in response:
            user = response['data'].get('user')
            if user:
                print(f"\n✓ User found: {user.get('login')}")
                issues = user.get('issues', {})
                print(f"✓ Total closed issues: {issues.get('totalCount', 0)}")
                nodes = issues.get('nodes', [])
                print(f"✓ Sample issues returned: {len(nodes)}")
                for issue in nodes:
                    print(f"  - #{issue['number']}: {issue['title']}")
            else:
                print("\n✗ No user data in response")
        else:
            print("\n✗ No data in response")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_graphql_query()
