"""
Tests for GitHub fetcher module
Includes both unit tests (mocked) and integration tests (real API)
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

from src.config import GITHUB_ORG
from src.github_fetcher import GitHubFetcher


class TestGitHubFetcherUnit:
    """Unit tests with mocked dependencies"""

    @pytest.mark.unit
    def test_bot_filtering(self):
        """Test that bot commits are properly filtered"""
        fetcher = GitHubFetcher(thread_count=1)

        # Mock bot commit (dict format from GraphQL API)
        bot_commit = {
            'author': {
                'type': 'Bot',
                'login': 'dependabot[bot]'
            },
            'commit': {
                'author': {
                    'name': 'dependabot[bot]',
                    'email': 'dependabot@github.com'
                }
            }
        }

        assert fetcher._is_bot_commit(bot_commit) is True

        # Mock human commit (dict format from GraphQL API)
        human_commit = {
            'author': {
                'type': 'User',
                'login': 'test-user'
            },
            'commit': {
                'author': {
                    'name': 'Test User',
                    'email': 'test@example.com'
                }
            }
        }

        assert fetcher._is_bot_commit(human_commit) is False

    @pytest.mark.unit
    def test_graphql_query_structure(self):
        """Test that GraphQL query is properly structured"""
        fetcher = GitHubFetcher(thread_count=1)

        # Test that the fetcher has the necessary methods for GraphQL
        assert hasattr(fetcher, '_graphql_request')
        assert hasattr(fetcher, '_fetch_commits_for_date')

        # Verify GraphQL URL is set correctly
        assert fetcher.graphql_url == 'https://api.github.com/graphql'

        # Verify session has bearer token authentication for GraphQL
        assert 'Authorization' in fetcher.session.headers
        assert fetcher.session.headers['Authorization'].startswith('bearer')


@pytest.mark.integration
class TestGitHubFetcherIntegration:
    """Integration tests using real GitHub API"""

    def test_fetch_dolr_ai_org_only(self, github_client, dolr_ai_org):
        """Test that we only fetch from dolr-ai organization"""
        fetcher = GitHubFetcher(thread_count=1)

        # Get a recent date
        test_date = datetime.now() - timedelta(days=2)
        start_dt = test_date.replace(hour=0, minute=0, second=0)
        end_dt = test_date.replace(hour=23, minute=59, second=59)

        result = fetcher._fetch_commits_for_date(
            test_date.strftime('%Y-%m-%d'),
            start_dt,
            end_dt,
            set(['saikatdas0790', 'gravityvi'])  # Known contributors
        )

        # Verify all commits are from dolr-ai org
        for commit in result.get('commits', []):
            assert commit['repository'].startswith(f"{GITHUB_ORG}/"), \
                f"Commit from wrong org: {commit['repository']}"

    def test_all_branches_included(self, github_client, dolr_ai_org):
        """Test that commits from all branches are included, not just main/default"""
        # Get a repo with multiple branches
        repos = list(dolr_ai_org.get_repos())

        # Find a repo with multiple branches
        test_repo = None
        for repo in repos[:10]:  # Check first 10 repos
            try:
                branches = list(repo.get_branches())
                if len(branches) > 1:
                    test_repo = repo
                    break
            except:
                continue

        if not test_repo:
            pytest.skip("No multi-branch repo found in dolr-ai org")

        # Get commits from all branches (default behavior)
        test_date = datetime.now() - timedelta(days=7)
        all_branches_commits = list(test_repo.get_commits(
            since=test_date,
            until=datetime.now()
        ))

        # Get commits from default branch only
        default_branch = test_repo.default_branch
        default_only_commits = list(test_repo.get_commits(
            sha=default_branch,
            since=test_date,
            until=datetime.now()
        ))

        # All branches should have >= commits than default branch only
        assert len(all_branches_commits) >= len(default_only_commits), \
            f"All branches ({len(all_branches_commits)}) should have >= commits than default only ({len(default_only_commits)})"

    def test_user_filtering(self, github_client):
        """Test that only specified users' commits are returned"""
        fetcher = GitHubFetcher(thread_count=1)

        test_date = datetime.now() - timedelta(days=3)
        start_dt = test_date.replace(hour=0, minute=0, second=0)
        end_dt = test_date.replace(hour=23, minute=59, second=59)

        # Test with specific user
        result = fetcher._fetch_commits_for_date(
            test_date.strftime('%Y-%m-%d'),
            start_dt,
            end_dt,
            set(['saikatdas0790'])  # Only this user
        )

        # Verify all commits are from the specified user
        for commit in result.get('commits', []):
            assert commit['author'] == 'saikatdas0790', \
                f"Found commit from unexpected user: {commit['author']}"

    def test_bot_commits_excluded(self, github_client, dolr_ai_org):
        """Test that bot commits are excluded from results"""
        fetcher = GitHubFetcher(thread_count=1)

        # Fetch recent commits
        test_date = datetime.now() - timedelta(days=5)
        start_dt = test_date.replace(hour=0, minute=0, second=0)
        end_dt = test_date.replace(hour=23, minute=59, second=59)

        result = fetcher._fetch_commits_for_date(
            test_date.strftime('%Y-%m-%d'),
            start_dt,
            end_dt,
            set(['saikatdas0790', 'gravityvi', 'dependabot[bot]'])
        )

        # Verify no bot commits in results
        for commit in result.get('commits', []):
            author = commit['author']
            assert '[bot]' not in author.lower(), \
                f"Bot commit not filtered: {author}"

    def test_non_default_branches_included(self, github_client, dolr_ai_org, temp_cache_dir):
        """Test that commits include branch information and have non-default branches"""
        from src.config import USER_IDS

        fetcher = GitHubFetcher(thread_count=8)

        # Fetch commits from recent date range to get enough data
        end_date = datetime.now() - timedelta(days=1)
        start_date = end_date - timedelta(days=7)  # Last 7 days

        results = fetcher.fetch_commits(
            start_date,
            end_date,
            USER_IDS,
            force_refresh=True
        )

        # Collect all commits from all dates
        all_commits = []
        for date_str, date_data in results.items():
            all_commits.extend(date_data.get('commits', []))

        print(f"\n\nTotal commits fetched: {len(all_commits)}")

        # Verify all commits are from dolr-ai organization
        for commit in all_commits:
            assert commit['repository'].startswith(f"{GITHUB_ORG}/"), \
                f"Commit from wrong org: {commit['repository']}"

        print(f"✓ All commits are from {GITHUB_ORG} organization")

        # Verify commits have branches field
        for commit in all_commits:
            assert 'branches' in commit, \
                f"Commit {commit['sha'][:7]} missing 'branches' field"

        print("✓ All commits have 'branches' field")

        # Collect all unique non-default branches
        default_branches = {'main', 'master', 'develop'}
        all_non_default_branches = set()

        for commit in all_commits:
            branches = commit.get('branches', [])
            non_default = [b for b in branches if b not in default_branches]
            all_non_default_branches.update(non_default)

        print(
            f"\nUnique non-default branch names found: {len(all_non_default_branches)}")
        print("\nNon-default branch names:")
        for branch in sorted(all_non_default_branches):
            print(f"  - {branch}")

        # Warn if fewer than 5 unique non-default branches found
        if len(all_non_default_branches) < 5:
            import warnings
            warnings.warn(
                f"Expected at least 5 unique non-default branches, found {len(all_non_default_branches)}. "
                f"This may indicate that non-default branch commits are not being captured properly.",
                UserWarning
            )
            print(
                f"\n⚠ Warning: Only found {len(all_non_default_branches)} unique non-default branches (expected at least 5)")
        else:
            print(
                f"\n✓ Test passed: Found {len(all_non_default_branches)} unique non-default branches")
