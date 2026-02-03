"""
GitHub Fetcher Module
Fetches commit data from GitHub with concurrent threading and bot filtering
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Set
from collections import defaultdict

from github import Github, GithubException, RateLimitExceededException
from tqdm import tqdm

from config import GITHUB_TOKEN, GITHUB_ORG, KNOWN_BOTS
from cache_manager import CacheManager


class GitHubFetcher:
    """Fetches commit data from GitHub with concurrent threading"""

    def __init__(self, thread_count: int = 4):
        self.thread_count = thread_count
        self.rate_limit_lock = threading.Lock()
        self.cache_manager = CacheManager()
        self.github_client = Github(GITHUB_TOKEN, per_page=100)

    def _check_rate_limit(self):
        """Check GitHub API rate limit and wait if necessary"""
        with self.rate_limit_lock:
            try:
                rate_limit = self.github_client.get_rate_limit()
                # Access rate_limit as dictionary or object
                if hasattr(rate_limit, 'core'):
                    remaining = rate_limit.core.remaining
                    reset_time = rate_limit.core.reset
                else:
                    # Fallback for newer PyGithub versions
                    remaining = rate_limit.rate.remaining
                    reset_time = rate_limit.rate.reset

                if remaining < 100:
                    wait_seconds = (
                        reset_time - datetime.utcnow()).total_seconds() + 10

                    if wait_seconds > 0:
                        print(
                            f"\nRate limit low ({remaining} remaining). Waiting {wait_seconds:.0f} seconds...")
                        time.sleep(wait_seconds)
            except Exception as e:
                # If rate limit check fails, log but continue
                print(f"Warning: Could not check rate limit: {e}")

    def _is_bot_commit(self, commit) -> bool:
        """Check if a commit is from a bot using API type check

        Args:
            commit: PyGithub commit object

        Returns:
            True if commit is from a bot
        """
        try:
            # Try to get author user object
            author = commit.author
            if author:
                # Check user type via API
                if hasattr(author, 'type') and author.type == 'Bot':
                    return True

            # Fallback: Check commit author login against known bots
            if commit.commit.author:
                author_name = commit.commit.author.name or ''
                author_email = commit.commit.author.email or ''

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
        """Fetch commits for a specific date from all org repos

        Args:
            date_str: Date in YYYY-MM-DD format
            start_datetime: Start datetime for filtering
            end_datetime: End datetime for filtering
            user_ids: Set of user IDs to track

        Returns:
            Dictionary with commits data
        """
        commits_data = []

        try:
            # Get organization
            org = self.github_client.get_organization(GITHUB_ORG)

            # Get all repositories
            repos = list(org.get_repos())

            for repo in repos:
                try:
                    # Check rate limit before each repo
                    self._check_rate_limit()

                    # Get commits for date range
                    commits = repo.get_commits(
                        since=start_datetime,
                        until=end_datetime
                    )

                    for commit in commits:
                        try:
                            # Skip if no author
                            if not commit.author:
                                continue

                            author_login = commit.author.login if commit.author else None

                            # Skip if author not in tracking list
                            if author_login not in user_ids:
                                continue

                            # Skip bot commits
                            if self._is_bot_commit(commit):
                                continue

                            # Extract commit data
                            commit_data = {
                                'sha': commit.sha,
                                'author': author_login,
                                'repository': repo.full_name,
                                'timestamp': commit.commit.author.date.isoformat(),
                                # First line, truncated
                                'message': commit.commit.message.split('\n')[0][:100],
                                'stats': {
                                    'additions': commit.stats.additions if commit.stats else 0,
                                    'deletions': commit.stats.deletions if commit.stats else 0,
                                    'total': commit.stats.total if commit.stats else 0
                                }
                            }

                            commits_data.append(commit_data)

                        except Exception as e:
                            # Skip problematic individual commits
                            continue

                except GithubException as e:
                    if e.status == 409:  # Empty repository
                        continue
                    print(
                        f"Warning: Error fetching commits from {repo.full_name}: {e}")
                    continue

        except Exception as e:
            print(f"Error fetching commits for {date_str}: {e}")

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
        user_ids_set = set(user_ids)
        results = {}

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
                    current_date += timedelta(days=1)
                    continue

            dates_to_fetch.append(date_str)
            current_date += timedelta(days=1)

        if not dates_to_fetch:
            print("All dates found in cache. Use --refresh to force re-fetch.")
            return results

        print(
            f"\nFetching commits for {len(dates_to_fetch)} date(s) from {GITHUB_ORG}...")
        print(f"Tracking users: {', '.join(user_ids)}")
        print(f"Using {self.thread_count} concurrent threads\n")

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
            rate_limit = self.github_client.get_rate_limit()

            # Access rate_limit as dictionary or object
            if hasattr(rate_limit, 'core'):
                remaining = rate_limit.core.remaining
                limit = rate_limit.core.limit
                reset = rate_limit.core.reset.isoformat()
            else:
                # Fallback for newer PyGithub versions
                remaining = rate_limit.rate.remaining
                limit = rate_limit.rate.limit
                reset = rate_limit.rate.reset.isoformat()

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
