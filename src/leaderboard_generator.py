"""
Leaderboard Generator Module
Generates daily and weekly GitHub commit leaderboards from cached data
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

from src.config import IST_TIMEZONE, LEADERBOARD_WEIGHTS
from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)


class LeaderboardGenerator:
    """Generates leaderboards from cached commit data"""

    def __init__(self, cache_manager: CacheManager):
        self.cache_manager = cache_manager

    def should_post_weekly(self) -> bool:
        """Check if we should post weekly leaderboard (Monday morning)

        Weekly summary should post on Monday 12:00 AM IST, which includes
        the complete Sunday-Saturday week in the data (yesterday = Sunday).

        Returns:
            True if today is Monday (weekday 0)
        """
        now = datetime.now(IST_TIMEZONE)
        return now.weekday() == 0

    def get_yesterday_ist(self) -> str:
        """Get yesterday's date in IST timezone

        Returns:
            Date string in YYYY-MM-DD format
        """
        now = datetime.now(IST_TIMEZONE)
        yesterday = now - timedelta(days=1)
        return yesterday.strftime('%Y-%m-%d')

    def get_last_7_days_ist(self) -> List[str]:
        """Get list of last 7 days ending yesterday in IST timezone

        Returns:
            List of date strings in YYYY-MM-DD format
        """
        now = datetime.now(IST_TIMEZONE)
        yesterday = now - timedelta(days=1)
        dates = []
        for i in range(7):
            date = yesterday - timedelta(days=i)
            dates.append(date.strftime('%Y-%m-%d'))
        return sorted(dates)  # Return in chronological order

    def aggregate_metrics(self, date_strings: List[str]) -> Dict[str, Dict[str, int]]:
        """Aggregate commit and issue metrics across multiple dates

        Args:
            date_strings: List of dates in YYYY-MM-DD format

        Returns:
            Dict mapping username to metrics dict with 'issues_closed', 'commit_count',
            'total_loc', 'total_additions', and 'total_deletions'
        """
        def _default_metrics():
            return {
                'issues_closed': 0,
                'commit_count': 0,
                'total_loc': 0,
                'total_additions': 0,
                'total_deletions': 0,
            }

        user_metrics = defaultdict(_default_metrics)

        for date_str in date_strings:
            cached_data = self.cache_manager.read_cache(date_str)
            if not cached_data:
                logger.debug(f"No cache found for {date_str}, skipping")
                continue

            # Process commits
            commits = cached_data.get('commits', [])
            logger.debug(f"Processing {len(commits)} commits for {date_str}")

            for commit in commits:
                author = commit.get('author')
                if not author:
                    continue

                stats = commit.get('stats', {})
                additions = stats.get('additions', 0)
                deletions = stats.get('deletions', 0)

                user_metrics[author]['commit_count'] += 1
                user_metrics[author]['total_loc'] += additions + deletions
                user_metrics[author]['total_additions'] += additions
                user_metrics[author]['total_deletions'] += deletions

            # Process issues (backward compatible - old cache files won't have issues)
            issues = cached_data.get('issues', [])
            logger.debug(f"Processing {len(issues)} issues for {date_str}")

            for issue in issues:
                assignee = issue.get('assignee')
                if not assignee:
                    continue

                user_metrics[assignee]['issues_closed'] += 1

        logger.info(
            f"Aggregated metrics for {len(user_metrics)} users across {len(date_strings)} dates")
        return dict(user_metrics)

    def compute_weighted_scores(
        self,
        user_metrics: Dict[str, Dict[str, int]]
    ) -> Dict[str, float]:
        """Compute weighted normalized scores for each contributor.

        Each metric is min-max normalized to [0, 1] across all contributors,
        then multiplied by its configured weight from LEADERBOARD_WEIGHTS.
        When all contributors share the same value for a metric (max == min),
        that metric contributes 0 to everyone's score.

        Args:
            user_metrics: Dict mapping username to metrics dict

        Returns:
            Dict mapping username to weighted score (float)
        """
        if not user_metrics:
            return {}

        usernames = list(user_metrics.keys())

        # Map each weight key to its corresponding metrics key
        metric_map = {
            'issues_closed': 'issues_closed',
            'commits': 'commit_count',
            'additions': 'total_additions',
            'deletions': 'total_deletions',
        }

        scores = {u: 0.0 for u in usernames}

        for weight_key, metrics_key in metric_map.items():
            weight = LEADERBOARD_WEIGHTS.get(weight_key, 0)
            if weight == 0:
                continue

            values = [user_metrics[u].get(metrics_key, 0) for u in usernames]
            min_val = min(values)
            max_val = max(values)

            if max_val == min_val:
                if max_val == 0:
                    # No activity for this metric — contributes nothing
                    continue
                # All contributors tied with the same non-zero value (includes
                # the single-contributor case) — everyone earns the full weight
                for u in usernames:
                    scores[u] += weight * 1.0
                continue

            for u, v in zip(usernames, values):
                normalized = (v - min_val) / (max_val - min_val)
                scores[u] += weight * normalized

        return scores

    def get_all_contributors_by_impact(
        self,
        user_metrics: Dict[str, Dict[str, int]]
    ) -> List[Tuple[str, Dict[str, int]]]:
        """Get ALL contributors sorted by weighted normalized impact score.

        Computes a weighted score from min-max normalized metrics:
            score = w_issues * norm(issues_closed)
                  + w_commits * norm(commit_count)
                  + w_additions * norm(total_additions)
                  + w_deletions * norm(total_deletions)

        Weights are configured in LEADERBOARD_WEIGHTS in config.py.

        Args:
            user_metrics: Dict mapping username to metrics

        Returns:
            List of tuples (username, full_metrics_dict) sorted by score descending.
            Each metrics dict includes a 'score' key with the computed float score.
        """
        if not user_metrics:
            return []

        scores = self.compute_weighted_scores(user_metrics)

        # Attach score to each user's metrics dict
        enriched = {}
        for username, metrics in user_metrics.items():
            enriched[username] = dict(metrics)
            enriched[username]['score'] = scores.get(username, 0.0)

        sorted_users = sorted(
            enriched.items(),
            key=lambda x: x[1]['score'],
            reverse=True
        )

        return sorted_users

    def format_date_range(self, date_strings: List[str]) -> str:
        """Format date range for display

        Args:
            date_strings: List of dates in YYYY-MM-DD format

        Returns:
            Formatted date range string like "Feb 2-8, 2026"
        """
        if not date_strings:
            return ""

        if len(date_strings) == 1:
            date = datetime.strptime(date_strings[0], '%Y-%m-%d')
            return date.strftime('%b %d, %Y')

        start_date = datetime.strptime(min(date_strings), '%Y-%m-%d')
        end_date = datetime.strptime(max(date_strings), '%Y-%m-%d')

        # If same month, show "Feb 2-8, 2026"
        if start_date.month == end_date.month:
            return f"{start_date.strftime('%b')} {start_date.day}-{end_date.day}, {end_date.year}"
        # If different months, show "Jan 28 - Feb 3, 2026"
        else:
            return f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"

    def generate_daily_leaderboard(self) -> Tuple[List[Tuple[str, Dict[str, int]]], str]:
        """Generate daily leaderboard for yesterday

        Returns:
            Tuple of (contributors_by_impact, date_string)
            contributors_by_impact: List of (username, metrics_dict) tuples
        """
        yesterday = self.get_yesterday_ist()
        logger.info(f"Generating daily leaderboard for {yesterday}")

        user_metrics = self.aggregate_metrics([yesterday])

        all_by_impact = self.get_all_contributors_by_impact(user_metrics)

        date_str = self.format_date_range([yesterday])

        logger.info(
            f"Daily leaderboard: {len(all_by_impact)} contributors"
        )

        return all_by_impact, date_str

    def generate_weekly_leaderboard(self) -> Tuple[List[Tuple[str, Dict[str, int]]], str]:
        """Generate weekly leaderboard for last 7 days

        Returns:
            Tuple of (contributors_by_impact, date_range_string)
            contributors_by_impact: List of (username, metrics_dict) tuples
        """
        last_7_days = self.get_last_7_days_ist()
        logger.info(
            f"Generating weekly leaderboard for {last_7_days[0]} to {last_7_days[-1]}")

        user_metrics = self.aggregate_metrics(last_7_days)

        all_by_impact = self.get_all_contributors_by_impact(user_metrics)

        date_str = self.format_date_range(last_7_days)

        logger.info(
            f"Weekly leaderboard: {len(all_by_impact)} contributors"
        )

        return all_by_impact, date_str

    def get_commits_breakdown(self, date_strings: List[str], leaderboard_order: List[Tuple[str, Dict[str, int]]]) -> Dict[str, List[Dict]]:
        """Get detailed commit breakdown for each user in leaderboard order

        Args:
            date_strings: List of dates in YYYY-MM-DD format
            leaderboard_order: List of (username, metrics_dict) tuples defining the order

        Returns:
            Dict mapping username to list of commits with details
        """
        user_commits = defaultdict(list)

        for date_str in date_strings:
            cached_data = self.cache_manager.read_cache(date_str)
            if not cached_data:
                continue

            commits = cached_data.get('commits', [])

            for commit in commits:
                author = commit.get('author')
                if not author:
                    continue

                stats = commit.get('stats', {})
                repo = commit.get('repository', '')
                sha = commit.get('sha', '')
                message = commit.get('message', '').split('\n')[
                    0]  # First line only

                user_commits[author].append({
                    'sha': sha,
                    'message': message,
                    'repository': repo,
                    'total_loc': stats.get('total', 0),
                    'additions': stats.get('additions', 0),
                    'deletions': stats.get('deletions', 0)
                })

        return dict(user_commits)

    def get_issues_breakdown(self, date_strings: List[str], leaderboard_order: List[Tuple[str, Dict[str, int]]]) -> Dict[str, List[Dict]]:
        """Get detailed issue breakdown for each user in leaderboard order

        Args:
            date_strings: List of dates in YYYY-MM-DD format
            leaderboard_order: List of (username, metrics_dict) tuples defining the order

        Returns:
            Dict mapping username to list of issues with details
        """
        # Extract usernames from leaderboard order
        usernames_in_order = [username for username, _ in leaderboard_order]

        user_issues = {username: [] for username in usernames_in_order}

        for date_str in date_strings:
            cached_data = self.cache_manager.read_cache(date_str)
            if not cached_data:
                continue

            issues = cached_data.get('issues', [])

            for issue in issues:
                assignee = issue.get('assignee')
                if assignee in user_issues:
                    user_issues[assignee].append({
                        'number': issue.get('number'),
                        'title': issue.get('title', ''),
                        'repository': issue.get('repository', ''),
                        'url': issue.get('url', ''),
                        'closed_at': issue.get('closed_at', '')
                    })

        return user_issues
