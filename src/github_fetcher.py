"""
GitHub Fetcher Module
Fetches commit data from GitHub with concurrent threading and bot filtering
"""
import logging
import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
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

    def _graphql_request(self, query: str, variables: Optional[Dict] = None) -> Optional[Dict]:
        """Make a GraphQL API request to GitHub

        Args:
            query: GraphQL query string
            variables: Query variables

        Returns:
            JSON response or None on error
        """
        try:
            payload = {'query': query}
            if variables:
                payload['variables'] = variables

            response = self.session.post(
                self.graphql_url, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()

            if 'errors' in result:
                logger.warning(f"GraphQL errors: {result['errors']}")
                return None

            return result.get('data')
        except requests.exceptions.RequestException as e:
            logger.warning(f"GraphQL request failed: {e}")
            return None

    def _api_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[List]:
        """Make a direct REST API request to GitHub (fallback for specific endpoints)

        Args:
            endpoint: API endpoint (e.g., '/repos/owner/repo/commits')
            params: Query parameters

        Returns:
            JSON response (list or dict) or None on error
        """
        url = f"{self.base_url}{endpoint}"
        try:
            # Update headers for REST API
            headers = self.session.headers.copy()
            headers['Authorization'] = f'token {GITHUB_TOKEN}'
            headers['Accept'] = 'application/vnd.github.v3+json'

            response = requests.get(
                url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            logger.debug(
                f"API request to {endpoint}: {len(result) if isinstance(result, list) else 'dict'} items")
            return result
        except requests.exceptions.RequestException as e:
            logger.warning(f"API request failed for {endpoint}: {e}")
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

    def _fetch_commits_for_date(self, date_str: str, start_datetime: datetime,
                                end_datetime: datetime, user_ids: Set[str]) -> Dict:
        """Fetch commits for a specific date from all org repos using GraphQL API

        Args:
            date_str: Date in YYYY-MM-DD format
            start_datetime: Start datetime for filtering
            end_datetime: End datetime for filtering
            user_ids: Set of user IDs to track

        Returns:
            Dictionary with commits data
        """
        commits_data = []
        seen_commits = set()

        try:
            # GraphQL query to fetch repos with their branches and commits
            # Reduced limits to avoid MAX_NODE_LIMIT_EXCEEDED error
            query = """
            query($org: String!, $since: GitTimestamp!, $until: GitTimestamp!, $cursor: String) {
              organization(login: $org) {
                repositories(first: 20, after: $cursor) {
                  pageInfo {
                    hasNextPage
                    endCursor
                  }
                  nodes {
                    nameWithOwner
                    refs(refPrefix: "refs/heads/", first: 10) {
                      nodes {
                        name
                        target {
                          ... on Commit {
                            history(first: 50, since: $since, until: $until) {
                              nodes {
                                oid
                                author {
                                  user {
                                    login
                                  }
                                  name
                                  email
                                }
                                committedDate
                                message
                                additions
                                deletions
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
            """

            variables = {
                'org': GITHUB_ORG,
                'since': start_datetime.isoformat() + 'Z',
                'until': end_datetime.isoformat() + 'Z',
                'cursor': None
            }

            has_next_page = True
            repo_count = 0

            while has_next_page:
                logger.debug(
                    f"Fetching repositories page (cursor: {variables.get('cursor', 'first')})")

                data = self._graphql_request(query, variables)

                if not data or 'organization' not in data:
                    logger.error(f"Failed to fetch data from GraphQL API")
                    break

                repos = data['organization']['repositories']
                page_info = repos['pageInfo']
                has_next_page = page_info['hasNextPage']
                variables['cursor'] = page_info['endCursor']

                for repo in repos['nodes']:
                    repo_full_name = repo['nameWithOwner']
                    repo_name = repo_full_name.split('/')[-1]
                    repo_commit_count = 0

                    # Process each branch
                    branches = repo.get('refs', {}).get('nodes', [])

                    for branch in branches:
                        branch_name = branch['name']

                        # Get commit history for this branch
                        target = branch.get('target')
                        if not target:
                            continue

                        history = target.get('history', {}).get('nodes', [])

                        for commit in history:
                            try:
                                commit_sha = commit['oid']

                                # Skip if we've already processed this commit
                                if commit_sha in seen_commits:
                                    continue

                                seen_commits.add(commit_sha)

                                # Get author info
                                author_data = commit.get('author', {})
                                author_user = author_data.get('user')

                                # Skip if no author user
                                if not author_user:
                                    continue

                                author_login = author_user.get('login')

                                # Skip if author not in tracking list
                                if author_login not in user_ids:
                                    continue

                                # Check for bot commits using author name/email
                                author_name = author_data.get('name', '')
                                author_email = author_data.get('email', '')
                                is_bot = False
                                for bot in KNOWN_BOTS:
                                    if bot.lower() in author_name.lower() or bot.lower() in author_email.lower():
                                        is_bot = True
                                        break

                                if is_bot:
                                    continue

                                # Extract commit data from GraphQL response
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
                                    # Tag with the branch we fetched it from
                                    'branches': [branch_name]
                                }

                                # Optionally fetch other branches containing this commit as HEAD
                                # (This will find if the commit is also the HEAD of other branches)
                                try:
                                    additional_branches = self._fetch_commit_branches(
                                        repo_full_name, commit_sha
                                    )
                                    # Add any branches not already in the list
                                    for branch in additional_branches:
                                        if branch not in commit_data['branches']:
                                            commit_data['branches'].append(
                                                branch)
                                except Exception as e:
                                    logger.debug(
                                        f"Could not fetch additional branches for commit {commit_sha[:7]}: {e}"
                                    )

                                commits_data.append(commit_data)
                                repo_commit_count += 1

                                logger.debug(
                                    f"Processed commit {commit_sha[:7]} by {author_login} in {repo_name}")

                            except Exception as e:
                                # Skip problematic individual commits
                                logger.debug(
                                    f"Skipped commit in {repo_full_name}: {e}")
                                continue

                    if repo_commit_count > 0:
                        logger.debug(
                            f"Fetched {repo_commit_count} commits from {repo_full_name}")
                        repo_count += 1

        except Exception as e:
            logger.error(f"Error fetching commits for {date_str}: {e}")

        # Log summary
        unique_repos = len(set(c['repository'] for c in commits_data))
        unique_authors = len(set(c['author'] for c in commits_data))
        logger.info(
            f"Date {date_str}: {len(commits_data)} commits from {unique_repos} repos, {unique_authors} authors")

        return {
            'date': date_str,
            'commits': commits_data
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

                        # Cache the data
                        self.cache_manager.write_cache(date_str, data)
                        results[date_str] = data

                        commit_count = len(data.get('commits', []))
                        pbar.set_postfix_str(
                            f"{date_str}: {commit_count} commits")

                    except Exception as e:
                        print(f"\nError processing {date_str}: {e}")

                    pbar.update(1)

        # Update metadata
        self.cache_manager.update_metadata(
            (start_date.date().isoformat(), end_date.date().isoformat()))

        print(
            f"\nFetch complete. Total: {sum(len(d.get('commits', [])) for d in results.values())} commits")

        return results

    def get_rate_limit_status(self) -> Dict:
        """Get current rate limit status

        Returns:
            Dictionary with rate limit info
        """
        try:
            response = self.session.get(
                f"{self.base_url}/rate_limit", timeout=10)
            if response.status_code != 200:
                return {'error': 'Could not fetch rate limit'}

            rate_data = response.json()
            rate_limit = rate_data['resources']['core']

            remaining = rate_limit['remaining']
            limit = rate_limit['limit']
            reset_timestamp = rate_limit['reset']
            reset = datetime.fromtimestamp(reset_timestamp).isoformat()

            return {
                'remaining': remaining,
                'limit': limit,
                'reset': reset
            }
        except Exception as e:
            return {
                'remaining': 'unknown',
                'limit': 'unknown',
                'reset': f'Error: {e}'
            }
