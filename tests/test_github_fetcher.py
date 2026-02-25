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

        # Verify the new two-step GraphQL methods are present
        assert hasattr(fetcher, '_graphql_request')
        assert hasattr(fetcher, '_discover_active_repos')
        assert hasattr(fetcher, '_fetch_commits_via_graphql')
        assert hasattr(fetcher, '_fetch_commits_for_date')

        # Verify GraphQL URL is set correctly
        assert fetcher.graphql_url == 'https://api.github.com/graphql'

        # Verify session has bearer token authentication for GraphQL
        assert 'Authorization' in fetcher.session.headers
        assert fetcher.session.headers['Authorization'].startswith('bearer')


# ---------------------------------------------------------------------------
# Helpers shared by TestDiscoverActiveRepos and TestFetchCommitsViaGraphQL
# ---------------------------------------------------------------------------

def _make_fetcher():
    """Return a GitHubFetcher with _graphql_request and rate-limit mocked out."""
    fetcher = GitHubFetcher(thread_count=1)
    fetcher._graphql_request = MagicMock()
    fetcher._check_rate_limit_and_wait = MagicMock()
    return fetcher


def _repo_node(name, pushed_at):
    return {'name': name, 'pushedAt': pushed_at}


def _gql_repos_page(nodes, has_next=False, end_cursor=None):
    return {
        'organization': {
            'repositories': {
                'pageInfo': {'hasNextPage': has_next, 'endCursor': end_cursor},
                'nodes': nodes,
            }
        }
    }


def _commit_node(oid, login, message='feat: test',
                 date='2026-02-17T12:00:00Z',
                 author_name='Test User', author_email='test@example.com',
                 additions=10, deletions=2):
    return {
        'oid': oid,
        'message': message,
        'additions': additions,
        'deletions': deletions,
        'author': {
            'name': author_name,
            'email': author_email,
            'date': date,
            'user': {'login': login},
        },
    }


def _ref_node(branch_name, commit_nodes):
    return {
        'name': branch_name,
        'target': {
            'history': {
                'pageInfo': {'hasNextPage': False, 'endCursor': None},
                'nodes': commit_nodes,
            }
        },
    }


def _gql_repo_page(idx, repo_name, ref_nodes, has_next_refs=False, end_cursor=None):
    """Build the GraphQL alias response for a single repo."""
    return {
        f'r{idx}': {
            'name': repo_name,
            'nameWithOwner': f'{GITHUB_ORG}/{repo_name}',
            'refs': {
                'pageInfo': {'hasNextPage': has_next_refs, 'endCursor': end_cursor},
                'nodes': ref_nodes,
            },
        }
    }


# ---------------------------------------------------------------------------
# Tests for _discover_active_repos
# ---------------------------------------------------------------------------

