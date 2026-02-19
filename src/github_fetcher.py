"""
GitHub Fetcher Module
Fetches commit data from GitHub with concurrent threading and bot filtering
"""
import logging
import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set, Callable, Any, Optional
from collections import defaultdict
from functools import wraps

from tqdm import tqdm

from src.config import GITHUB_TOKEN, GITHUB_ORG, KNOWN_BOTS
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

    def _check_rate_limit_and_wait(self, min_remaining: int = 500) -> None:
        """Check GraphQL rate limit and wait if needed

        Args:
            min_remaining: Minimum remaining calls required to proceed
        """
        try:
            response = self.session.get(
                f'{self.base_url}/rate_limit', timeout=10)
            response.raise_for_status()
            rate_data = response.json()

            graphql_limit = rate_data.get('resources', {}).get('graphql', {})
            remaining = graphql_limit.get('remaining', 0)
            reset_timestamp = graphql_limit.get('reset', 0)

            if remaining < min_remaining:
                # Calculate wait time
                reset_time = datetime.fromtimestamp(reset_timestamp)
                wait_seconds = (reset_time - datetime.now()).total_seconds()

                if wait_seconds > 0:
                    logger.warning(
                        f"GraphQL rate limit low ({remaining} remaining). "
                        f"Waiting {int(wait_seconds)}s until {reset_time.strftime('%H:%M:%S')}"
                    )
                    time.sleep(wait_seconds + 5)  # Add 5s buffer
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

    def _api_request(self, endpoint: str, params: Optional[Dict] = None,
                     max_retries: int = 10) -> Optional[List]:
        """Make a direct REST API request to GitHub with smart rate limit handling

        Args:
            endpoint: API endpoint (e.g., '/repos/owner/repo/commits')
            params: Query parameters
            max_retries: Maximum number of retry attempts for rate limits (default: 10)

        Returns:
            JSON response (list or dict) or None on error
        """
        url = f"{self.base_url}{endpoint}"
        retries = 0

        while retries <= max_retries:
            try:
                # Update headers for REST API
                headers = self.session.headers.copy()
                headers['Authorization'] = f'token {GITHUB_TOKEN}'
                headers['Accept'] = 'application/vnd.github.v3+json'

                response = requests.get(
                    url, params=params, headers=headers, timeout=30)

                # Handle 202 Accepted (stats being computed) - return None to signal retry needed
                if response.status_code == 202:
                    logger.debug(
                        f"API returned 202 Accepted for {endpoint} (stats being computed)")
                    return None

                response.raise_for_status()
                result = response.json()
                logger.debug(
                    f"API request to {endpoint}: {len(result) if isinstance(result, list) else 'dict'} items")
                return result

            except requests.exceptions.HTTPError as e:
                # Check for rate limit errors (403 or 429 status codes)
                if e.response and e.response.status_code in [403, 429]:
                    if retries < max_retries:
                        retries += 1

                        # Get exact reset time from GitHub API
                        wait_seconds = self._get_rate_limit_reset_time('core')

                        if wait_seconds is not None and wait_seconds > 0:
                            logger.warning(
                                f"REST API rate limit hit for {endpoint}. "
                                f"Retry {retries}/{max_retries} after waiting {int(wait_seconds)}s for rate limit reset"
                            )
                            time.sleep(wait_seconds)
                        else:
                            # Fallback to exponential backoff if rate limit check fails
                            # Cap at 5 minutes
                            fallback_delay = min(5 * (2 ** (retries - 1)), 300)
                            logger.warning(
                                f"REST API rate limit hit for {endpoint}. "
                                f"Retry {retries}/{max_retries} after {fallback_delay}s (fallback delay)"
                            )
                            time.sleep(fallback_delay)
                        continue
                    else:
                        logger.error(
                            f"REST API request failed after {max_retries} retries due to rate limiting: {endpoint}")
                        return None
                else:
                    logger.warning(f"API request failed for {endpoint}: {e}")
                    return None

            except requests.exceptions.RequestException as e:
                logger.warning(f"API request failed for {endpoint}: {e}")
                return None

        return None

    def _check_rate_limit(self):
        """Check GitHub API rate limit and wait if necessary"""
        with self.rate_limit_lock:
            try:
                response = self.session.get(
                    f"{self.base_url}/rate_limit", timeout=10)
                if response.status_code != 200:
                    return

                rate_data = response.json()
                remaining = rate_data['resources']['core']['remaining']
                reset_time = datetime.fromtimestamp(
                    rate_data['resources']['core']['reset'])

                if remaining < 100:
                    wait_seconds = (
                        reset_time - datetime.utcnow()).total_seconds() + 10

                    if wait_seconds > 0:
                        logger.warning(
                            f"Rate limit low ({remaining} remaining). Waiting {wait_seconds:.0f} seconds...")
                        time.sleep(wait_seconds)
                else:
                    logger.debug(f"Rate limit: {remaining} requests remaining")
            except Exception as e:
                # If rate limit check fails, log but continue
                logger.warning(f"Could not check rate limit: {e}")

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

    def _fetch_commits_for_user_via_search(self, username: str, date_str: str,
                                           start_datetime: datetime,
                                           end_datetime: datetime) -> List[Dict]:
        """Fetch all commits by a user in the org for a date using GraphQL commit search.

        Uses GitHub's ``search(type: COMMIT)`` API which queries across ALL branches
        and ALL repos in the org in a single paginated query per user.  This avoids
        the 300-event hard cap of the Events API and the N×M (repos × branches) cost
        of the old contributionsCollection approach.

        Search rate limit is a separate bucket from the core GraphQL limit
        (30 requests / minute).  The existing ``_check_rate_limit_and_wait`` helper
        accepts a ``resource_type`` argument and is reused here with ``'search'``.

        Args:
            username: GitHub login to search commits for.
            date_str: ISO date string (YYYY-MM-DD) used for logging only.
            start_datetime: Start of the time window (naive UTC assumed).
            end_datetime: End of the time window (naive UTC assumed).

        Returns:
            List of commit dicts in the cache schema:
            ``{sha, author, repository, timestamp, message, stats, branches}``.
            ``branches`` is always ``[]`` — the search API does not expose branch info
            but the field is kept for cache-schema compatibility.
        """
        search_query_template = (
            'author:{username} org:{org} committer-date:{start}..{end}'
        )
        search_query_str = search_query_template.format(
            username=username,
            org=GITHUB_ORG,
            start=start_datetime.strftime('%Y-%m-%dT%H:%M:%SZ'),
            end=end_datetime.strftime('%Y-%m-%dT%H:%M:%SZ'),
        )

        graphql_query = """
        query($searchQuery: String!, $cursor: String) {
          search(query: $searchQuery, type: COMMIT, first: 100, after: $cursor) {
            nodes {
              ... on Commit {
                oid
                message
                committedDate
                additions
                deletions
                author {
                  name
                  email
                  user {
                    login
                  }
                }
                repository {
                  nameWithOwner
                }
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """

        commits: List[Dict] = []
        seen_shas: Set[str] = set()
        cursor: Optional[str] = None
        page_num = 0

        while True:
            # Respect the search rate-limit bucket before each request
            self._check_rate_limit_and_wait(
                min_remaining=5, resource_type='search')

            variables = {'searchQuery': search_query_str, 'cursor': cursor}
            data = self._graphql_request(graphql_query, variables)

            if not data or 'search' not in data:
                logger.debug(
                    f"No search data returned for {username} on {date_str} (page {page_num})"
                )
                break

            search = data['search']
            nodes = search.get('nodes', [])
            page_info = search.get('pageInfo', {})
            page_num += 1

            for node in nodes:
                try:
                    sha = node.get('oid', '')
                    if not sha or sha in seen_shas:
                        continue

                    # Filter to target org only (search can occasionally return
                    # results from forks in other orgs)
                    repo_name = node.get('repository', {}).get(
                        'nameWithOwner', '')
                    if not repo_name.startswith(f"{GITHUB_ORG}/"):
                        continue

                    # Bot filtering — build a surrogate commit_data dict that
                    # matches the shape _is_bot_commit() expects
                    author_node = node.get('author') or {}
                    author_user = author_node.get('user') or {}
                    author_login = author_user.get('login', '')
                    author_name = author_node.get('name', '')
                    author_email = author_node.get('email', '')

                    surrogate = {
                        'author': {'type': 'User', 'login': author_login},
                        'commit': {
                            'author': {
                                'name': author_name,
                                'email': author_email,
                            }
                        },
                    }
                    if self._is_bot_commit(surrogate):
                        continue

                    # The search is already scoped to the author login, but
                    # double-check in case co-authored commits slip through.
                    if author_login and author_login.lower() != username.lower():
                        continue

                    additions = node.get('additions', 0) or 0
                    deletions = node.get('deletions', 0) or 0

                    commit_entry = {
                        'sha': sha,
                        'author': author_login or username,
                        'repository': repo_name,
                        'timestamp': node.get('committedDate', ''),
                        'message': (node.get('message') or '').split('\n')[0][:100],
                        'stats': {
                            'additions': additions,
                            'deletions': deletions,
                            'total': additions + deletions,
                        },
                        # Search API does not return branch info; kept for schema
                        # compatibility so downstream code does not break.
                        'branches': [],
                    }

                    seen_shas.add(sha)
                    commits.append(commit_entry)

                except Exception as exc:
                    logger.debug(
                        f"Skipped search result node for {username}: {exc}")
                    continue

            if not page_info.get('hasNextPage'):
                break

            cursor = page_info.get('endCursor')

        logger.debug(
            f"User {username} on {date_str}: {len(commits)} commits via search "
            f"({page_num} page(s))"
        )
        return commits

    def _fetch_commits_for_date(self, date_str: str, start_datetime: datetime,
                                end_datetime: datetime, user_ids: Set[str]) -> Dict:
        """Fetch all commits and closed issues for a specific date.

        Commit discovery uses the GitHub GraphQL commit search API
        (``search(type: COMMIT)``) which covers every branch and every repo in the
        org in a single paginated query per user — no repo pre-discovery step, no
        Events API, no 300-event cap.

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
        commits_by_sha: Dict[str, Dict] = {}

        try:
            logger.debug(
                f"Fetching commits for {date_str} from {len(user_ids)} users "
                f"via GraphQL commit search"
            )

            for username in user_ids:
                user_commits = self._fetch_commits_for_user_via_search(
                    username, date_str, start_datetime, end_datetime
                )

                for commit in user_commits:
                    sha = commit['sha']
                    if sha not in commits_by_sha:
                        commits_by_sha[sha] = commit
                        commits_data.append(commit)
                    # If the same SHA was already added (e.g. two users share a
                    # co-authored commit, which is rare), keep the first entry.

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
