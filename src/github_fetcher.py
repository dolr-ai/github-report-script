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

    @retry_with_exponential_backoff(max_retries=5, base_delay=60)
    def _fetch_commit_branches(self, repo_full_name: str, commit_sha: str) -> List[str]:
        """Fetch list of branch names containing the given commit

        Uses GitHub REST API endpoint: /repos/{owner}/{repo}/commits/{sha}/branches-where-head

        Args:
            repo_full_name: Full repository name (e.g., 'dolr-ai/repo-name')
            commit_sha: Commit SHA to look up

        Returns:
            List of branch names containing this commit
        """
        try:
            endpoint = f"/repos/{repo_full_name}/commits/{commit_sha}/branches-where-head"
            data = self._api_request(endpoint)

            if data is None:
                return []

            # Extract branch names from response
            branch_names = [branch['name'] for branch in data]
            return branch_names

        except Exception as e:
            logger.debug(f"Error fetching branches for {commit_sha[:7]}: {e}")
            return []

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

    def _get_week_start_date(self, date: datetime) -> str:
        """Get the start date (Sunday) of the week containing the given date

        GitHub's contributor stats API groups data by week starting on Sunday.

        Args:
            date: The date to get the week start for

        Returns:
            ISO format date string (YYYY-MM-DD) of the Sunday starting that week
        """
        # Get the day of week (0=Monday, 6=Sunday)
        weekday = date.weekday()
        # Calculate days back to Sunday (Sunday is weekday 6)
        days_to_sunday = (weekday + 1) % 7
        week_start = date - timedelta(days=days_to_sunday)
        return week_start.date().isoformat()

    def _has_contributor_stats_for_week(self, date_str: str, username: str) -> bool:
        """Check if we already have contributor stats for the week containing this date

        Args:
            date_str: Date string in YYYY-MM-DD format
            username: GitHub username

        Returns:
            True if we have stats for this week cached
        """
        try:
            cached_data = self.cache_manager.read_cache(date_str)
            if not cached_data:
                return False

            contributor_stats = cached_data.get('contributor_stats', {})
            user_stats = contributor_stats.get(username, {})

            # If we have any stats for this user, it means we already fetched the weekly data
            # GitHub stats API returns weekly data, so if we have it once, we have the whole week
            return len(user_stats) > 0
        except Exception as e:
            logger.debug(f"Error checking cached stats for {date_str}: {e}")
            return False

    @retry_with_exponential_backoff(max_retries=5, base_delay=60)
    def _fetch_contributor_stats(self, repo_full_name: str, username: str,
                                 start_date: datetime, end_date: datetime,
                                 max_retries: int = 10) -> Dict:
        """Fetch contributor statistics from GitHub's stats API

        This API provides the authoritative commit counts and LOC that match
        what GitHub shows in the contributors graph. It aggregates by week.

        NOTE: This API can return 202 Accepted when stats need to be computed.
        By default, we retry with exponential backoff. Set max_retries=1 to skip retries.

        Args:
            repo_full_name: Full repository name (e.g., 'dolr-ai/yral-mobile')
            username: GitHub username
            start_date: Start date for filtering
            end_date: End date for filtering
            max_retries: Maximum number of retry attempts (default: 10, use 1 for no retries)

        Returns:
            Dictionary with stats by date: {
                'date': {'commits': X, 'additions': Y, 'deletions': Z}
            }
        """
        try:
            endpoint = f"/repos/{repo_full_name}/stats/contributors"

            # Try up to max_retries times if we get 202 (stats being computed)
            # Use exponential backoff: 5s, 10s, 15s, 20s, 30s, 40s, 50s, 60s, 90s, 120s
            for attempt in range(max_retries):
                data = self._api_request(endpoint)

                # _api_request returns None or empty list for 202
                if data is None or (isinstance(data, list) and len(data) == 0):
                    if attempt < max_retries - 1:
                        # Calculate backoff delay
                        if attempt < 4:
                            delay = 5 + (attempt * 5)  # 5, 10, 15, 20
                        elif attempt < 7:
                            delay = 30 + ((attempt - 4) * 10)  # 30, 40, 50
                        else:
                            delay = 60 + ((attempt - 7) * 30)  # 60, 90, 120

                        logger.info(
                            f"Stats API returned 202 for {repo_full_name}, waiting {delay}s (attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(delay)
                        continue
                    else:
                        logger.debug(
                            f"Stats API still computing for {repo_full_name} after {max_retries} attempts, skipping"
                        )
                        return {}

                # We got data, process it
                break

            if not data:
                logger.debug(
                    f"No contributor stats found for {repo_full_name}")
                return {}

            # Find the user's contribution data
            user_data = None
            for contributor in data:
                author = contributor.get('author', {})
                if author and author.get('login') == username:
                    user_data = contributor
                    break

            if not user_data:
                logger.debug(
                    f"User {username} not found in contributor stats for {repo_full_name}")
                return {}

            # Extract weekly stats and convert to daily
            weeks = user_data.get('weeks', [])
            start_timestamp = int(start_date.timestamp())
            end_timestamp = int(end_date.timestamp())

            stats_by_date = {}

            for week in weeks:
                week_timestamp = week.get('w', 0)

                # Skip weeks outside our date range
                if week_timestamp < start_timestamp or week_timestamp > end_timestamp:
                    continue

                commits = week.get('c', 0)
                additions = week.get('a', 0)
                deletions = week.get('d', 0)

                if commits > 0:
                    # Convert timestamp to date
                    week_date = datetime.fromtimestamp(week_timestamp).date()
                    date_str = week_date.isoformat()

                    stats_by_date[date_str] = {
                        'commits': commits,
                        'additions': additions,
                        'deletions': deletions,
                        'total': additions + deletions
                    }

            logger.debug(
                f"Fetched contributor stats for {username} in {repo_full_name}: "
                f"{len(stats_by_date)} weeks with activity"
            )

            return stats_by_date

        except Exception as e:
            logger.debug(
                f"Error fetching contributor stats for {username} in {repo_full_name}: {e}")
            return {}

    def _get_user_active_repos(self, username: str, start_datetime: datetime,
                               end_datetime: datetime) -> List[str]:
        """Get list of repos where user has contributions in the date range

        Uses contributionsCollection to identify which repos the user has worked on,
        so we only fetch branches from relevant repos instead of all org repos.

        Args:
            username: GitHub username
            start_datetime: Start datetime for filtering
            end_datetime: End datetime for filtering

        Returns:
            List of repository full names (owner/repo) where user has commits
        """
        query = """
        query($username: String!, $from: DateTime!, $to: DateTime!) {
          user(login: $username) {
            contributionsCollection(from: $from, to: $to) {
              commitContributionsByRepository {
                repository {
                  nameWithOwner
                }
              }
            }
          }
        }
        """

        variables = {
            'username': username,
            'from': start_datetime.isoformat() + 'Z',
            'to': end_datetime.isoformat() + 'Z'
        }

        data = self._graphql_request(query, variables)

        if not data or 'user' not in data or not data['user']:
            logger.debug(f"No contribution data found for user {username}")
            return []

        contributions_collection = data['user'].get(
            'contributionsCollection', {})
        commit_contributions = contributions_collection.get(
            'commitContributionsByRepository', [])

        # Extract repo names and filter to our organization
        active_repos = []
        for repo_contrib in commit_contributions:
            repo_name = repo_contrib['repository']['nameWithOwner']
            if repo_name.startswith(f"{GITHUB_ORG}/"):
                active_repos.append(repo_name)

        logger.debug(f"User {username}: Active in {len(active_repos)} repos")
        return active_repos

    def _fetch_commits_for_date(self, date_str: str, start_datetime: datetime,
                                end_datetime: datetime, user_ids: Set[str]) -> Dict:
        """Fetch commits for a specific date - OPTIMIZED to query only relevant repos per user

        Instead of fetching all branches from all org repos, this:
        1. Identifies which repos each user has contributed to (via contributionsCollection)
        2. Only fetches branches from those specific repos for that user
        3. Still captures ALL branches, but avoids wasting API calls on repos where user has no activity

        Args:
            date_str: Date in YYYY-MM-DD format
            start_datetime: Start datetime for filtering
            end_datetime: End datetime for filtering
            user_ids: Set of user IDs to track

        Returns:
            Dictionary with commits data
        """
        commits_data = []
        commits_by_sha = {}

        try:
            logger.debug(
                f"Fetching commits for {date_str} from {len(user_ids)} users")

            # Step 1: For each user, identify repos where they have activity
            user_repos = {}
            for username in user_ids:
                active_repos = self._get_user_active_repos(
                    username, start_datetime, end_datetime)
                if active_repos:
                    user_repos[username] = active_repos

            if not user_repos:
                logger.info(
                    f"No active repos found for any user on {date_str}")
                return {'date': date_str, 'commits': []}

            # Step 2: For each user, fetch all branches from their active repos
            for username, repos in user_repos.items():
                logger.debug(f"Processing {len(repos)} repos for {username}")

                for repo_full_name in repos:
                    owner, repo_short = repo_full_name.split('/')

                    # First, fetch all branches (without commits)
                    branches_query = """
                    query($owner: String!, $repo: String!, $cursor: String) {
                      repository(owner: $owner, name: $repo) {
                        refs(refPrefix: "refs/heads/", first: 50, after: $cursor) {
                          totalCount
                          pageInfo {
                            hasNextPage
                            endCursor
                          }
                          nodes {
                            name
                          }
                        }
                      }
                    }
                    """

                    branch_variables = {
                        'owner': owner,
                        'repo': repo_short,
                        'cursor': None
                    }

                    # Collect all branch names first
                    all_branches = []
                    has_next_branch_page = True

                    while has_next_branch_page:
                        branch_data = self._graphql_request(
                            branches_query, branch_variables)

                        if not branch_data or 'repository' not in branch_data:
                            logger.debug(
                                f"Could not fetch branches for {repo_full_name}")
                            break

                        refs = branch_data['repository']['refs']
                        branch_page_info = refs['pageInfo']
                        has_next_branch_page = branch_page_info['hasNextPage']
                        branch_variables['cursor'] = branch_page_info['endCursor']

                        branches = refs.get('nodes', [])
                        all_branches.extend([b['name'] for b in branches])

                    # Now fetch commits for each branch with pagination
                    repo_commit_count = 0
                    total_branches_processed = len(all_branches)

                    for branch_name in all_branches:
                        # Query to fetch commits from a specific branch with pagination
                        commits_query = f"""
                        query($owner: String!, $repo: String!, $branch: String!, $cursor: String) {{
                          repository(owner: $owner, name: $repo) {{
                            ref(qualifiedName: $branch) {{
                              target {{
                                ... on Commit {{
                                  history(first: 100, since: "{start_datetime.isoformat()}Z", until: "{end_datetime.isoformat()}Z", after: $cursor) {{
                                    totalCount
                                    pageInfo {{
                                      hasNextPage
                                      endCursor
                                    }}
                                    nodes {{
                                      oid
                                      author {{
                                        user {{
                                          login
                                        }}
                                        name
                                        email
                                      }}
                                      committedDate
                                      message
                                      additions
                                      deletions
                                    }}
                                  }}
                                }}
                              }}
                            }}
                          }}
                        }}
                        """

                        commit_variables = {
                            'owner': owner,
                            'repo': repo_short,
                            'branch': f"refs/heads/{branch_name}",
                            'cursor': None
                        }

                        has_next_commit_page = True
                        branch_commit_count = 0

                        # Paginate through all commits in this branch
                        while has_next_commit_page:
                            commit_data = self._graphql_request(
                                commits_query, commit_variables)

                            if not commit_data or 'repository' not in commit_data:
                                break

                            ref = commit_data['repository'].get('ref')
                            if not ref or not ref.get('target'):
                                break

                            history = ref['target'].get('history', {})
                            commits = history.get('nodes', [])
                            commit_page_info = history.get('pageInfo', {})

                            has_next_commit_page = commit_page_info.get(
                                'hasNextPage', False)
                            commit_variables['cursor'] = commit_page_info.get(
                                'endCursor')

                            # Process commits from this page
                            for commit in commits:
                                try:
                                    commit_sha = commit['oid']

                                    # Check if we've already seen this commit
                                    if commit_sha in commits_by_sha:
                                        existing_commit = commits_by_sha[commit_sha]
                                        if branch_name not in existing_commit['branches']:
                                            existing_commit['branches'].append(
                                                branch_name)
                                        continue

                                    # Get author info
                                    author_data = commit.get('author', {})
                                    author_user = author_data.get('user')

                                    if not author_user:
                                        continue

                                    author_login = author_user.get('login')

                                    # Only process commits from the current user
                                    if author_login != username:
                                        continue

                                    # Check for bot commits
                                    author_name = author_data.get('name', '')
                                    author_email = author_data.get('email', '')
                                    is_bot = False
                                    for bot in KNOWN_BOTS:
                                        if bot.lower() in author_name.lower() or bot.lower() in author_email.lower():
                                            is_bot = True
                                            break

                                    if is_bot:
                                        continue

                                    # Extract commit data
                                    commit_data = {
                                        'sha': commit_sha,
                                        'author': author_login,
                                        'repository': repo_full_name,
                                        'timestamp': commit.get('committedDate', ''),
                                        'message': commit.get('message', '').split('\n')[0][:100],
                                        'stats': {
                                            'additions': commit.get('additions', 0),
                                            'deletions': commit.get('deletions', 0),
                                            'total': commit.get('additions', 0) + commit.get('deletions', 0)
                                        },
                                        'branches': [branch_name]
                                    }

                                    commits_by_sha[commit_sha] = commit_data
                                    commits_data.append(commit_data)
                                    repo_commit_count += 1
                                    branch_commit_count += 1

                                except Exception as e:
                                    logger.debug(
                                        f"Skipped commit in {repo_full_name}: {e}")
                                    continue

                        # Log if branch had commits
                        if branch_commit_count > 0:
                            logger.debug(
                                f"Branch {branch_name}: fetched {branch_commit_count} commits (paginated)")

                    if repo_commit_count > 0:
                        logger.debug(
                            f"User {username}: {repo_commit_count} commits from {repo_full_name} ({total_branches_processed} branches)"
                        )

        except Exception as e:
            logger.error(f"Error fetching commits for {date_str}: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Log summary
        unique_repos = len(set(c['repository'] for c in commits_data))
        unique_authors = len(set(c['author'] for c in commits_data))
        logger.info(
            f"Date {date_str}: {len(commits_data)} commits from {unique_repos} repos, {unique_authors} authors"
        )

        # Fetch contributor stats (only if not already cached for this week)
        # GitHub's stats API provides weekly data. If we already have stats for this week,
        # skip fetching to save API calls.
        contributor_stats = {}

        # Check if this date is within the last 7 days - stats might not be available yet
        date_obj = datetime.fromisoformat(date_str)
        days_old = (datetime.now().date() - date_obj.date()).days

        if days_old < 7:
            logger.debug(
                f"Date {date_str} is only {days_old} days old - skipping contributor stats fetch "
                "(GitHub stats calculated weekly)"
            )
        else:
            # Check if we need to fetch stats for any users
            users_needing_stats = []
            for username in user_ids:
                if not self._has_contributor_stats_for_week(date_str, username):
                    users_needing_stats.append(username)

            if users_needing_stats:
                logger.info(
                    f"Fetching contributor stats for {len(users_needing_stats)} user(s) "
                    f"(skipped {len(user_ids) - len(users_needing_stats)} already cached)"
                )

                for username in users_needing_stats:
                    active_repos = user_repos.get(username, [])
                    user_stats = {}

                    for repo_full_name in active_repos:
                        repo_stats = self._fetch_contributor_stats(
                            repo_full_name, username, start_datetime, end_datetime
                        )
                        if repo_stats:
                            # Merge stats from this repo
                            for stat_date, stats in repo_stats.items():
                                if stat_date not in user_stats:
                                    user_stats[stat_date] = {
                                        'commits': 0,
                                        'additions': 0,
                                        'deletions': 0,
                                        'total': 0,
                                        'repos': []
                                    }
                                user_stats[stat_date]['commits'] += stats['commits']
                                user_stats[stat_date]['additions'] += stats['additions']
                                user_stats[stat_date]['deletions'] += stats['deletions']
                                user_stats[stat_date]['total'] += stats['total']
                                user_stats[stat_date]['repos'].append(
                                    repo_full_name)

                    if user_stats:
                        contributor_stats[username] = user_stats
            else:
                logger.info(
                    f"All contributor stats already cached for week containing {date_str}"
                )

        # Fetch closed issues for each user
        issues_data = []
        logger.info(f"Fetching closed issues for {len(user_ids)} user(s)")
        for username in user_ids:
            user_issues = self._fetch_closed_issues_for_user(
                username=username,
                org=GITHUB_ORG,
                start_date=start_datetime,
                end_date=end_datetime
            )
            issues_data.extend(user_issues)

        logger.info(f"Date {date_str}: {len(issues_data)} total issues closed")

        return {
            'date': date_str,
            'commits': commits_data,
            'issues': issues_data,
            'issue_count': len(issues_data),
            'contributor_stats': contributor_stats  # Authoritative stats from GitHub
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

    def refresh_contributor_stats(self, start_date: datetime, end_date: datetime,
                                  user_ids: List[str]) -> Dict[str, Dict]:
        """Refresh only GitHub contributor stats without refetching commits

        This updates the contributor_stats field in existing cache files
        without re-fetching all the commit data.

        Args:
            start_date: Start date
            end_date: End date
            user_ids: List of GitHub user IDs to track

        Returns:
            Dictionary mapping date strings to updated cache data
        """
        logger.info(
            f"Refreshing GitHub contributor stats from {start_date.date()} to {end_date.date()}")

        # Get list of dates to process (only dates at least 7 days old)
        # GitHub stats are calculated weekly, so no point in fetching for recent data
        cutoff_date = datetime.now() - timedelta(days=7)
        dates = []
        current = start_date
        while current <= end_date:
            if current <= cutoff_date:
                dates.append(current.date().isoformat())
            current += timedelta(days=1)

        if not dates:
            print(f"\nNo dates to process (all data is less than 7 days old).")
            print("GitHub stats are calculated weekly. Recent data will be captured in the next report generation.")
            return {}

        print(
            f"\nProcessing {len(dates)} dates (at least 7 days old, skipping recent data)")

        results = {}
        start_datetime = start_date.replace(
            hour=0, minute=0, second=0, microsecond=0)
        end_datetime = end_date.replace(
            hour=23, minute=59, second=59, microsecond=999999)

        # Get active repos for each user (from existing cache)
        print("\nIdentifying active repositories from cached data...")
        user_repos = {}
        for username in user_ids:
            repos = set()
            for date_str in dates:
                cached_data = self.cache_manager.read_cache(date_str)
                if cached_data:
                    commits = cached_data.get('commits', [])
                    for commit in commits:
                        if commit.get('author') == username:
                            repo_name = commit.get('repository')
                            if repo_name:
                                repos.add(repo_name)
            if repos:
                user_repos[username] = sorted(list(repos))
                print(f"  {username}: {len(repos)} repos")

        if not user_repos:
            logger.warning(
                "No active repositories found in cache. Run fetch first.")
            return results

        # Fetch contributor stats for each date
        print(f"\nRefreshing GitHub stats for {len(dates)} dates...")
        with tqdm(total=len(dates), desc="Refreshing stats") as pbar:
            for date_str in dates:
                # Read existing cache
                cached_data = self.cache_manager.read_cache(date_str)
                if not cached_data:
                    logger.debug(f"No cache found for {date_str}, skipping")
                    pbar.update(1)
                    continue

                # Fetch contributor stats
                contributor_stats = {}
                for username in user_ids:
                    active_repos = user_repos.get(username, [])
                    user_stats = {}

                    for repo_full_name in active_repos:
                        # No retries for refresh - GitHub stats are weekly, if it's 202 it will be captured next time
                        repo_stats = self._fetch_contributor_stats(
                            repo_full_name, username, start_datetime, end_datetime, max_retries=1
                        )
                        if repo_stats:
                            # Merge stats from this repo
                            for stat_date, stats in repo_stats.items():
                                if stat_date not in user_stats:
                                    user_stats[stat_date] = {
                                        'commits': 0,
                                        'additions': 0,
                                        'deletions': 0,
                                        'total': 0,
                                        'repos': []
                                    }
                                user_stats[stat_date]['commits'] += stats['commits']
                                user_stats[stat_date]['additions'] += stats['additions']
                                user_stats[stat_date]['deletions'] += stats['deletions']
                                user_stats[stat_date]['total'] += stats['total']
                                user_stats[stat_date]['repos'].append(
                                    repo_full_name)

                    if user_stats:
                        contributor_stats[username] = user_stats

                # Update cache with new stats
                cached_data['contributor_stats'] = contributor_stats
                self.cache_manager.write_cache(date_str, cached_data)
                results[date_str] = cached_data

                stats_count = len(contributor_stats)
                pbar.set_postfix_str(f"{date_str}: {stats_count} users")
                pbar.update(1)

        print(f"\nRefresh complete. Updated stats for {len(results)} dates")
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
