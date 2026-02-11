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

    def __init__(self):
        """Initialize Google Chat poster with configuration"""
        self.webhook_url = self._construct_webhook_url()

    def _construct_webhook_url(self) -> str:
        """Construct full webhook URL with key and token

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
        top_by_commits: List[Tuple[str, int]],
        top_by_loc: List[Tuple[str, int]]
    ) -> str:
        """Format complete leaderboard message

        Args:
            period_type: "Daily" or "Weekly"
            date_string: Formatted date or date range
            top_by_commits: List of (username, commit_count) tuples
            top_by_loc: List of (username, total_loc) tuples

        Returns:
            Formatted message string
        """
        # Check if there's any activity
        if not top_by_commits and not top_by_loc:
            return (
                f"📊 **{period_type} Leaderboard ({date_string})**\n\n"
                f"No activity for this period.\n\n"
                f"🔗 View all reports: {REPORTS_BASE_URL}"
            )

        # Build message with both sections
        message_parts = [
            f"📊 **{period_type} Leaderboard ({date_string})**\n",
            self._format_leaderboard_section(
                "🏆 Top Contributors by Commits",
                top_by_commits,
                "commits"
            ),
            "\n",
            self._format_leaderboard_section(
                "📈 Top Contributors by Lines Changed",
                top_by_loc,
                "lines"
            ),
            f"\n\n🔗 View all reports: {REPORTS_BASE_URL}"
        ]

        return "\n".join(message_parts)

    def post_message(self, message: str, max_retries: int = 3) -> bool:
        """Post message to Google Chat with retry logic

        Args:
            message: Message text to post
            max_retries: Maximum number of retry attempts

        Returns:
            True if posted successfully, False otherwise
        """
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
        top_by_commits: List[Tuple[str, int]],
        top_by_loc: List[Tuple[str, int]]
    ) -> bool:
        """Format and post leaderboard to Google Chat

        Args:
            period_type: "Daily" or "Weekly"
            date_string: Formatted date or date range
            top_by_commits: List of (username, commit_count) tuples
            top_by_loc: List of (username, total_loc) tuples

        Returns:
            True if posted successfully, False otherwise
        """
        try:
            message = self.format_leaderboard_message(
                period_type,
                date_string,
                top_by_commits,
                top_by_loc
            )

            logger.debug(
                f"Formatted {period_type.lower()} leaderboard message:\n{message}")

            return self.post_message(message)

        except Exception as e:
            logger.error(f"Error posting leaderboard: {e}", exc_info=True)
            return False
