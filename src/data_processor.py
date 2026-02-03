"""
Data Processor Module
Processes cached commits and generates pre-aggregated daily metrics per user
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from collections import defaultdict

from src.config import OUTPUT_DIR, USER_IDS
from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)


class DataProcessor:
    """Processes commit data and generates aggregated metrics"""

    def __init__(self):
        self.cache_manager = CacheManager()

    def _ensure_user_directory(self, username: str) -> str:
        """Ensure output directory exists for user

        Args:
            username: GitHub username

        Returns:
            Path to user's output directory
        """
        user_dir = os.path.join(OUTPUT_DIR, username)
        os.makedirs(user_dir, exist_ok=True)
        return user_dir

    def _get_output_file_path(self, username: str, date_str: str) -> str:
        """Get output file path for user and date

        Args:
            username: GitHub username
            date_str: Date in YYYY-MM-DD format

        Returns:
            Full path to output file
        """
        user_dir = self._ensure_user_directory(username)
        return os.path.join(user_dir, f"{date_str}.json")

    def output_exists(self, username: str, date_str: str) -> bool:
        """Check if output already exists for user and date

        Args:
            username: GitHub username
            date_str: Date in YYYY-MM-DD format

        Returns:
            True if output file exists
        """
        return os.path.exists(self._get_output_file_path(username, date_str))

    def process_date(self, date_str: str, user_ids: List[str], force_refresh: bool = False):
        """Process commits for a specific date and generate per-user metrics

        Args:
            date_str: Date in YYYY-MM-DD format
            user_ids: List of user IDs to process
            force_refresh: If True, overwrite existing output files
        """
        # Read cached data
        cached_data = self.cache_manager.read_cache(date_str)

        if not cached_data:
            print(f"Warning: No cached data found for {date_str}")
            return

        commits = cached_data.get('commits', [])

        # Aggregate by user
        user_metrics = defaultdict(lambda: {
            'additions': 0,
            'deletions': 0,
            'total_loc': 0,
            'commit_count': 0,
            'repositories': set()
        })

        for commit in commits:
            author = commit.get('author')
            if author and author in user_ids:
                stats = commit.get('stats', {})
                user_metrics[author]['additions'] += stats.get('additions', 0)
                user_metrics[author]['deletions'] += stats.get('deletions', 0)
                user_metrics[author]['total_loc'] += stats.get('total', 0)
                user_metrics[author]['commit_count'] += 1
                user_metrics[author]['repositories'].add(
                    commit.get('repository', ''))

        # Write output for each user
        for username in user_ids:
            # Skip if output exists and not forcing refresh
            if not force_refresh and self.output_exists(username, date_str):
                continue

            metrics = user_metrics[username]

            # Convert set to list for JSON serialization
            repos_list = sorted(
                list(metrics['repositories'])) if metrics['repositories'] else []

            output_data = {
                'date': date_str,
                'username': username,
                'additions': metrics['additions'],
                'deletions': metrics['deletions'],
                'total_loc': metrics['total_loc'],
                'commit_count': metrics['commit_count'],
                'repositories': repos_list,
                'repo_count': len(repos_list),
                'processed_at': datetime.utcnow().isoformat() + 'Z'
            }

            # Write to file
            output_file = self._get_output_file_path(username, date_str)
            try:
                with open(output_file, 'w') as f:
                    json.dump(output_data, f, indent=2)

                if metrics['commit_count'] > 0:
                    logger.debug(
                        f"{username}: {metrics['commit_count']} commits, {metrics['total_loc']} LOC on {date_str}")
            except IOError as e:
                print(
                    f"Error writing output for {username} on {date_str}: {e}")

    def process_date_range(self, start_date: datetime, end_date: datetime,
                           user_ids: List[str], force_refresh: bool = False):
        """Process commits for a date range

        Args:
            start_date: Start date
            end_date: End date
            user_ids: List of user IDs to process
            force_refresh: If True, overwrite existing output files
        """
        current_date = start_date.date()
        end_date_only = end_date.date()
        dates_processed = 0
        dates_skipped = 0

        logger.info(f"Processing data for {len(user_ids)} user(s)...")

        while current_date <= end_date_only:
            date_str = current_date.isoformat()

            # Check if all users already have output for this date
            if not force_refresh and all(self.output_exists(user, date_str) for user in user_ids):
                dates_skipped += 1
                current_date += timedelta(days=1)
                continue

            self.process_date(date_str, user_ids, force_refresh)
            dates_processed += 1

            current_date += timedelta(days=1)

        if dates_skipped > 0:
            logger.info(f"Skipped {dates_skipped} date(s) (already processed)")

        logger.info(f"Processed {dates_processed} date(s)") if dates_processed > 0 else logger.info(
            "No new dates to process")

    def read_user_data(self, username: str, start_date: datetime, end_date: datetime) -> Dict[str, Dict]:
        """Read processed data for a user across date range

        Args:
            username: GitHub username
            start_date: Start date
            end_date: End date

        Returns:
            Dictionary mapping date strings to metrics
        """
        data = {}
        current_date = start_date.date()
        end_date_only = end_date.date()

        logger.debug(
            f"Reading data for {username} from {start_date.date()} to {end_date.date()}")

        logger.debug(
            f"Reading data for {username} from {start_date.date()} to {end_date.date()}")

        while current_date <= end_date_only:
            date_str = current_date.isoformat()
            output_file = self._get_output_file_path(username, date_str)

            if os.path.exists(output_file):
                try:
                    with open(output_file, 'r') as f:
                        data[date_str] = json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    print(
                        f"Warning: Failed to read data for {username} on {date_str}: {e}")
            else:
                # Create zero-data entry for missing dates
                data[date_str] = {
                    'date': date_str,
                    'username': username,
                    'additions': 0,
                    'deletions': 0,
                    'total_loc': 0,
                    'commit_count': 0,
                    'repositories': [],
                    'repo_count': 0
                }

            current_date += timedelta(days=1)

        return data

    def read_all_users_data(self, user_ids: List[str], start_date: datetime,
                            end_date: datetime) -> Dict[str, Dict[str, Dict]]:
        """Read processed data for all users

        Args:
            user_ids: List of GitHub usernames
            start_date: Start date
            end_date: End date

        Returns:
            Dictionary mapping usernames to their date-indexed data
        """
        all_data = {}

        for username in user_ids:
            all_data[username] = self.read_user_data(
                username, start_date, end_date)

        return all_data

    def get_summary_stats(self, user_ids: List[str], start_date: datetime,
                          end_date: datetime) -> Dict:
        """Get summary statistics for all users

        Args:
            user_ids: List of GitHub usernames
            start_date: Start date
            end_date: End date

        Returns:
            Summary statistics dictionary
        """
        all_data = self.read_all_users_data(user_ids, start_date, end_date)

        summary = {
            'date_range': {
                'start': start_date.date().isoformat(),
                'end': end_date.date().isoformat()
            },
            'users': {}
        }

        for username, data in all_data.items():
            total_additions = sum(d['additions'] for d in data.values())
            total_deletions = sum(d['deletions'] for d in data.values())
            total_commits = sum(d['commit_count'] for d in data.values())

            # Get unique repositories
            all_repos = set()
            for d in data.values():
                all_repos.update(d['repositories'])

            summary['users'][username] = {
                'total_additions': total_additions,
                'total_deletions': total_deletions,
                'total_loc': total_additions + total_deletions,
                'total_commits': total_commits,
                'unique_repositories': len(all_repos),
                'repositories': sorted(list(all_repos))
            }

        return summary