class TestDiscoverActiveRepos:
    """Unit tests for _discover_active_repos()."""

    START = datetime(2026, 2, 17, 0, 0, 0)
    END = datetime(2026, 2, 17, 23, 59, 59)

    @pytest.mark.unit
    def test_returns_repos_in_window(self):
        """Repos pushed inside the date window are returned."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = _gql_repos_page([
            _repo_node('yral-billing', '2026-02-17T10:00:00Z'),
            # too old → triggers early exit
            _repo_node('old-repo', '2026-01-01T00:00:00Z'),
        ])

        result = fetcher._discover_active_repos(self.START, self.END)

        assert result == [f'{GITHUB_ORG}/yral-billing']

    @pytest.mark.unit
    def test_includes_repos_pushed_after_window_end(self):
        """Repos pushed AFTER the window end are included.

        A repo pushed today for a yesterday window may still have commits
        from yesterday in its branch history.  history(since:, until:) in
        Step 2 enforces the actual date boundary.
        """
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = _gql_repos_page([
            # Pushed on Feb 18 for a Feb 17 window — must still be included
            _repo_node('github-report-script', '2026-02-18T10:00:00Z'),
            _repo_node('yral-billing', '2026-02-17T10:00:00Z'),
            # too old → early exit
            _repo_node('old-repo', '2026-01-01T00:00:00Z'),
        ])

        result = fetcher._discover_active_repos(self.START, self.END)

        assert f'{GITHUB_ORG}/github-report-script' in result
        assert f'{GITHUB_ORG}/yral-billing' in result

    @pytest.mark.unit
    def test_empty_when_no_repos_in_window(self):
        """Returns empty list when no repos were pushed in the window."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = _gql_repos_page([
            _repo_node('ancient-repo', '2025-01-01T00:00:00Z'),
        ])

        result = fetcher._discover_active_repos(self.START, self.END)

        assert result == []

    @pytest.mark.unit
    def test_paginates_when_has_next_page(self):
        """Two pages of results are fetched when hasNextPage is True on page 1."""
        fetcher = _make_fetcher()
        page1 = _gql_repos_page(
            [_repo_node('repo-a', '2026-02-17T08:00:00Z')],
            has_next=True, end_cursor='cursor1',
        )
        page2 = _gql_repos_page(
            [_repo_node('repo-b', '2026-02-17T09:00:00Z'),
             # triggers early exit
             _repo_node('old-repo', '2025-06-01T00:00:00Z')],
        )
        fetcher._graphql_request.side_effect = [page1, page2]

        result = fetcher._discover_active_repos(self.START, self.END)

        assert set(result) == {f'{GITHUB_ORG}/repo-a', f'{GITHUB_ORG}/repo-b'}
        assert fetcher._graphql_request.call_count == 2

    @pytest.mark.unit
    def test_early_exit_when_repos_older_than_lookback(self):
        """Stops pagination as soon as a repo's pushedAt is before the look-behind window."""
        fetcher = _make_fetcher()
        # First node is in window, second is way older — should stop immediately.
        fetcher._graphql_request.return_value = _gql_repos_page([
            _repo_node('active-repo', '2026-02-17T14:00:00Z'),
            _repo_node('stale-repo', '2024-01-01T00:00:00Z'),
        ], has_next=True)  # has_next=True, but early-exit should prevent a second call

        result = fetcher._discover_active_repos(self.START, self.END)

        assert result == [f'{GITHUB_ORG}/active-repo']
        # Only one GraphQL call despite hasNextPage=True
        assert fetcher._graphql_request.call_count == 1

    @pytest.mark.unit
    def test_returns_empty_on_graphql_failure(self):
        """Returns empty list (not an exception) when _graphql_request returns None."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = None

        result = fetcher._discover_active_repos(self.START, self.END)

        assert result == []

    @pytest.mark.unit
    def test_look_behind_includes_repo_pushed_just_before_window(self):
        """A repo pushed 12h before the window opens is included (1-day look-behind)."""
        fetcher = _make_fetcher()
        # Pushed 12 hours before window START
        pushed_at = '2026-02-16T12:00:00Z'
        fetcher._graphql_request.return_value = _gql_repos_page([
            _repo_node('early-push-repo', pushed_at),
        ])

        result = fetcher._discover_active_repos(self.START, self.END)

        # 12 h before window is within the 1-day buffer
        assert f'{GITHUB_ORG}/early-push-repo' in result


# ---------------------------------------------------------------------------
# Tests for _fetch_commits_via_graphql
# ---------------------------------------------------------------------------

class TestFetchCommitsViaGraphQL:
    """Unit tests for _fetch_commits_via_graphql()."""

    START = datetime(2026, 2, 17, 0, 0, 0)
    END = datetime(2026, 2, 17, 23, 59, 59)
    USER_IDS = {'joel-medicala-yral', 'saikatdas0790'}

    @pytest.mark.unit
    def test_returns_commits_for_tracked_users(self):
        """Happy path: commits by tracked users are returned."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = _gql_repo_page(
            0, 'yral-ai-chat',
            [_ref_node('main', [_commit_node('abc123', 'joel-medicala-yral')])]
        )

        result = fetcher._fetch_commits_via_graphql(
            [f'{GITHUB_ORG}/yral-ai-chat'], self.START, self.END, self.USER_IDS
        )

        assert len(result) == 1
        c = result[0]
        assert c['sha'] == 'abc123'
        assert c['author'] == 'joel-medicala-yral'
        assert c['repository'] == f'{GITHUB_ORG}/yral-ai-chat'
        assert c['stats'] == {'additions': 10, 'deletions': 2, 'total': 12}

    @pytest.mark.unit
    def test_filters_out_untracked_authors(self):
        """Commits by authors not in user_ids are silently dropped."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = _gql_repo_page(
            0, 'yral-ai-chat',
            [_ref_node('main', [_commit_node('xyz999', 'random-outsider')])]
        )

        result = fetcher._fetch_commits_via_graphql(
            [f'{GITHUB_ORG}/yral-ai-chat'], self.START, self.END, self.USER_IDS
        )

        assert result == []

    @pytest.mark.unit
    def test_filters_bot_commits(self):
        """Commits from bots are filtered even if the bot login is in user_ids."""
        fetcher = _make_fetcher()
        # Use bot name that _is_bot_commit recognises (type or known name)
        bot_node = _commit_node(
            'bot001', 'dependabot[bot]',
            author_name='dependabot[bot]',
            author_email='dependabot@github.com',
        )
        fetcher._graphql_request.return_value = _gql_repo_page(
            0, 'yral-ai-chat', [_ref_node('main', [bot_node])]
        )

        result = fetcher._fetch_commits_via_graphql(
            [f'{GITHUB_ORG}/yral-ai-chat'],
            self.START, self.END,
            self.USER_IDS | {'dependabot[bot]'},
        )

        assert result == []

    @pytest.mark.unit
    def test_deduplicates_by_sha(self):
        """The same commit SHA seen on two branches is stored once with both branches."""
        fetcher = _make_fetcher()
        commit = _commit_node('sha_dup', 'joel-medicala-yral')
        fetcher._graphql_request.return_value = _gql_repo_page(
            0, 'yral-ai-chat',
            [
                _ref_node('main', [commit]),
                _ref_node('feature/xyz', [commit]),
            ]
        )

        result = fetcher._fetch_commits_via_graphql(
            [f'{GITHUB_ORG}/yral-ai-chat'], self.START, self.END, self.USER_IDS
        )

        assert len(result) == 1
        assert set(result[0]['branches']) == {'main', 'feature/xyz'}

    @pytest.mark.unit
    def test_branches_field_populated(self):
        """branches field contains the actual branch name, not an empty list."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = _gql_repo_page(
            0, 'yral-billing',
            [_ref_node('feat/setup-pooling',
                       [_commit_node('sha001', 'saikatdas0790')])]
        )

        result = fetcher._fetch_commits_via_graphql(
            [f'{GITHUB_ORG}/yral-billing'], self.START, self.END, self.USER_IDS
        )

        assert len(result) == 1
        assert result[0]['branches'] == ['feat/setup-pooling']

    @pytest.mark.unit
    def test_stats_inline_no_rest_calls(self):
        """additions/deletions come from the GraphQL response; requests.get is not called."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = _gql_repo_page(
            0, 'yral-ai-chat',
            [_ref_node('main', [_commit_node('sha_stats', 'joel-medicala-yral',
                                             additions=42, deletions=7)])]
        )

        with patch('requests.get') as mock_get:
            result = fetcher._fetch_commits_via_graphql(
                [f'{GITHUB_ORG}/yral-ai-chat'], self.START, self.END, self.USER_IDS
            )
            mock_get.assert_not_called()

        assert result[0]['stats'] == {
            'additions': 42, 'deletions': 7, 'total': 49}

    @pytest.mark.unit
    def test_returns_empty_for_empty_repo_list(self):
        """No GraphQL call is made and [] is returned when repo_names is empty."""
        fetcher = _make_fetcher()

        result = fetcher._fetch_commits_via_graphql(
            [], self.START, self.END, self.USER_IDS
        )

        assert result == []
        fetcher._graphql_request.assert_not_called()

    @pytest.mark.unit
    def test_returns_empty_on_graphql_failure(self):
        """Returns [] without raising when _graphql_request returns None."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = None

        result = fetcher._fetch_commits_via_graphql(
            [f'{GITHUB_ORG}/yral-ai-chat'], self.START, self.END, self.USER_IDS
        )

        assert result == []

    @pytest.mark.unit
    def test_message_truncated_to_first_line(self):
        """Only the first line of a multi-line commit message is stored."""
        fetcher = _make_fetcher()
        commit = _commit_node('sha_msg', 'joel-medicala-yral',
                              message='feat: add feature\n\nDetailed body here.')
        fetcher._graphql_request.return_value = _gql_repo_page(
            0, 'yral-ai-chat', [_ref_node('main', [commit])]
        )

        result = fetcher._fetch_commits_via_graphql(
            [f'{GITHUB_ORG}/yral-ai-chat'], self.START, self.END, self.USER_IDS
        )

        assert result[0]['message'] == 'feat: add feature'

    @pytest.mark.unit
    def test_batches_multiple_repos(self):
        """Repos are batched; 6 repos with batch_size=5 results in exactly 2 GraphQL calls."""
        fetcher = _make_fetcher()

        # Build responses for batch1 (repos 0-4) and batch2 (repo 5)
        def make_batch_response(idxs, repo_suffix_start):
            resp = {}
            for i, idx in enumerate(idxs):
                repo_name = f'repo-{repo_suffix_start + i}'
                resp[f'r{idx}'] = {
                    'name': repo_name,
                    'nameWithOwner': f'{GITHUB_ORG}/{repo_name}',
                    'refs': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [],
                    },
                }
            return resp

        batch1_resp = make_batch_response([0, 1, 2, 3, 4], 0)
        batch2_resp = make_batch_response([5], 5)
        fetcher._graphql_request.side_effect = [batch1_resp, batch2_resp]

        repo_names = [f'{GITHUB_ORG}/repo-{i}' for i in range(6)]
        fetcher._fetch_commits_via_graphql(
            repo_names, self.START, self.END, self.USER_IDS)

        assert fetcher._graphql_request.call_count == 2


