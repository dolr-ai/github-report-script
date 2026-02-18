"""
Google Chat Poster Module
Posts leaderboard messages to Google Chat webhook
"""
import logging
import time
from typing import List, Tuple

import requests

from src.config import (
    GOOGLE_CHAT_WEBHOOK_BASE_URL,
    GOOGLE_CHAT_KEY,
    GOOGLE_CHAT_TOKEN,
    REPORTS_BASE_URL
)

logger = logging.getLogger(__name__)


class GoogleChatPoster:
    """Posts formatted messages to Google Chat webhook"""

    # Rank emojis for top 3
    RANK_EMOJIS = ['🥇', '🥈', '🥉']

    def __init__(self, dry_run: bool = False):
        """Initialize Google Chat poster with configuration

        Args:
            dry_run: When True, print messages to stdout instead of sending
                     to Google Chat. Useful for previewing output locally.
        """
        self.dry_run = dry_run
        if not dry_run:
            self.webhook_url = self._construct_webhook_url()
        else:
            self.webhook_url = ""
            logger.info(
                "GoogleChatPoster running in DRY-RUN mode — messages will be printed, not sent")

    def _construct_webhook_url(self) -> str:
        """Construct full webhook URL with key and token.

        Not called in dry-run mode.

        Returns:
            Complete webhook URL

        Raises:
            ValueError: If required configuration is missing
        """
        if not GOOGLE_CHAT_WEBHOOK_BASE_URL:
            raise ValueError("GOOGLE_CHAT_WEBHOOK_BASE_URL not configured")
        if not GOOGLE_CHAT_KEY:
            raise ValueError("GOOGLE_CHAT_KEY not configured in environment")
        if not GOOGLE_CHAT_TOKEN:
            raise ValueError("GOOGLE_CHAT_TOKEN not configured in environment")

        url = f"{GOOGLE_CHAT_WEBHOOK_BASE_URL}?key={GOOGLE_CHAT_KEY}&token={GOOGLE_CHAT_TOKEN}"
        logger.debug(f"Constructed webhook URL (key/token hidden)")
        return url

    def _get_rank_emoji(self, rank: int) -> str:
        """Get emoji for given rank position

        Args:
            rank: Rank position (0-indexed)

        Returns:
            Emoji string or empty string if rank > 2
        """
        if rank < len(self.RANK_EMOJIS):
            return self.RANK_EMOJIS[rank]
        return ""

    def _format_leaderboard_section(
        self,
        title: str,
        contributors: List[Tuple[str, int]],
        metric_suffix: str
    ) -> str:
        """Format a leaderboard section with all contributors
        Shows badges (🥇🥈🥉) for top 3, then lists everyone else

        Args:
            title: Section title (e.g., "🏆 Top Contributors by Commits")
            contributors: List of (username, metric_value) tuples (all contributors)
            metric_suffix: Suffix for metric (e.g., "commits", "lines")

        Returns:
            Formatted section string
        """
        if not contributors:
            return f"**{title}**\nNo activity"

        lines = [f"**{title}**"]

        # Track current rank for handling ties
        current_rank = 0
        prev_value = None

        for idx, (username, value) in enumerate(contributors):
            # Handle ties: same value = same rank
            if prev_value is None or value != prev_value:
                current_rank = idx

            # Show emoji for top 3 positions only, otherwise use rank number
            if current_rank < 3:
                emoji = self._get_rank_emoji(current_rank)
                lines.append(f"{emoji} {username}: {value:,} {metric_suffix}")
            else:
                # For positions 4 and beyond, just show the number
                lines.append(
                    f"{current_rank + 1}. {username}: {value:,} {metric_suffix}")

            prev_value = value

        return "\n".join(lines)

    def format_leaderboard_message(
        self,
        period_type: str,
        date_string: str,
        contributors_by_impact: List[Tuple[str, Dict[str, int]]]
    ) -> str:
        """Format complete leaderboard message with new format

        Args:
            period_type: "Daily" or "Weekly"
            date_string: Formatted date or date range
            contributors_by_impact: List of (username, metrics_dict) tuples

        Returns:
            Formatted message string
        """
        # Check if there's any activity
        if not contributors_by_impact:
            return (
                f"📊 **{period_type} Leaderboard ({date_string})**\n\n"
                f"No activity for this period.\n\n"
                f"🔗 View all reports: {REPORTS_BASE_URL}"
            )

        # Build message with new format
        lines = [f"📊 **{period_type} Leaderboard ({date_string})**\n"]

        current_rank = 0
        prev_metrics = None

        for idx, (username, metrics) in enumerate(contributors_by_impact):
            issues_closed = metrics.get('issues_closed', 0)
            commit_count = metrics.get('commit_count', 0)
            total_loc = metrics.get('total_loc', 0)

            # Handle ties: same rank if all three metrics match
            if prev_metrics is None or (issues_closed, commit_count, total_loc) != prev_metrics:
                current_rank = idx

            # Show emoji for top 3 positions only
            if current_rank < 3:
                emoji = self._get_rank_emoji(current_rank)
                rank_prefix = emoji
            else:
                rank_prefix = f"{current_rank + 1}."

            # Format: 🥇 username - X issues closed / X commits / X lines of code
            issue_text = f"{issues_closed} issue{'s' if issues_closed != 1 else ''} closed" if issues_closed > 0 else "0 issues closed"
            lines.append(f"{rank_prefix} **{username}** - {issue_text}")
            lines.append(
                f"{commit_count} commit{'s' if commit_count != 1 else ''}")
            lines.append(f"{total_loc:,} lines of code")
            if idx < len(contributors_by_impact) - 1:
                lines.append("")  # Blank line between contributors

            prev_metrics = (issues_closed, commit_count, total_loc)

        lines.append(f"\n🔗 View all reports: {REPORTS_BASE_URL}")

        return "\n".join(lines)

    def post_message(self, message: str, max_retries: int = 3) -> bool:
        """Post message to Google Chat with retry logic.

        In dry-run mode the message is printed to stdout and True is returned
        without making any HTTP request.

        Args:
            message: Message text to post
            max_retries: Maximum number of retry attempts

        Returns:
            True if posted (or printed) successfully, False otherwise
        """
        if self.dry_run:
            separator = "=" * 70
            print(f"\n{separator}")
            print("[DRY-RUN] Message that would be sent to Google Chat:")
            print(separator)
            print(message)
            print(separator)
            return True

        payload = {"text": message}
        headers = {"Content-Type": "application/json"}

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Posting to Google Chat (attempt {attempt + 1}/{max_retries})")

                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=30
                )

                if response.status_code == 200:
                    logger.info("Successfully posted to Google Chat")
                    return True
                else:
                    logger.warning(
                        f"Google Chat API returned status {response.status_code}: "
                        f"{response.text}"
                    )

            except requests.exceptions.RequestException as e:
                logger.warning(f"Request failed: {e}")

            # Exponential backoff: 2s, 4s, 8s
            if attempt < max_retries - 1:
                wait_time = 2 ** (attempt + 1)
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)

        logger.error(
            f"Failed to post to Google Chat after {max_retries} attempts")
        return False

    def post_leaderboard(
        self,
        period_type: str,
        date_string: str,
        contributors_by_impact: List[Tuple[str, Dict[str, int]]]
    ) -> bool:
        """Format and post leaderboard to Google Chat

        Args:
            period_type: "Daily" or "Weekly"
            date_string: Formatted date or date range
            contributors_by_impact: List of (username, metrics_dict) tuples

        Returns:
            True if posted successfully, False otherwise
        """
        try:
            message = self.format_leaderboard_message(
                period_type,
                date_string,
                contributors_by_impact
            )

            logger.debug(
                f"Formatted {period_type.lower()} leaderboard message:\n{message}")

            return self.post_message(message)

        except Exception as e:
            logger.error(f"Error posting leaderboard: {e}", exc_info=True)
            return False

    def format_commits_breakdown_message(
        self,
        period_type: str,
        date_string: str,
        leaderboard_order: List[Tuple[str, Dict[str, int]]],
        user_commits: dict,
        user_issues: dict
    ) -> str:
        """Format detailed commit and issue breakdown message

        Args:
            period_type: "Daily" or "Weekly"
            date_string: Formatted date or date range
            leaderboard_order: List of (username, metrics_dict) tuples in leaderboard order
            user_commits: Dict mapping username to list of commit dicts
            user_issues: Dict mapping username to list of issue dicts

        Returns:
            Formatted message string
        """
        if not leaderboard_order:
            return f"📝 **{period_type} Commit & Issue Details ({date_string})**\n\nNo activity for this period."

        message_parts = [
            f"📝 **{period_type} Commit & Issue Details ({date_string})**\n"]

        current_rank = 0
        prev_metrics = None

        for idx, (username, metrics) in enumerate(leaderboard_order):
            issues_closed = metrics.get('issues_closed', 0)
            commit_count = metrics.get('commit_count', 0)
            total_loc = metrics.get('total_loc', 0)

            # Handle ties: same rank if all three metrics match
            if prev_metrics is None or (issues_closed, commit_count, total_loc) != prev_metrics:
                current_rank = idx

            # Show emoji for top 3 positions
            if current_rank < 3:
                emoji = self._get_rank_emoji(current_rank)
                rank_prefix = emoji
            else:
                rank_prefix = f"{current_rank + 1}."

            message_parts.append(f"\n{rank_prefix} **{username}**")

            # Show issues first if any
            issues = user_issues.get(username, [])
            if issues:
                message_parts.append(f"  **Issues Closed ({len(issues)}):**")
                for issue in issues[:20]:  # Limit to first 20 issues
                    issue_num = issue.get('number', '?')
                    issue_title = issue.get('title', 'Untitled')[:60]
                    issue_url = issue.get('url', '')
                    repo = issue.get('repository', '').split(
                        '/')[-1] if issue.get('repository') else 'unknown'
                    message_parts.append(
                        f"  • [{repo}#{issue_num}: {issue_title}]({issue_url})")
                if len(issues) > 20:
                    message_parts.append(
                        f"  • ... and {len(issues) - 20} more issues")

            prev_metrics = (issues_closed, commit_count, total_loc)

            # Show commits
            commits = user_commits.get(username, [])
            if commits:
                message_parts.append(f"  **Commits ({len(commits)}):**")
                for commit in commits[:20]:  # Limit to first 20 commits
                    sha_short = commit.get('sha', 'unknown')[:7]
                    message = commit.get('message', 'No message')[:60]
                    repo = commit.get('repository', '').split(
                        '/')[-1] if commit.get('repository') else 'unknown'
                    sha_full = commit.get('sha', '')
                    repo_full = commit.get('repository', '')
                    commit_url = f"https://github.com/{repo_full}/commit/{sha_full}" if repo_full and sha_full else ''
                    loc = commit.get('total_loc', 0)
                    message_parts.append(
                        f"  • [{repo} {sha_short}]({commit_url}): {message} ({loc:,} LOC)")
                if len(commits) > 20:
                    message_parts.append(
                        f"  • ... and {len(commits) - 20} more commits")
            elif not issues:
                message_parts.append("  No commits or issues")

            prev_issues = issues_closed

        return "\n".join(message_parts)

    def post_commits_breakdown(
        self,
        period_type: str,
        date_string: str,
        leaderboard_order: List[Tuple[str, Dict[str, int]]],
        user_commits: dict,
        user_issues: dict
    ) -> bool:
        """Format and post detailed breakdown to Google Chat

        Args:
            period_type: "Daily" or "Weekly"
            date_string: Formatted date or date range
            leaderboard_order: List of (username, metrics_dict) tuples in leaderboard order
            user_commits: Dict mapping username to list of commit dicts
            user_issues: Dict mapping username to list of issue dicts

        Returns:
            True if posted successfully, False otherwise
        """
        try:
            message = self.format_commits_breakdown_message(
                period_type,
                date_string,
                leaderboard_order,
                user_commits,
                user_issues
            )

            logger.debug(
                f"Formatted {period_type.lower()} commits breakdown message"
            )

            return self.post_message(message)

        except Exception as e:
            logger.error(
                f"Error posting commits breakdown: {e}", exc_info=True)
            return False
