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

    # Priority branches (checked in order)
    PRIORITY_BRANCHES = ['main', 'master', 'develop',
                         'development', 'staging', 'production']

    def __init__(self):
        self.cache_manager = CacheManager()

    def _get_primary_branch(self, branches: List[str]) -> str:
        """Select the most relevant branch from a list

        Prioritizes main/master/develop branches over feature branches.

        Args:
            branches: List of branch names

        Returns:
            Primary branch name (or 'unknown' if empty list)
        """
        if not branches:
            return 'unknown'

        # Check for priority branches in order
        for priority_branch in self.PRIORITY_BRANCHES:
            if priority_branch in branches:
                return priority_branch

        # Return first branch if no priority branch found
        return branches[0]

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

        # Deduplicate commits by SHA to avoid counting merge commits and their constituent commits
        seen_shas = set()
        unique_commits = []

        # First pass: deduplicate by exact SHA match
        for commit in commits:
            sha = commit.get('sha')
            if sha and sha not in seen_shas:
                seen_shas.add(sha)
                unique_commits.append(commit)
            else:
                logger.debug(
                    f"Skipping duplicate commit {sha[:7]} on {date_str}")

        # Second pass: detect and remove squash-merge duplicates
        # (same author, same date, very similar stats, different SHAs)
        author_commits = defaultdict(list)
        for commit in unique_commits:
            author = commit.get('author')
            if author:
                author_commits[author].append(commit)

        deduped_commits = []
        for author, author_commit_list in author_commits.items():
            # Group commits by similar stats (within 1% difference)
            processed_indices = set()

            for i, commit in enumerate(author_commit_list):
                if i in processed_indices:
                    continue

                stats = commit.get('stats', {})
                additions = stats.get('additions', 0)
                deletions = stats.get('deletions', 0)
                total = stats.get('total', 0)
                branches = commit.get('branches', [])
                primary_branch = self._get_primary_branch(branches)

                # Find similar commits (likely squash-merge duplicates)
                similar_commits = [commit]
                for j, other_commit in enumerate(author_commit_list):
                    if j <= i or j in processed_indices:
                        continue

                    other_stats = other_commit.get('stats', {})
                    other_additions = other_stats.get('additions', 0)
                    other_deletions = other_stats.get('deletions', 0)
                    other_total = other_stats.get('total', 0)

                    # Check if stats are very similar (within 1% or absolute difference < 100)
                    if total > 0 and other_total > 0:
                        diff_ratio = abs(total - other_total) / \
                            max(total, other_total)
                        if diff_ratio < 0.01 or abs(total - other_total) < 100:
                            similar_commits.append(other_commit)
                            processed_indices.add(j)

                # If we found similar commits, keep only the one on the highest priority branch
                if len(similar_commits) > 1:
                    logger.info(
                        f"Found {len(similar_commits)} similar commits by {author} "
                        f"with ~{total} LOC changes on {date_str}. Keeping only the one on highest priority branch."
                    )
                    # Sort by branch priority (main/master/develop first)
                    similar_commits.sort(key=lambda c: (
                        self.PRIORITY_BRANCHES.index(
                            self._get_primary_branch(c.get('branches', [])))
                        if self._get_primary_branch(c.get('branches', [])) in self.PRIORITY_BRANCHES
                        else 999
                    ))
                    deduped_commits.append(similar_commits[0])
                    for skipped in similar_commits[1:]:
                        logger.info(
                            f"  Skipping {skipped.get('sha', '')[:7]} on branch "
                            f"{self._get_primary_branch(skipped.get('branches', []))}"
                        )
                else:
                    deduped_commits.append(commit)

                processed_indices.add(i)

        logger.info(
            f"Date {date_str}: {len(commits)} total commits, "
            f"{len(unique_commits)} unique by SHA, "
            f"{len(deduped_commits)} after squash-merge deduplication"
        )

        # Aggregate by user
        user_metrics = defaultdict(lambda: {
            'additions': 0,
            'deletions': 0,
            'total_loc': 0,
            'commit_count': 0,
            'repositories': set(),
            'branch_breakdown': defaultdict(lambda: defaultdict(lambda: {
                'additions': 0,
                'deletions': 0,
                'total_loc': 0,
                'commit_count': 0
            }))
        })

        for commit in deduped_commits:
            author = commit.get('author')
            if author and author in user_ids:
                stats = commit.get('stats', {})
                repository = commit.get('repository', '')
                branches = commit.get('branches', [])

                # Aggregate overall metrics
                user_metrics[author]['additions'] += stats.get('additions', 0)
                user_metrics[author]['deletions'] += stats.get('deletions', 0)
                user_metrics[author]['total_loc'] += stats.get('total', 0)
                user_metrics[author]['commit_count'] += 1
                user_metrics[author]['repositories'].add(repository)

                # Select primary branch (prioritizes main/master/develop over feature branches)
                # This prevents counting the same commit multiple times across branches
                primary_branch = self._get_primary_branch(branches)

                user_metrics[author]['branch_breakdown'][repository][primary_branch]['additions'] += stats.get(
                    'additions', 0)
                user_metrics[author]['branch_breakdown'][repository][primary_branch]['deletions'] += stats.get(
                    'deletions', 0)
                user_metrics[author]['branch_breakdown'][repository][primary_branch]['total_loc'] += stats.get(
                    'total', 0)
                user_metrics[author]['branch_breakdown'][repository][primary_branch]['commit_count'] += 1

        # Write output for each user
        for username in user_ids:
            # Skip if output exists and not forcing refresh
            if not force_refresh and self.output_exists(username, date_str):
                continue

            metrics = user_metrics[username]

            # Convert set to list for JSON serialization
            repos_list = sorted(
                list(metrics['repositories'])) if metrics['repositories'] else []

            # Convert branch_breakdown nested defaultdicts to regular dicts for JSON
            branch_breakdown = {}
            if 'branch_breakdown' in metrics:
                for repo, branches in metrics['branch_breakdown'].items():
                    branch_breakdown[repo] = dict(branches)

            output_data = {
                'date': date_str,
                'username': username,
                'additions': metrics['additions'],
                'deletions': metrics['deletions'],
                'total_loc': metrics['total_loc'],
                'commit_count': metrics['commit_count'],
                'repositories': repos_list,
                'repo_count': len(repos_list),
                'branch_breakdown': branch_breakdown,
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
            start_date: Start date (None for all cached dates)
            end_date: End date (None for all cached dates)
            user_ids: List of user IDs to process
            force_refresh: If True, overwrite existing output files
        """
        dates_processed = 0
        dates_skipped = 0

        logger.info(f"Processing data for {len(user_ids)} user(s)...")

        # Handle ALL_CACHED mode
        if start_date is None and end_date is None:
            # Get all cached dates
            cached_dates = self.cache_manager.get_cached_dates()
            for date_str in cached_dates:
                # Check if all users already have output for this date
                if not force_refresh and all(self.output_exists(user, date_str) for user in user_ids):
                    dates_skipped += 1
                    continue

                self.process_date(date_str, user_ids, force_refresh)
                dates_processed += 1
        else:
            # Normal date range iteration
            current_date = start_date.date()
            end_date_only = end_date.date()

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
                    'repo_count': 0,
                    'branch_breakdown': {}
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
