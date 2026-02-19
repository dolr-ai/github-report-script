"""
GitHub Fetcher Module
Fetches commit data from GitHub with concurrent threading and bot filtering.

Commit discovery strategy (two-step GraphQL):
  Step 1 – _discover_active_repos(): one GraphQL call that lists all org repos
            ordered by pushedAt and filters to those pushed in the date window.
  Step 2 – _fetch_commits_via_graphql(): batched GraphQL aliases — for each
            active repo, fetch all branches (refs) and for each branch, fetch
            commits in the date window.  additions/deletions are returned inline,
            so no follow-up REST calls are required.

Issue discovery stays as pure GraphQL via _fetch_closed_issues_for_user().
"""
import logging
import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set, Callable, Any, Optional, Tuple
from functools import wraps

from tqdm import tqdm

from src.config import GITHUB_TOKEN, GITHUB_ORG, KNOWN_BOTS, USER_IDS
from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)


def retry_with_exponential_backoff(max_retries: int = 5, base_delay: int = 60):
    """Decorator that retries a function with exponential backoff on rate limit errors

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (will be doubled each retry)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            retries = 0
            delay = base_delay
            max_delay = 300  # Cap at 5 minutes

            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)
                except requests.exceptions.HTTPError as e:
                    # Rate limit errors
                    if e.response and e.response.status_code in [403, 429]:
                        if retries >= max_retries:
                            logger.error(
                                f"Max retries ({max_retries}) reached for {func.__name__}. Giving up."
                            )
                            raise

                        current_delay = min(delay, max_delay)
                        logger.warning(
                            f"Rate limit hit in {func.__name__}. "
                            f"Retry {retries + 1}/{max_retries} after {current_delay}s"
                        )
                        time.sleep(current_delay)
                        delay *= 2  # Exponential backoff
                        retries += 1
                    else:
                        raise  # Re-raise non-rate-limit errors

            return func(*args, **kwargs)
        return wrapper
    return decorator


class GitHubFetcher:
    """Fetches commit data from GitHub with concurrent threading using GraphQL API"""

    def __init__(self, thread_count: int = 4):
        self.thread_count = thread_count
        self.rate_limit_lock = threading.Lock()
        self.cache_manager = CacheManager()
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'bearer {GITHUB_TOKEN}',
            'Content-Type': 'application/json',
            'User-Agent': 'github-report-script'
        })
        self.base_url = 'https://api.github.com'
        self.graphql_url = 'https://api.github.com/graphql'

    def _get_rate_limit_reset_time(self, resource_type: str = 'graphql') -> Optional[float]:
        """Get the reset time for a specific rate limit resource

        Args:
            resource_type: Type of resource ('graphql', 'core', 'search', etc.)

        Returns:
            Seconds until reset (including 2s buffer) or None if check fails
        """
        try:
            response = self.session.get(
                f'{self.base_url}/rate_limit', timeout=10)
            response.raise_for_status()
            rate_data = response.json()

            resource_limit = rate_data.get(
                'resources', {}).get(resource_type, {})
            remaining = resource_limit.get('remaining', 0)
            reset_timestamp = resource_limit.get('reset', 0)

            if reset_timestamp:
                reset_time = datetime.fromtimestamp(reset_timestamp)
                wait_seconds = (reset_time - datetime.now()).total_seconds()

                # Add 2 second buffer to ensure rate limit has reset
                if wait_seconds > 0:
                    logger.info(
                        f"{resource_type.upper()} rate limit: {remaining} remaining, "
                        f"resets at {reset_time.strftime('%H:%M:%S')} UTC"
                    )
                    return wait_seconds + 2

            return None
        except Exception as e:
            logger.warning(f"Could not check rate limit: {e}")
            return None

    def _check_rate_limit_and_wait(self, min_remaining: int = 500, resource_type: str = 'graphql') -> None:
        """Check GitHub API rate limit and wait if needed

        Args:
            min_remaining: Minimum remaining calls required to proceed
            resource_type: The rate-limit resource bucket to check.
                           Use 'graphql' for GraphQL API calls and 'search'
                           for GraphQL search queries (separate 30 req/min bucket).
        """
        try:
            response = self.session.get(
                f'{self.base_url}/rate_limit', timeout=10)
            response.raise_for_status()
            rate_data = response.json()

            resource_limit = rate_data.get(
                'resources', {}).get(resource_type, {})
            remaining = resource_limit.get('remaining', 0)
            reset_timestamp = resource_limit.get('reset', 0)

            if remaining < min_remaining:
                # Calculate wait time
                reset_time = datetime.fromtimestamp(reset_timestamp)
                wait_seconds = (reset_time - datetime.now()).total_seconds()

                if wait_seconds > 0:
                    logger.warning(
                        f"{resource_type} rate limit low ({remaining} remaining). "
                        f"Waiting {int(wait_seconds)}s until {reset_time.strftime('%H:%M:%S')}"
                    )
                    time.sleep(wait_seconds + 2)  # Add 2s buffer
                    logger.info("Rate limit reset complete. Resuming...")
        except Exception as e:
            logger.warning(f"Could not check rate limit: {e}. Proceeding...")

    def _graphql_request(self, query: str, variables: Optional[Dict] = None,
                         max_retries: int = 10) -> Optional[Dict]:
        """Make a GraphQL API request to GitHub with smart rate limit handling

        Args:
            query: GraphQL query string
            variables: Query variables
            max_retries: Maximum number of retry attempts for rate limits (default: 10)

        Returns:
            JSON response or None on error
        """
        retries = 0

        while retries <= max_retries:
            try:
                payload = {'query': query}
                if variables:
                    payload['variables'] = variables

                response = self.session.post(
                    self.graphql_url, json=payload, timeout=60)
                response.raise_for_status()
                result = response.json()

                if 'errors' in result:
                    # Check if it's a rate limit error
                    errors = result['errors']
                    is_rate_limit = any(
                        err.get('type') == 'RATE_LIMIT' or
                        err.get('code') == 'graphql_rate_limit'
                        for err in errors
                    )

                    if is_rate_limit and retries < max_retries:
                        retries += 1

                        # Get exact reset time from GitHub API
                        wait_seconds = self._get_rate_limit_reset_time(
                            'graphql')

                        if wait_seconds is not None and wait_seconds > 0:
                            logger.warning(
                                f"GraphQL rate limit hit. Retry {retries}/{max_retries} "
                                f"after waiting {int(wait_seconds)}s for rate limit reset"
                            )
                            time.sleep(wait_seconds)
                        else:
                            # Fallback to exponential backoff if rate limit check fails
                            # Cap at 5 minutes
                            fallback_delay = min(5 * (2 ** (retries - 1)), 300)
                            logger.warning(
                                f"GraphQL rate limit hit. Retry {retries}/{max_retries} "
                                f"after {fallback_delay}s (fallback delay)"
                            )
                            time.sleep(fallback_delay)
                        continue
                    else:
                        logger.warning(f"GraphQL errors: {result['errors']}")
                        return None

                return result.get('data')

            except requests.exceptions.RequestException as e:
                logger.warning(f"GraphQL request failed: {e}")
                return None

        logger.error(
            f"GraphQL request failed after {max_retries} retries due to rate limiting")
        return None

    def _fetch_closed_issues_for_user(
        self,
        username: str,
        org: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """Fetch closed issues assigned to user within date range from org repos

        Args:
            username: GitHub username
            org: GitHub organization
            start_date: Start date for filtering (timezone-naive, will be treated as UTC)
            end_date: End date for filtering (timezone-naive, will be treated as UTC)

        Returns:
            List of issue dicts with number, title, closed_at, url, repository, labels
        """
        issues = []
        has_next_page = True
        cursor = None

        # Make dates timezone-aware (UTC) if they aren't already
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        logger.debug(
            f"Fetching closed issues for {username} from {start_date.date()} to {end_date.date()}")

        try:
            while has_next_page:
                # GraphQL query for closed issues assigned to user
                query = """
                query($username: String!, $cursor: String) {
                  user(login: $username) {
                    issues(
                      first: 100
                      after: $cursor
                      filterBy: {states: CLOSED}
                      orderBy: {field: UPDATED_AT, direction: DESC}
                    ) {
                      pageInfo {
                        hasNextPage
                        endCursor
                      }
                      nodes {
                        number
                        title
                        closedAt
                        url
                        repository {
                          nameWithOwner
                          owner {
                            login
                          }
                        }
                        labels(first: 10) {
                          nodes {
                            name
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

                variables = {
                    'username': username,
                    'cursor': cursor
                }

                response = self._graphql_request(query, variables)
                if not response:
                    logger.warning(
                        f"No response from GraphQL for issues of {username}")
                    break

                user_data = response.get('user')
                if not user_data:
                    logger.debug(f"No user data found for {username}")
                    break

                issues_data = user_data.get('issues', {})
                nodes = issues_data.get('nodes', [])
                page_info = issues_data.get('pageInfo', {})

                for issue_node in nodes:
                    # Get closedAt date
                    closed_at_str = issue_node.get('closedAt')
                    if not closed_at_str:
                        continue

                    closed_at = datetime.fromisoformat(
                        closed_at_str.replace('Z', '+00:00'))

                    # Filter by date range (closedAt must be within our date range)
                    if not (start_date <= closed_at <= end_date):
                        continue

                    # Check if issue is from our organization
                    repo_data = issue_node.get('repository', {})
                    repo_owner = repo_data.get('owner', {}).get('login', '')
                    if repo_owner != org:
                        continue

                    # Check if user is actually assigned to this issue
                    assignees = issue_node.get(
                        'assignees', {}).get('nodes', [])
                    is_assigned = any(a.get('login') ==
                                      username for a in assignees)
                    if not is_assigned:
                        continue

                    # Extract issue data
                    repo_name = repo_data.get('nameWithOwner', '')
                    labels = [label['name'] for label in issue_node.get(
                        'labels', {}).get('nodes', [])]

                    issue_dict = {
                        'number': issue_node.get('number'),
                        'title': issue_node.get('title', ''),
                        'closed_at': closed_at_str,
                        'assignee': username,
                        'repository': repo_name,
                        'url': issue_node.get('url', ''),
                        'labels': labels
                    }

                    issues.append(issue_dict)

                # Check pagination
                has_next_page = page_info.get('hasNextPage', False)
                cursor = page_info.get('endCursor')

                # Stop if we've gone far enough back in time
                if nodes and not has_next_page:
                    break

        except Exception as e:
            logger.error(f"Error fetching issues for {username}: {e}")
            import traceback
            logger.error(traceback.format_exc())

        logger.info(
            f"Found {len(issues)} closed issues for {username} in date range")
        return issues

    def _is_bot_commit(self, commit_data: Dict) -> bool:
        """Check if a commit is from a bot

        Args:
            commit_data: Commit data from GitHub API

        Returns:
            True if commit is from a bot
        """
        try:
            # Check author type
            author = commit_data.get('author')
            if author and author.get('type') == 'Bot':
                return True

            # Fallback: Check commit author name/email against known bots
            commit_info = commit_data.get('commit', {})
            author_info = commit_info.get('author', {})
            author_name = author_info.get('name', '')
            author_email = author_info.get('email', '')

            # Check if name or email contains bot indicators
            for bot in KNOWN_BOTS:
                if bot.lower() in author_name.lower() or bot.lower() in author_email.lower():
                    return True

            return False
        except Exception:
            # If we can't determine, assume it's not a bot
            return False

    def _discover_active_repos(
        self,
        start_datetime: datetime,
        end_datetime: datetime,
    ) -> List[str]:
        """Return names of org repos that may have commits in the date window.

        A single GraphQL call fetches all org repos ordered by pushedAt DESC.
        A repo is included when its ``pushedAt`` is at or after the look-behind
        lower bound (start − 1 day), regardless of whether it is newer than
        ``end_datetime``.  A repo pushed *after* the window (e.g. today) is
        still included because it may contain commits from yesterday in its
        branch history — the ``history(since:, until:)`` call in Step 2 is
        what enforces the actual date filter.

        Early-exit fires only when repos are *older* than the look-behind
        lower bound (they can’t possibly contain commits in the window).

        Args:
            start_datetime: Start of the time window (UTC).
            end_datetime:   End of the time window (UTC).

        Returns:
            List of ``"owner/repo"``-style full repo name strings.
        """
        # 1-day buffer on the lower bound so repos pushed just before midnight
        # are not missed.
        lookback_str = (start_datetime - timedelta(days=1)
                        ).strftime('%Y-%m-%dT%H:%M:%SZ')

        active: List[str] = []
        cursor: Optional[str] = None

        while True:
            after_clause = f', after: "{cursor}"' if cursor else ''
            query = f"""
            {{
              rateLimit {{ remaining }}
              organization(login: "{GITHUB_ORG}") {{
                repositories(
                  first: 100
                  orderBy: {{field: PUSHED_AT, direction: DESC}}
                  {after_clause}
                ) {{
                  pageInfo {{ hasNextPage endCursor }}
                  nodes {{ name pushedAt }}
                }}
              }}
            }}
            """
            data = self._graphql_request(query)
            if not data:
                logger.warning(
                    "_discover_active_repos: empty GraphQL response")
                break

            repos = data.get('organization', {}).get('repositories', {})
            nodes = repos.get('nodes', [])
            page_info = repos.get('pageInfo', {})

            for node in nodes:
                pushed_at = node.get('pushedAt', '')
                if not pushed_at:
                    continue
                # Early-exit: repos older than look-behind can't have commits
                # in our window.
                if pushed_at < lookback_str:
                    return active
                # Include any repo pushed at or after the look-behind bound.
                # This deliberately includes repos pushed *after* end_datetime
                # (e.g. pushed today for a yesterday window) because their
                # branch history may still contain commits dated within the
                # window.  The history(since:, until:) filter in Step 2
                # enforces the actual date boundary.
                active.append(f"{GITHUB_ORG}/{node['name']}")

            if not page_info.get('hasNextPage'):
                break
            cursor = page_info.get('endCursor')

        logger.info(
            f"Active repos in window [{start_datetime.date()} → {end_datetime.date()}]: "
            f"{len(active)} — {[r.split('/')[-1] for r in active]}"
        )
        return active

    # ------------------------------------------------------------------
    # REPOS_PER_BATCH: how many repos to pack into a single batched
    # GraphQL query.  5 is safe; larger values save round-trips but
    # increase query complexity and risk hitting the GraphQL max-node cap.
    # ------------------------------------------------------------------
    _REPOS_PER_BATCH = 5

    def _fetch_commits_via_graphql(
        self,
        repo_names: List[str],
        start_datetime: datetime,
        end_datetime: datetime,
        user_ids: Set[str],
    ) -> List[Dict]:
        """Fetch commits across all branches of the given repos, filtered to user_ids.

        For each repo, fetches all refs (branches) ordered by most-recently
        committed first (``orderBy: TAG_COMMIT_DATE DESC``).  For each branch,
        uses ``history(since:, until:)`` — a real git filter with no search-index
        dependency — to retrieve commits inside the date window.  ``additions``
        and ``deletions`` are included inline, so no follow-up REST calls are
        required.

        Repos are batched (``_REPOS_PER_BATCH`` per GraphQL request) using
        aliases to minimise round-trips.  Commits are deduplicated by SHA across
        all branches and repos, and filtered client-side to only include authors
        present in ``user_ids``.

        Args:
            repo_names:     List of ``"owner/repo"`` full names to scan.
            start_datetime: Start of the time window (UTC).
            end_datetime:   End of the time window (UTC).
            user_ids:       Set of GitHub logins whose commits we keep.

        Returns:
            List of commit dicts matching the cache schema:
            ``{sha, author, repository, timestamp, message, stats, branches}``.
        """
        if not repo_names:
            return []

        since_str = start_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
        until_str = end_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')

        commits_by_sha: Dict[str, Dict] = {}

        # Split repos into batches
        batches = [
            repo_names[i: i + self._REPOS_PER_BATCH]
            for i in range(0, len(repo_names), self._REPOS_PER_BATCH)
        ]

        for batch in batches:
            # We may need to paginate branches (refs) for repos with many branches.
            # Track per-repo cursor state.
            repo_cursors: Dict[str, Optional[str]] = {r: None for r in batch}
            # repos that still have more branch pages
            repos_with_more: Set[str] = set(batch)

            while repos_with_more:
                # Build batched aliased query
                alias_blocks = []
                for idx, repo_full in enumerate(batch):
                    if repo_full not in repos_with_more:
                        # No more pages for this repo — emit a dummy alias that
                        # returns an empty refs list so alias indices stay stable.
                        # Simplest: just skip — we key by alias, not index.
                        continue
                    owner, repo = repo_full.split('/', 1)
                    cursor = repo_cursors[repo_full]
                    after_clause = f', after: "{cursor}"' if cursor else ''
                    alias = f"r{idx}"
                    alias_blocks.append(f"""
                      {alias}: repository(owner: "{owner}", name: "{repo}") {{
                        name
                        nameWithOwner
                        refs(
                          refPrefix: "refs/heads/"
                          first: 100
                          orderBy: {{field: TAG_COMMIT_DATE, direction: DESC}}
                          {after_clause}
                        ) {{
                          pageInfo {{ hasNextPage endCursor }}
                          nodes {{
                            name
                            target {{
                              ... on Commit {{
                                history(first: 100, since: "{since_str}", until: "{until_str}") {{
                                  pageInfo {{ hasNextPage endCursor }}
                                  nodes {{
                                    oid
                                    message
                                    additions
                                    deletions
                                    author {{
                                      name
                                      email
                                      date
                                      user {{ login }}
                                    }}
                                  }}
                                }}
                              }}
                            }}
                          }}
                        }}
                      }}
                    """)

                if not alias_blocks:
                    break

                query = "{\n" + "\n".join(alias_blocks) + "\n}"
                data = self._graphql_request(query)
                if not data:
                    logger.warning(
                        f"_fetch_commits_via_graphql: empty response for batch {[r.split('/')[-1] for r in batch]}"
                    )
                    break

                next_repos_with_more: Set[str] = set()

                for idx, repo_full in enumerate(batch):
                    alias = f"r{idx}"
                    repo_data = data.get(alias)
                    if not repo_data:
                        continue

                    repo_name_with_owner = repo_data.get(
                        'nameWithOwner', repo_full)
                    refs = repo_data.get('refs', {})
                    refs_page_info = refs.get('pageInfo', {})

                    for ref_node in refs.get('nodes', []):
                        branch_name = ref_node.get('name', '')
                        target = ref_node.get('target') or {}
                        history = target.get('history', {})

                        # Note: we only request first:100 for history — if a
                        # single branch has >100 commits in one day, we log a
                        # warning.  This is extremely unlikely in practice.
                        if history.get('pageInfo', {}).get('hasNextPage'):
                            logger.warning(
                                f"Branch {repo_full}/{branch_name} has >100 commits "
                                f"in window; some may be missed. Consider reducing batch size."
                            )

                        for commit_node in history.get('nodes', []):
                            sha = commit_node.get('oid', '')
                            if not sha:
                                continue

                            author_info = commit_node.get('author') or {}
                            user_info = author_info.get('user') or {}
                            author_login = user_info.get('login', '')
                            author_name = author_info.get('name', '')
                            author_email = author_info.get('email', '')

                            # Bot check
                            surrogate = {
                                'author': {'type': 'User', 'login': author_login},
                                'commit': {'author': {'name': author_name, 'email': author_email}},
                            }
                            if self._is_bot_commit(surrogate):
                                continue

                            # Author filter — only keep tracked users
                            if author_login not in user_ids:
                                continue

                            additions = commit_node.get('additions', 0) or 0
                            deletions = commit_node.get('deletions', 0) or 0

                            if sha in commits_by_sha:
                                # Same commit on multiple branches — append branch
                                if branch_name not in commits_by_sha[sha]['branches']:
                                    commits_by_sha[sha]['branches'].append(
                                        branch_name)
                            else:
                                commits_by_sha[sha] = {
                                    'sha': sha,
                                    'author': author_login,
                                    'repository': repo_name_with_owner,
                                    'timestamp': author_info.get('date', ''),
                                    'message': (commit_node.get('message') or '').split('\n')[0][:100],
                                    'stats': {
                                        'additions': additions,
                                        'deletions': deletions,
                                        'total': additions + deletions,
                                    },
                                    'branches': [branch_name],
                                }

                    # Track whether this repo needs another branch page
                    if refs_page_info.get('hasNextPage') and repo_full in repos_with_more:
                        next_repos_with_more.add(repo_full)
                        repo_cursors[repo_full] = refs_page_info.get(
                            'endCursor')

                repos_with_more = next_repos_with_more

        result = list(commits_by_sha.values())
        logger.debug(
            f"_fetch_commits_via_graphql: {len(result)} unique commits "
            f"from {len(repo_names)} repo(s)"
        )
        return result

    def _fetch_commits_for_date(self, date_str: str, start_datetime: datetime,
                                end_datetime: datetime, user_ids: Set[str]) -> Dict:
        """Fetch all commits and closed issues for a specific date.

        Commit discovery uses a two-step pure-GraphQL approach:
          1. _discover_active_repos() — one call to find repos pushed in window.
          2. _fetch_commits_via_graphql() — batched calls over refs→history to
             get every commit on every branch, with additions/deletions inline.

        This approach queries git data directly and never depends on GitHub's
        search index, so it cannot miss commits regardless of indexing delay.

        Args:
            date_str: Date in YYYY-MM-DD format.
            start_datetime: Start datetime for filtering (naive UTC).
            end_datetime: End datetime for filtering (naive UTC).
            user_ids: Set of GitHub logins to track.

        Returns:
            Dictionary with schema:
            ``{date, commits: [...], issues: [...], issue_count}``.
        """
        commits_data: List[Dict] = []

        try:
            logger.info(
                f"Fetching commits for {date_str} via two-step GraphQL "
                f"(repo discovery → branch history)"
            )

            # Step 1: which repos had pushes in this date window?
            active_repos = self._discover_active_repos(
                start_datetime, end_datetime)

            if active_repos:
                # Step 2: for each active repo, scan all branches for commits by our users
                commits_data = self._fetch_commits_via_graphql(
                    active_repos, start_datetime, end_datetime, user_ids
                )
            else:
                logger.info(
                    f"No repos pushed on {date_str} — skipping branch scan")

        except Exception as exc:
            logger.error(f"Error fetching commits for {date_str}: {exc}")
            import traceback
            logger.error(traceback.format_exc())

        unique_repos = len(set(c['repository'] for c in commits_data))
        unique_authors = len(set(c['author'] for c in commits_data))
        logger.info(
            f"Date {date_str}: {len(commits_data)} commits from "
            f"{unique_repos} repos, {unique_authors} authors"
        )

        # Fetch closed issues for each user (pure GraphQL — unchanged)
        issues_data: List[Dict] = []
        logger.info(f"Fetching closed issues for {len(user_ids)} user(s)")
        for username in user_ids:
            user_issues = self._fetch_closed_issues_for_user(
                username=username,
                org=GITHUB_ORG,
                start_date=start_datetime,
                end_date=end_datetime,
            )
            issues_data.extend(user_issues)

        logger.info(f"Date {date_str}: {len(issues_data)} total issues closed")

        return {
            'date': date_str,
            'commits': commits_data,
            'issues': issues_data,
            'issue_count': len(issues_data),
        }

    def fetch_commits(self, start_date: datetime, end_date: datetime,
                      user_ids: List[str], force_refresh: bool = False) -> Dict[str, Dict]:
        """Fetch commits for date range with concurrent threading

        Args:
            start_date: Start date
            end_date: End date
            user_ids: List of GitHub user IDs to track
            force_refresh: If True, ignore cache and re-fetch

        Returns:
            Dictionary mapping date strings to commit data
        """
        # Validate cache structure and clear if outdated
        if not force_refresh and not self.cache_manager.validate_cache_structure():
            logger.warning(
                "Cache structure is outdated. Clearing cache and forcing refresh..."
            )
            self.cache_manager.clear_all_cache()
            force_refresh = True

        user_ids_set = set(user_ids)
        results = {}

        logger.info(
            f"Fetching commits from {start_date.date()} to {end_date.date()}")
        logger.info(
            f"Tracking {len(user_ids)} users: {', '.join(user_ids[:3])}{'...' if len(user_ids) > 3 else ''}")
        logger.info(f"Using {self.thread_count} concurrent threads")

        # Generate list of dates to fetch
        current_date = start_date.date()
        end_date_only = end_date.date()
        dates_to_fetch = []

        while current_date <= end_date_only:
            date_str = current_date.isoformat()

            # Check cache unless force refresh
            if not force_refresh and self.cache_manager.cache_exists(date_str):
                cached_data = self.cache_manager.read_cache(date_str)
                if cached_data:
                    results[date_str] = cached_data
                    logger.debug(f"Using cached data for {date_str}")
                    current_date += timedelta(days=1)
                    continue

            dates_to_fetch.append(date_str)
            current_date += timedelta(days=1)

        if not dates_to_fetch:
            logger.info(
                "All dates found in cache. Use REFRESH mode to force re-fetch.")
            return results

        logger.info(f"Need to fetch {len(dates_to_fetch)} date(s)")

        # Check rate limit before starting work
        self._check_rate_limit_and_wait(min_remaining=500)

        # Fetch commits concurrently
        with ThreadPoolExecutor(max_workers=self.thread_count) as executor:
            future_to_date = {}

            for date_str in dates_to_fetch:
                # Create start and end datetime for this date
                date_obj = datetime.fromisoformat(date_str)
                start_dt = date_obj.replace(
                    hour=0, minute=0, second=0, microsecond=0)
                end_dt = date_obj.replace(
                    hour=23, minute=59, second=59, microsecond=999999)

                future = executor.submit(
                    self._fetch_commits_for_date,
                    date_str,
                    start_dt,
                    end_dt,
                    user_ids_set
                )
                future_to_date[future] = date_str

            # Process results as they complete
            with tqdm(total=len(dates_to_fetch), desc="Fetching commits") as pbar:
                for future in as_completed(future_to_date):
                    date_str = future_to_date[future]

                    try:
                        data = future.result()

                        # Only cache and store valid data (None indicates rate limit failure)
                        if data is not None:
                            self.cache_manager.write_cache(date_str, data)
                            results[date_str] = data
                            commit_count = len(data.get('commits', []))
                            pbar.set_postfix_str(
                                f"{date_str}: {commit_count} commits")
                        else:
                            logger.warning(
                                f"Skipping cache update for {date_str} - no valid data returned (likely rate limited)")
                            pbar.set_postfix_str(
                                f"{date_str}: FAILED")

                    except Exception as e:
                        logger.error(f"Error processing {date_str}: {e}")
                        pbar.set_postfix_str(f"{date_str}: ERROR")

                    pbar.update(1)

        # Update metadata
        self.cache_manager.update_metadata(
            (start_date.date().isoformat(), end_date.date().isoformat()))

        print(
            f"\nFetch complete. Total: {sum(len(d.get('commits', [])) for d in results.values())} commits")

        return results

    def get_rate_limit_status(self) -> Dict:
        """Get current rate limit status for all resource types

        Returns:
            Dictionary with rate limit info for all resources
        """
        try:
            response = self.session.get(
                f"{self.base_url}/rate_limit", timeout=10)
            if response.status_code != 200:
                return {'error': 'Could not fetch rate limit'}

            rate_data = response.json()
            resources = rate_data.get('resources', {})

            result = {}

            # Process each resource type
            for resource_name in ['core', 'graphql', 'search', 'code_search']:
                resource = resources.get(resource_name, {})
                if resource:
                    remaining = resource.get('remaining', 0)
                    limit = resource.get('limit', 0)
                    reset_timestamp = resource.get('reset', 0)

                    if reset_timestamp:
                        reset_time = datetime.fromtimestamp(reset_timestamp)
                        reset_str = reset_time.strftime(
                            '%Y-%m-%d %H:%M:%S UTC')
                        seconds_until = int(
                            (reset_time - datetime.now()).total_seconds())
                    else:
                        reset_str = 'Unknown'
                        seconds_until = 0

                    result[resource_name] = {
                        'remaining': remaining,
                        'limit': limit,
                        'reset': reset_str,
                        'seconds_until_reset': max(0, seconds_until)
                    }

            return result

        except Exception as e:
            return {
                'error': f'Could not fetch rate limit: {e}'
            }
