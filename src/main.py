#!/usr/bin/env python3
"""
GitHub Report Script - Main Entry Point

Configuration can be set in src/config.py or overridden via command-line arguments.

Examples:
    python src/main.py                          # Use config.py settings (default: fetch and chart)
    python src/main.py --mode fetch             # Fetch only
    python src/main.py --mode refresh --days 90 # Refresh last 90 days
    python src/main.py --mode chart             # Generate charts only
    python src/main.py --mode status            # Show status
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
from src.data_processor import DataProcessor
from src.chart_generator import ChartGenerator
from src.leaderboard_generator import LeaderboardGenerator
from src.google_chat_poster import GoogleChatPoster
from src.cache_manager import CacheManager
# fmt: on

logger = logging.getLogger(__name__)


def cmd_fetch():
    """Fetch commits, cache, and process to output directory"""
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

    # Process data
    processor = DataProcessor()
    processor.process_date_range(
        start_date, end_date, USER_IDS, force_refresh=False)

    # Show summary
    print("\n" + "=" * 70)
    print("Summary Statistics")
    print("=" * 70)
    summary = processor.get_summary_stats(USER_IDS, start_date, end_date)

    for username, stats in summary['users'].items():
        print(f"\n{username}:")
        print(f"  Total commits:     {stats['total_commits']}")
        print(f"  Lines added:       {stats['total_additions']:,}")
        print(f"  Lines deleted:     {stats['total_deletions']:,}")
        print(f"  Total LOC changed: {stats['total_loc']:,}")
        print(f"  Repositories:      {stats['unique_repositories']}")

    print("\n" + "=" * 70)
    print("✓ Fetch complete! Data saved to cache/ and output/")
    print("  Run with MODE = ExecutionMode.CHART to generate visualizations")
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

    # Handle ALL_CACHED mode (just reprocess existing cache)
    if start_date is None and end_date is None:
        logger.info("Reprocessing all cached dates")
        print("Reprocessing all cached dates\n")

        # Just process data (don't fetch)
        processor = DataProcessor()
        processor.process_date_range(
            start_date, end_date, USER_IDS, force_refresh=True)
    else:
        logger.info(
            f"Refresh date range: {start_date.date()} to {end_date.date()}")
        print(
            f"Refreshing cache and output for: {start_date.date()} to {end_date.date()}\n")

        # Fetch commits with force refresh
        fetcher = GitHubFetcher(thread_count=THREAD_COUNT)
        fetcher.fetch_commits(start_date, end_date,
                              USER_IDS, force_refresh=True)

        # Process data with force refresh
        processor = DataProcessor()
        processor.process_date_range(
            start_date, end_date, USER_IDS, force_refresh=True)

    print("\n" + "=" * 70)
    print("✓ Refresh complete! Cache and output updated")
    print("=" * 70)


def cmd_chart():
    """Generate charts from processed data"""
    print(display_config())
    logger.info("Starting CHART mode")

    # Get date range
    if DATE_RANGE_MODE == DateRangeMode.ALL_CACHED:
        # Use all available cached data
        from src.cache_manager import CacheManager
        cache_manager = CacheManager()
        cached_dates = cache_manager.get_cached_dates()

        if not cached_dates:
            print("\n❌ No cached data found. Run with MODE = ExecutionMode.FETCH first.")
            sys.exit(1)

        start_date = datetime.strptime(cached_dates[0], '%Y-%m-%d')
        end_date = datetime.strptime(cached_dates[-1], '%Y-%m-%d')
        print(
            f"\nUsing all cached dates: {start_date.date()} to {end_date.date()}\n")
    else:
        start_date, end_date = get_date_range()

    # Read processed data
    processor = DataProcessor()
    all_data = processor.read_all_users_data(USER_IDS, start_date, end_date)

    # Check if we have any data
    has_data = any(
        any(day_data.get('commit_count', 0) >
            0 for day_data in user_data.values())
        for user_data in all_data.values()
    )

    if not has_data:
        print("\n❌ No commit data found for the specified date range.")
        print("   Run with MODE = ExecutionMode.FETCH first to collect data.")
        sys.exit(1)

    # Generate charts
    generator = ChartGenerator()
    results = generator.generate_all_charts(
        all_data,
        start_date.date().isoformat(),
        end_date.date().isoformat()
    )

    print("\n" + "=" * 70)
    print("✓ Charts generated successfully!")
    print("=" * 70)


def cmd_status():
    """Show current status and rate limit"""
    print(display_config())
    logger.info("Starting STATUS mode")

    # Get rate limit
    logger.debug("Fetching rate limit information")
    fetcher = GitHubFetcher()
    rate_limit = fetcher.get_rate_limit_status()
    print("GitHub API Rate Limit:")
    print(f"  Remaining: {rate_limit['remaining']}/{rate_limit['limit']}")
    print(f"  Resets at: {rate_limit['reset']}")
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

    # Check output status
    import os
    from src.config import OUTPUT_DIR

    if os.path.exists(OUTPUT_DIR):
        user_dirs = [d for d in os.listdir(OUTPUT_DIR)
                     if os.path.isdir(os.path.join(OUTPUT_DIR, d))]
        if user_dirs:
            print(f"Processed users: {len(user_dirs)}")
            for user_dir in sorted(user_dirs):
                user_path = os.path.join(OUTPUT_DIR, user_dir)
                file_count = len([f for f in os.listdir(
                    user_path) if f.endswith('.json')])
                print(f"  {user_dir}: {file_count} date(s)")
        else:
            print("No processed data found.")
    else:
        print("No processed data found.")

    print("\n" + "=" * 70)


def cmd_refresh_stats():
    """Refresh only GitHub contributor stats without re-fetching commits"""
    print(display_config())
    logger.info("Starting REFRESH_STATS mode")

    # Get date range
    start_date, end_date = get_date_range()
    logger.info(f"Date range: {start_date.date()} to {end_date.date()}")

    print(
        f"\nRefreshing GitHub contributor stats for: {start_date.date()} to {end_date.date()}")
    print("This will update contributor_stats in cache without re-fetching commits.\n")

    # Refresh stats
    fetcher = GitHubFetcher(thread_count=THREAD_COUNT)
    fetcher.refresh_contributor_stats(start_date, end_date, USER_IDS)

    print("\n" + "=" * 70)
    print("✓ GitHub stats refresh complete!")
    print("  Run with --mode chart to generate updated charts")
    print("=" * 70)


def cmd_fetch_and_chart():
    """Combined mode: Fetch data and immediately generate charts"""
    print(display_config())
    logger.info("Starting FETCH_AND_CHART mode (combined operation)")

    # Clean up old data (older than DATA_RETENTION_DAYS)
    cache_manager = CacheManager()
    cache_manager.cleanup_old_data(days_to_keep=DATA_RETENTION_DAYS)

    # Get date range
    start_date, end_date = get_date_range()
    logger.info(f"Date range: {start_date.date()} to {end_date.date()}")

    # Step 1: Fetch commits
    logger.info("Step 1/3: Fetching commits from GitHub")
    fetcher = GitHubFetcher(thread_count=THREAD_COUNT)
    fetcher.fetch_commits(start_date, end_date, USER_IDS, force_refresh=False)

    # Step 2: Process data
    logger.info("Step 2/3: Processing and aggregating data")
    processor = DataProcessor()
    processor.process_date_range(
        start_date, end_date, USER_IDS, force_refresh=False)

    # Step 3: Generate charts
    logger.info("Step 3/3: Generating charts")
    all_data = processor.read_all_users_data(USER_IDS, start_date, end_date)

    if not all_data or all(not data for data in all_data.values()):
        print("\n❌ No data available to generate charts.")
        print("   Run with MODE = ExecutionMode.FETCH first.")
        sys.exit(1)

    generator = ChartGenerator()
    results = generator.generate_all_charts(
        all_data,
        start_date.date().isoformat(),
        end_date.date().isoformat()
    )

    print("\n" + "=" * 70)
    print("✓ FETCH_AND_CHART complete!")
    print("  Data fetched, processed, and charts generated")
    print("=" * 70)


def cmd_fetch_and_leaderboard():
    """Combined mode: Fetch data and immediately post leaderboard"""
    print(display_config())
    logger.info("Starting FETCH_AND_LEADERBOARD mode (combined operation)")

    # Clean up old data (older than DATA_RETENTION_DAYS)
    cache_manager = CacheManager()
    cache_manager.cleanup_old_data(days_to_keep=DATA_RETENTION_DAYS)

    # Get date range
    start_date, end_date = get_date_range()
    logger.info(f"Date range: {start_date.date()} to {end_date.date()}")

    # Step 1: Fetch commits
    logger.info("Step 1/3: Fetching commits from GitHub")
    fetcher = GitHubFetcher(thread_count=THREAD_COUNT)
    fetcher.fetch_commits(start_date, end_date, USER_IDS, force_refresh=False)

    # Step 2: Process data
    logger.info("Step 2/3: Processing and aggregating data")
    processor = DataProcessor()
    processor.process_date_range(
        start_date, end_date, USER_IDS, force_refresh=False)

    # Step 3: Post leaderboard
    logger.info("Step 3/3: Posting leaderboard to Google Chat")
    cmd_leaderboard()

    print("\n" + "=" * 70)
    print("✓ FETCH_AND_LEADERBOARD complete!")
    print("  Data fetched, processed, and leaderboard posted")
    print("=" * 70)


def cmd_leaderboard():
    """Generate and post daily/weekly leaderboards to Google Chat"""
    if MODE == ExecutionMode.LEADERBOARD:
        print(display_config())
    logger.info("Starting LEADERBOARD mode")

    try:
        # Initialize components
        cache_manager = CacheManager()
        leaderboard_generator = LeaderboardGenerator(cache_manager)
        chat_poster = GoogleChatPoster()

        # Determine if today is Sunday (post weekly) or weekday (post daily)
        is_sunday = leaderboard_generator.is_sunday()

        if is_sunday:
            logger.info("Sunday detected - generating weekly leaderboard")
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


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='GitHub Report Script - Fetch commits and generate productivity reports',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/main.py                          # Default: fetch and chart last 30 days
  python src/main.py --mode fetch             # Fetch only
  python src/main.py --mode refresh --days 90 # Force refresh last 90 days
  python src/main.py --mode chart             # Generate charts from existing data
  python src/main.py --mode status            # Check cache status
  python src/main.py --mode refresh-stats     # Refresh GitHub stats only (no commits fetch)
  python src/main.py --mode leaderboard       # Post leaderboard to Google Chat (daily/weekly)
  python src/main.py --mode fetch_and_leaderboard  # Fetch data and post leaderboard (combined)

Note: Arguments override settings in src/config.py
        """
    )

    parser.add_argument(
        '--mode',
        type=str,
        choices=['fetch', 'refresh', 'chart', 'status',
                 'fetch_and_chart', 'refresh-stats', 'leaderboard', 'fetch_and_leaderboard'],
        help='Execution mode (default: from config.py, typically fetch_and_chart)'
    )

    parser.add_argument(
        '--days',
        type=int,
        help='Number of days back to process (default: from config.py, typically 30)'
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
            'chart': ExecutionMode.CHART,
            'status': ExecutionMode.STATUS,
            'fetch_and_chart': ExecutionMode.FETCH_AND_CHART,
            'leaderboard': ExecutionMode.LEADERBOARD,
            'fetch_and_leaderboard': ExecutionMode.FETCH_AND_LEADERBOARD,
            'refresh-stats': 'REFRESH_STATS'  # Special mode
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
        elif MODE == ExecutionMode.CHART:
            cmd_chart()
        elif MODE == ExecutionMode.STATUS:
            cmd_status()
        elif MODE == ExecutionMode.FETCH_AND_CHART:
            cmd_fetch_and_chart()
        elif MODE == ExecutionMode.LEADERBOARD:
            cmd_leaderboard()
        elif MODE == ExecutionMode.FETCH_AND_LEADERBOARD:
            cmd_fetch_and_leaderboard()
        elif MODE == 'REFRESH_STATS':
            cmd_refresh_stats()
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
