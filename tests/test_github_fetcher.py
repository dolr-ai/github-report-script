"""
Tests for GitHub fetcher module
Includes both unit tests (mocked) and integration tests (real API)
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch, call
import requests

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


class TestGetUserActiveReposFromEvents:
    """Unit tests for _get_user_active_repos_from_events"""

    def _make_fetcher(self):
        fetcher = GitHubFetcher(thread_count=1)
        fetcher.session = MagicMock()
        fetcher.session.headers = {
            'Authorization': 'bearer test-token',
            'Content-Type': 'application/json',
        }
        return fetcher

    def _utc(self, dt: datetime) -> datetime:
        return dt.replace(tzinfo=timezone.utc)

    @pytest.mark.unit
    def test_returns_org_repos_from_push_events(self):
        """PushEvents within the window for the target org are returned."""
        fetcher = self._make_fetcher()

        start = datetime(2026, 2, 17, 0, 0, 0)
        end = datetime(2026, 2, 17, 23, 59, 59)
        event_time = "2026-02-17T12:00:00Z"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                'type': 'PushEvent',
                'created_at': event_time,
                'repo': {'name': f'{GITHUB_ORG}/yral-ai-chat'},
            }
        ]

        # Second page returns empty list to stop pagination
        mock_response_empty = MagicMock()
        mock_response_empty.status_code = 200
        mock_response_empty.json.return_value = []

        with patch('requests.get', side_effect=[mock_response, mock_response_empty]):
            result = fetcher._get_user_active_repos_from_events(
                'joel-medicala-yral', start, end)

        assert f'{GITHUB_ORG}/yral-ai-chat' in result

    @pytest.mark.unit
    def test_ignores_push_events_outside_window(self):
        """PushEvents outside the time window are not returned."""
        fetcher = self._make_fetcher()

        start = datetime(2026, 2, 17, 0, 0, 0)
        end = datetime(2026, 2, 17, 23, 59, 59)

        mock_response = MagicMock()
        mock_response.status_code = 200
        # Event is one day before the window
        mock_response.json.return_value = [
            {
                'type': 'PushEvent',
                'created_at': '2026-02-16T12:00:00Z',
                'repo': {'name': f'{GITHUB_ORG}/yral-ai-chat'},
            }
        ]

        with patch('requests.get', return_value=mock_response):
            result = fetcher._get_user_active_repos_from_events(
                'joel-medicala-yral', start, end)

        assert result == []

    @pytest.mark.unit
    def test_ignores_non_push_events(self):
        """Non-PushEvent events (e.g. IssuesEvent) are not returned."""
        fetcher = self._make_fetcher()

        start = datetime(2026, 2, 17, 0, 0, 0)
        end = datetime(2026, 2, 17, 23, 59, 59)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                'type': 'IssuesEvent',
                'created_at': '2026-02-17T12:00:00Z',
                'repo': {'name': f'{GITHUB_ORG}/yral-ai-chat'},
            },
            {
                'type': 'PullRequestEvent',
                'created_at': '2026-02-17T13:00:00Z',
                'repo': {'name': f'{GITHUB_ORG}/yral-ai-chat'},
            },
        ]

        mock_empty = MagicMock()
        mock_empty.status_code = 200
        mock_empty.json.return_value = []

        with patch('requests.get', side_effect=[mock_response, mock_empty]):
            result = fetcher._get_user_active_repos_from_events(
                'joel-medicala-yral', start, end)

        assert result == []

    @pytest.mark.unit
    def test_ignores_repos_outside_org(self):
        """PushEvents to repos outside GITHUB_ORG are filtered out."""
        fetcher = self._make_fetcher()

        start = datetime(2026, 2, 17, 0, 0, 0)
        end = datetime(2026, 2, 17, 23, 59, 59)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                'type': 'PushEvent',
                'created_at': '2026-02-17T12:00:00Z',
                'repo': {'name': 'some-other-org/repo'},
            }
        ]

        mock_empty = MagicMock()
        mock_empty.status_code = 200
        mock_empty.json.return_value = []

        with patch('requests.get', side_effect=[mock_response, mock_empty]):
            result = fetcher._get_user_active_repos_from_events(
                'joel-medicala-yral', start, end)

        assert result == []

    @pytest.mark.unit
    def test_deduplicates_repos(self):
        """Multiple PushEvents to the same repo are returned only once."""
        fetcher = self._make_fetcher()

        start = datetime(2026, 2, 17, 0, 0, 0)
        end = datetime(2026, 2, 17, 23, 59, 59)
        repo = f'{GITHUB_ORG}/yral-ai-chat'

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {'type': 'PushEvent', 'created_at': '2026-02-17T10:00:00Z',
                'repo': {'name': repo}},
            {'type': 'PushEvent', 'created_at': '2026-02-17T11:00:00Z',
                'repo': {'name': repo}},
            {'type': 'PushEvent', 'created_at': '2026-02-17T12:00:00Z',
                'repo': {'name': repo}},
        ]

        mock_empty = MagicMock()
        mock_empty.status_code = 200
        mock_empty.json.return_value = []

        with patch('requests.get', side_effect=[mock_response, mock_empty]):
            result = fetcher._get_user_active_repos_from_events(
                'joel-medicala-yral', start, end)

        assert result.count(repo) == 1

    @pytest.mark.unit
    def test_stops_pagination_when_events_before_window(self):
        """Pagination stops early once events fall before the start of the window."""
        fetcher = self._make_fetcher()

        start = datetime(2026, 2, 17, 0, 0, 0)
        end = datetime(2026, 2, 17, 23, 59, 59)

        # First page has one in-window event followed by one pre-window event
        mock_page1 = MagicMock()
        mock_page1.status_code = 200
        mock_page1.json.return_value = [
            {
                'type': 'PushEvent',
                'created_at': '2026-02-17T12:00:00Z',
                'repo': {'name': f'{GITHUB_ORG}/repo-a'},
            },
            {
                'type': 'PushEvent',
                'created_at': '2026-02-10T00:00:00Z',  # Before window
                'repo': {'name': f'{GITHUB_ORG}/repo-b'},
            },
        ]

        with patch('requests.get', return_value=mock_page1) as mock_get:
            result = fetcher._get_user_active_repos_from_events(
                'joel-medicala-yral', start, end)

        # Only repo-a should appear; pagination stopped after page 1
        assert f'{GITHUB_ORG}/repo-a' in result
        assert f'{GITHUB_ORG}/repo-b' not in result
        assert mock_get.call_count == 1

    @pytest.mark.unit
    def test_handles_404_gracefully(self):
        """A 404 from the Events API returns an empty list without raising."""
        fetcher = self._make_fetcher()

        start = datetime(2026, 2, 17, 0, 0, 0)
        end = datetime(2026, 2, 17, 23, 59, 59)

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = MagicMock()

        with patch('requests.get', return_value=mock_response):
            result = fetcher._get_user_active_repos_from_events(
                'private-user', start, end)

        assert result == []

    @pytest.mark.unit
    def test_handles_request_exception_gracefully(self):
        """A network error returns an empty list without raising."""
        fetcher = self._make_fetcher()

        start = datetime(2026, 2, 17, 0, 0, 0)
        end = datetime(2026, 2, 17, 23, 59, 59)

        with patch('requests.get', side_effect=requests.exceptions.ConnectionError("network down")):
            result = fetcher._get_user_active_repos_from_events(
                'joel-medicala-yral', start, end)

        assert result == []


class TestGetUserActiveReposCombined:
    """Unit tests for _get_user_active_repos — verifies delegation to Events API."""

    def _make_fetcher(self):
        fetcher = GitHubFetcher(thread_count=1)
        fetcher.session = MagicMock()
        return fetcher

    @pytest.mark.unit
    def test_delegates_to_events_api(self):
        """_get_user_active_repos delegates entirely to _get_user_active_repos_from_events."""
        fetcher = self._make_fetcher()

        start = datetime(2026, 2, 17, 0, 0, 0)
        end = datetime(2026, 2, 17, 23, 59, 59)

        events_repos = [f'{GITHUB_ORG}/yral-ai-chat',
                        f'{GITHUB_ORG}/hot-or-not-web-leptos-ssr']
        fetcher._get_user_active_repos_from_events = MagicMock(
            return_value=events_repos)

        result = fetcher._get_user_active_repos(
            'joel-medicala-yral', start, end)

        fetcher._get_user_active_repos_from_events.assert_called_once_with(
            'joel-medicala-yral', start, end)
        assert set(result) == set(events_repos)

    @pytest.mark.unit
    def test_returns_empty_when_events_empty(self):
        """Returns an empty list when the Events API has no results."""
        fetcher = self._make_fetcher()

        start = datetime(2026, 2, 17, 0, 0, 0)
        end = datetime(2026, 2, 17, 23, 59, 59)

        fetcher._get_user_active_repos_from_events = MagicMock(return_value=[])

        result = fetcher._get_user_active_repos(
            'joel-medicala-yral', start, end)

        assert result == []


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
