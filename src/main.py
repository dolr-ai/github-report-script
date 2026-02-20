#!/usr/bin/env python3
"""
GitHub Report Script - Main Entry Point

Configuration can be set in src/config.py or overridden via command-line arguments.

Examples:
    python src/main.py                               # Use config.py settings (default: fetch_and_leaderboard)
    python src/main.py --mode fetch                  # Fetch only
    python src/main.py --mode refresh --days 90      # Refresh last 90 days
    python src/main.py --mode status                 # Show status
    python src/main.py --mode leaderboard            # Post leaderboard to Google Chat
    python src/main.py --mode fetch_and_leaderboard  # Fetch data and post leaderboard
"""
import sys
import os
import argparse
from datetime import datetime
import logging

# Setup Python path BEFORE any src imports
# This MUST be first or imports will fail
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# fmt: off - DO NOT REORDER THESE IMPORTS
from src.config import MODE, ExecutionMode, DATE_RANGE_MODE, DateRangeMode, USER_IDS, THREAD_COUNT, GITHUB_ORG, DATA_RETENTION_DAYS, validate_config, display_config, get_date_range, IST_TIMEZONE
from src.github_fetcher import GitHubFetcher
from src.leaderboard_generator import LeaderboardGenerator
from src.google_chat_poster import GoogleChatPoster
from src.cache_manager import CacheManager
# fmt: on

logger = logging.getLogger(__name__)


def cmd_fetch():
    """Fetch commits and cache them"""
    print(display_config())
    logger.info("Starting FETCH mode")

    # Clean up old data (older than DATA_RETENTION_DAYS)
    cache_manager = CacheManager()
    cache_manager.cleanup_old_data(days_to_keep=DATA_RETENTION_DAYS)

    # Get date range
    start_date, end_date = get_date_range()
    logger.info(f"Date range: {start_date.date()} to {end_date.date()}")

    # Fetch commits
    logger.info("Initializing GitHub fetcher")
    fetcher = GitHubFetcher(thread_count=THREAD_COUNT)
    fetcher.fetch_commits(start_date, end_date, USER_IDS, force_refresh=False)

    print("\n" + "=" * 70)
    print("✓ Fetch complete! Data saved to cache/")
    print("=" * 70)


def cmd_refresh():
    """Refresh cache for specific date range"""
    print(display_config())
    logger.info("Starting REFRESH mode")

    # Clean up old data (older than DATA_RETENTION_DAYS)
    cache_manager = CacheManager()
    cache_manager.cleanup_old_data(days_to_keep=DATA_RETENTION_DAYS)

    # Get date range
    start_date, end_date = get_date_range()
    logger.info(
        f"Refresh date range: {start_date.date()} to {end_date.date()}")
    print(
        f"Refreshing cache for: {start_date.date()} to {end_date.date()}\n")

    # Fetch commits with force refresh
    fetcher = GitHubFetcher(thread_count=THREAD_COUNT)
    fetcher.fetch_commits(start_date, end_date, USER_IDS, force_refresh=True)

    print("\n" + "=" * 70)
    print("✓ Refresh complete! Cache updated")
    print("=" * 70)


def cmd_status():
    """Show current status and rate limit"""
    print(display_config())
    logger.info("Starting STATUS mode")

    # Get rate limit
    logger.debug("Fetching rate limit information")
    fetcher = GitHubFetcher()
    rate_limits = fetcher.get_rate_limit_status()

    if 'error' in rate_limits:
        print(f"GitHub API Rate Limit: {rate_limits['error']}")
    else:
        print("GitHub API Rate Limits:")
        print()

        # Display GraphQL rate limit
        if 'graphql' in rate_limits:
            rl = rate_limits['graphql']
            print(f"  GraphQL API:")
            print(f"    Remaining: {rl['remaining']:>5} / {rl['limit']}")
            print(f"    Resets at: {rl['reset']}")
            if rl['seconds_until_reset'] > 0:
                mins = rl['seconds_until_reset'] // 60
                secs = rl['seconds_until_reset'] % 60
                print(f"    Resets in: {mins}m {secs}s")
            print()

        # Display Core (REST) API rate limit
        if 'core' in rate_limits:
            rl = rate_limits['core']
            print(f"  Core (REST) API:")
            print(f"    Remaining: {rl['remaining']:>5} / {rl['limit']}")
            print(f"    Resets at: {rl['reset']}")
            if rl['seconds_until_reset'] > 0:
                mins = rl['seconds_until_reset'] // 60
                secs = rl['seconds_until_reset'] % 60
                print(f"    Resets in: {mins}m {secs}s")
            print()

        # Display Search API rate limit
        if 'search' in rate_limits:
            rl = rate_limits['search']
            print(f"  Search API:")
            print(f"    Remaining: {rl['remaining']:>5} / {rl['limit']}")
            print(f"    Resets at: {rl['reset']}")
            if rl['seconds_until_reset'] > 0:
                mins = rl['seconds_until_reset'] // 60
                secs = rl['seconds_until_reset'] % 60
                print(f"    Resets in: {mins}m {secs}s")
            print()

        # Display Code Search API rate limit
        if 'code_search' in rate_limits:
            rl = rate_limits['code_search']
            print(f"  Code Search API:")
            print(f"    Remaining: {rl['remaining']:>5} / {rl['limit']}")
            print(f"    Resets at: {rl['reset']}")
            if rl['seconds_until_reset'] > 0:
                mins = rl['seconds_until_reset'] // 60
                secs = rl['seconds_until_reset'] % 60
                print(f"    Resets in: {mins}m {secs}s")
            print()

    print()

    # Check cache status
    from src.cache_manager import CacheManager
    cache_manager = CacheManager()
    cached_dates = cache_manager.get_cached_dates()

    if cached_dates:
        print(f"Cached dates: {len(cached_dates)}")
        print(f"  Range: {cached_dates[0]} to {cached_dates[-1]}")
    else:
        print("No cached data found.")
    print()

    print("\n" + "=" * 70)