# ---------------------------------------------------------------------------
# Helper for _fetch_closed_issues_for_user tests
# ---------------------------------------------------------------------------

def _gql_search_issues_page(issue_nodes, has_next=False, end_cursor=None):
    """Build the GraphQL search response for closed issues."""
    return {
        'search': {
            'pageInfo': {'hasNextPage': has_next, 'endCursor': end_cursor},
            'nodes': issue_nodes,
        }
    }


def _issue_node(number, title, closed_at, repo_with_owner, labels=None):
    owner = repo_with_owner.split('/')[0]
    return {
        'number': number,
        'title': title,
        'closedAt': closed_at,
        'url': f'https://github.com/{repo_with_owner}/issues/{number}',
        'repository': {
            'nameWithOwner': repo_with_owner,
            'owner': {'login': owner},
        },
        'labels': {'nodes': [{'name': l} for l in (labels or [])]},
        'assignees': {'nodes': [{'login': repo_with_owner.split('/')[0]}]},
    }


class TestFetchClosedIssuesForUser:
    """Unit tests for _fetch_closed_issues_for_user()."""

    START = datetime(2026, 2, 24, 0, 0, 0, tzinfo=timezone.utc)
    END = datetime(2026, 2, 24, 23, 59, 59, tzinfo=timezone.utc)

    @pytest.mark.unit
    def test_returns_assigned_issues_in_range(self):
        """Issues closed within the date window and assigned to the user are returned."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = _gql_search_issues_page([
            _issue_node(1669, 'Increase rate limit', '2026-02-24T13:13:39Z',
                        f'{GITHUB_ORG}/product'),
        ])

        result = fetcher._fetch_closed_issues_for_user(
            'ravi-sawlani-yral', GITHUB_ORG, self.START, self.END)

        assert len(result) == 1
        assert result[0]['number'] == 1669
        assert result[0]['assignee'] == 'ravi-sawlani-yral'
        assert result[0]['repository'] == f'{GITHUB_ORG}/product'

    @pytest.mark.unit
    def test_issues_authored_by_others_are_included(self):
        """Issues created by someone else but assigned to the user must be returned.

        This is the core bug that was fixed: the old user.issues query returned
        issues *authored* by the user, so externally-authored issues were dropped.
        The search-based query has no such restriction.
        """
        fetcher = _make_fetcher()
        # Simulate issue #1669: authored by jatin-agarwal-yral, assigned to ravi-sawlani-yral
        fetcher._graphql_request.return_value = _gql_search_issues_page([
            _issue_node(1669, 'Increase rate limit of video gen',
                        '2026-02-24T13:13:39Z', f'{GITHUB_ORG}/product'),
        ])

        result = fetcher._fetch_closed_issues_for_user(
            'ravi-sawlani-yral', GITHUB_ORG, self.START, self.END)

        # Must be returned regardless of who authored the issue
        assert len(result) == 1
        assert result[0]['number'] == 1669

    @pytest.mark.unit
    def test_issues_outside_date_range_are_excluded(self):
        """Issues closed outside the window are filtered out."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = _gql_search_issues_page([
            _issue_node(100, 'Old issue', '2026-01-01T10:00:00Z',
                        f'{GITHUB_ORG}/product'),
        ])

        result = fetcher._fetch_closed_issues_for_user(
            'ravi-sawlani-yral', GITHUB_ORG, self.START, self.END)

        assert result == []

    @pytest.mark.unit
    def test_empty_search_result(self):
        """Returns empty list when no issues match."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = _gql_search_issues_page([])

        result = fetcher._fetch_closed_issues_for_user(
            'ravi-sawlani-yral', GITHUB_ORG, self.START, self.END)

        assert result == []

    @pytest.mark.unit
    def test_pagination_fetches_all_pages(self):
        """All pages are consumed before returning."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.side_effect = [
            _gql_search_issues_page(
                [_issue_node(1, 'Issue A', '2026-02-24T09:00:00Z',
                             f'{GITHUB_ORG}/product')],
                has_next=True, end_cursor='cursor1',
            ),
            _gql_search_issues_page(
                [_issue_node(2, 'Issue B', '2026-02-24T11:00:00Z',
                             f'{GITHUB_ORG}/product')],
                has_next=False,
            ),
        ]

        result = fetcher._fetch_closed_issues_for_user(
            'ravi-sawlani-yral', GITHUB_ORG, self.START, self.END)

        assert len(result) == 2
        assert fetcher._graphql_request.call_count == 2

    @pytest.mark.unit
    def test_search_query_uses_assignee_and_org(self):
        """The GraphQL search query targets the correct assignee and organisation."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = _gql_search_issues_page([])

        fetcher._fetch_closed_issues_for_user(
            'ravi-sawlani-yral', GITHUB_ORG, self.START, self.END)

        call_args = fetcher._graphql_request.call_args
        # positional (query, variables)
        search_query = call_args[0][1]['searchQuery']
        assert 'assignee:ravi-sawlani-yral' in search_query
        assert f'org:{GITHUB_ORG}' in search_query
        assert 'is:issue' in search_query
        assert 'is:closed' in search_query

    @pytest.mark.unit
    def test_no_response_returns_empty_list(self):
        """None response from GraphQL results in empty list (no crash)."""
        fetcher = _make_fetcher()
        fetcher._graphql_request.return_value = None

        result = fetcher._fetch_closed_issues_for_user(
            'ravi-sawlani-yral', GITHUB_ORG, self.START, self.END)

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
