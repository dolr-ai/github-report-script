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

        # Mock bot commit
        bot_commit = Mock()
        bot_commit.author = Mock()
        bot_commit.author.type = 'Bot'
        bot_commit.author.login = 'dependabot[bot]'

        assert fetcher._is_bot_commit(bot_commit) is True

        # Mock human commit
        human_commit = Mock()
        human_commit.author = Mock()
        human_commit.author.type = 'User'
        human_commit.author.login = 'test-user'
        human_commit.commit.author.name = 'Test User'
        human_commit.commit.author.email = 'test@example.com'

        assert fetcher._is_bot_commit(human_commit) is False

    @pytest.mark.unit
    def test_all_branches_default_behavior(self):
        """Test that get_commits is called without sha parameter (all branches)"""
        with patch('src.github_fetcher.Github') as mock_github:
            mock_repo = Mock()
            mock_repo.name = "test-repo"
            mock_repo.full_name = f"{GITHUB_ORG}/test-repo"
            mock_repo.get_commits.return_value = []

            mock_org = Mock()
            mock_org.get_repos.return_value = [mock_repo]

            mock_github.return_value.get_organization.return_value = mock_org

            fetcher = GitHubFetcher(thread_count=1)

            # Fetch for a date range
            start_dt = datetime(2026, 1, 1, 0, 0, 0)
            end_dt = datetime(2026, 1, 1, 23, 59, 59)

            result = fetcher._fetch_commits_for_date(
                "2026-01-01",
                start_dt,
                end_dt,
                set(['test-user'])
            )

            # Verify get_commits was called with since/until only (no sha)
            mock_repo.get_commits.assert_called_once()
            call_kwargs = mock_repo.get_commits.call_args[1]
            assert 'since' in call_kwargs
            assert 'until' in call_kwargs
            assert 'sha' not in call_kwargs  # No sha = all branches


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