def cmd_leaderboard(dry_run: bool = False, test_channel: bool = False):
    """Generate and post daily/weekly leaderboards to Google Chat

    Args:
        dry_run: When True, print messages to stdout instead of sending them.
        test_channel: When True, post to the test Google Chat channel.
    """
    if MODE == ExecutionMode.LEADERBOARD:
        print(display_config())
    if dry_run:
        print(
            "[DRY-RUN] Leaderboard messages will be printed, not sent to Google Chat\n")
    if test_channel and not dry_run:
        print(
            "[TEST CHANNEL] Leaderboard will be posted to the test Google Chat channel\n")
    logger.info("Starting LEADERBOARD mode%s", " (dry-run)" if dry_run else "")

    try:
        # Initialize components
        cache_manager = CacheManager()
        leaderboard_generator = LeaderboardGenerator(cache_manager)
        chat_poster = GoogleChatPoster(
            dry_run=dry_run, test_channel=test_channel)

        # Determine if today is Monday (post weekly) or other days (post daily)
        should_post_weekly = leaderboard_generator.should_post_weekly()

        if should_post_weekly:
            logger.info("Monday detected - generating weekly leaderboard")
            print("Generating weekly leaderboard for last 7 days...\n")

            # Generate weekly leaderboard
            contributors_by_impact, date_string = leaderboard_generator.generate_weekly_leaderboard()

            # Post to Google Chat
            success = chat_poster.post_leaderboard(
                period_type="Weekly",
                date_string=date_string,
                contributors_by_impact=contributors_by_impact
            )

            if success:
                # Get commit and issue details, post breakdown as second message
                date_strings = leaderboard_generator.get_last_7_days_ist()
                user_commits = leaderboard_generator.get_commits_breakdown(
                    date_strings, contributors_by_impact)
                user_issues = leaderboard_generator.get_issues_breakdown(
                    date_strings, contributors_by_impact)

                # Post the detailed breakdown
                breakdown_success = chat_poster.post_commits_breakdown(
                    period_type="Weekly",
                    date_string=date_string,
                    leaderboard_order=contributors_by_impact,
                    user_commits=user_commits,
                    user_issues=user_issues
                )

                if breakdown_success:
                    logger.info("Successfully posted commits breakdown")
                else:
                    logger.warning("Failed to post commits breakdown")

                print("\n" + "=" * 70)
                print("✓ Weekly leaderboard posted to Google Chat!")
                print("=" * 70)
            else:
                logger.warning(
                    "Failed to post weekly leaderboard to Google Chat")
                print("\n" + "=" * 70)
                print("⚠️  Failed to post weekly leaderboard to Google Chat")
                print("   Check logs for details")
                print("=" * 70)

        else:
            logger.info("Weekday detected - generating daily leaderboard")
            print("Generating daily leaderboard for yesterday...\n")

            # Generate daily leaderboard
            contributors_by_impact, date_string = leaderboard_generator.generate_daily_leaderboard()

            # Post to Google Chat
            success = chat_poster.post_leaderboard(
                period_type="Daily",
                date_string=date_string,
                contributors_by_impact=contributors_by_impact
            )

            if success:
                # Get commit and issue details, post breakdown as second message
                date_strings = [leaderboard_generator.get_yesterday_ist()]
                user_commits = leaderboard_generator.get_commits_breakdown(
                    date_strings, contributors_by_impact)
                user_issues = leaderboard_generator.get_issues_breakdown(
                    date_strings, contributors_by_impact)

                # Post the detailed breakdown
                breakdown_success = chat_poster.post_commits_breakdown(
                    period_type="Daily",
                    date_string=date_string,
                    leaderboard_order=contributors_by_impact,
                    user_commits=user_commits,
                    user_issues=user_issues
                )

                if breakdown_success:
                    logger.info("Successfully posted commits breakdown")
                else:
                    logger.warning("Failed to post commits breakdown")

                print("\n" + "=" * 70)
                print("✓ Daily leaderboard posted to Google Chat!")
                print("=" * 70)
            else:
                logger.warning(
                    "Failed to post daily leaderboard to Google Chat")
                print("\n" + "=" * 70)
                print("⚠️  Failed to post daily leaderboard to Google Chat")
                print("   Check logs for details")
                print("=" * 70)

    except Exception as e:
        logger.error(
            f"Error generating/posting leaderboard: {e}", exc_info=True)
        print("\n" + "=" * 70)
        print(f"❌ Error: {e}")
        print("   Leaderboard posting failed but will not block workflow")
        print("=" * 70)
        # Don't raise - allow workflow to continue


def cmd_fetch_and_leaderboard(dry_run: bool = False, test_channel: bool = False):
    """Fetch commits, cache them, then generate and post leaderboards.

    This is the default CI mode: it combines FETCH and LEADERBOARD in a single
    run so that the leaderboard always reflects the freshly-fetched data.

    Args:
        dry_run: When True, print leaderboard messages to stdout instead of
                 sending them to Google Chat.
        test_channel: When True, post to the test Google Chat channel.
    """
    logger.info("Starting FETCH_AND_LEADERBOARD mode")
    cmd_fetch()
    cmd_leaderboard(dry_run=dry_run, test_channel=test_channel)


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='GitHub Report Script - Fetch commits and post leaderboards',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/main.py                               # Default: fetch_and_leaderboard
  python src/main.py --mode fetch                  # Fetch only
  python src/main.py --mode refresh --days 90      # Force refresh last 90 days
  python src/main.py --mode status                 # Check cache status
  python src/main.py --mode leaderboard            # Post leaderboard to Google Chat (daily/weekly)
  python src/main.py --mode fetch_and_leaderboard  # Fetch data and post leaderboard (combined)
  python src/main.py --mode leaderboard --dry-run  # Preview leaderboard without sending
  python src/main.py --mode leaderboard --test-channel  # Post to the test Google Chat channel

Note: Arguments override settings in src/config.py
        """
    )

    parser.add_argument(
        '--mode',
        type=str,
        choices=['fetch', 'refresh', 'status',
                 'leaderboard', 'fetch_and_leaderboard'],
        help='Execution mode (default: from config.py, typically fetch_and_leaderboard)'
    )

    parser.add_argument(
        '--days',
        type=int,
        help='Number of days back to process (default: from config.py, typically 30)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help='Print leaderboard messages to stdout instead of sending to Google Chat'
    )

    parser.add_argument(
        '--test-channel',
        action='store_true',
        default=False,
        help='Post leaderboard to the test Google Chat channel instead of production'
    )

    return parser.parse_args()


def main():
    """Main entry point - runs the configured mode"""
    # Parse command-line arguments
    args = parse_args()

    # Override config with command-line arguments
    global MODE, DAYS_BACK

    if args.mode:
        mode_map = {
            'fetch': ExecutionMode.FETCH,
            'refresh': ExecutionMode.REFRESH,
            'status': ExecutionMode.STATUS,
            'leaderboard': ExecutionMode.LEADERBOARD,
            'fetch_and_leaderboard': ExecutionMode.FETCH_AND_LEADERBOARD,
        }
        MODE = mode_map[args.mode]
        logger.info(f"Mode overridden via CLI: {args.mode}")

    if args.days:
        import src.config as config
        config.DAYS_BACK = args.days
        DAYS_BACK = args.days
        logger.info(f"DAYS_BACK overridden via CLI: {args.days}")

    try:
        # Validate configuration
        validate_config()

        # Execute based on configured mode
        if MODE == ExecutionMode.FETCH:
            cmd_fetch()
        elif MODE == ExecutionMode.REFRESH:
            cmd_refresh()
        elif MODE == ExecutionMode.STATUS:
            cmd_status()
        elif MODE == ExecutionMode.LEADERBOARD:
            cmd_leaderboard(dry_run=args.dry_run,
                            test_channel=args.test_channel)
        elif MODE == ExecutionMode.FETCH_AND_LEADERBOARD:
            cmd_fetch_and_leaderboard(
                dry_run=args.dry_run, test_channel=args.test_channel)
        else:
            print(f"❌ Unknown execution mode: {MODE}")
            sys.exit(1)

    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
