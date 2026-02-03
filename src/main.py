#!/usr/bin/env python3
"""
GitHub Report Script - Main Entry Point

No command-line arguments needed. All configuration is in src/config.py
Simply run: python src/main.py
"""
import sys
from datetime import datetime

from config import (
    MODE, ExecutionMode, DATE_RANGE_MODE, DateRangeMode,
    USER_IDS, THREAD_COUNT, GITHUB_ORG,
    validate_config, display_config, get_date_range
)
from github_fetcher import GitHubFetcher
from data_processor import DataProcessor
from chart_generator import ChartGenerator


def cmd_fetch():
    """Fetch commits, cache, and process to output directory"""
    print(display_config())

    # Get date range
    start_date, end_date = get_date_range()

    # Fetch commits
    print("Starting data fetch...")
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

    # Get date range
    start_date, end_date = get_date_range()
    print(
        f"Refreshing cache and output for: {start_date.date()} to {end_date.date()}\n")

    # Fetch commits with force refresh
    fetcher = GitHubFetcher(thread_count=THREAD_COUNT)
    fetcher.fetch_commits(start_date, end_date, USER_IDS, force_refresh=True)

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

    # Get date range
    if DATE_RANGE_MODE == DateRangeMode.ALL_CACHED:
        # Use all available cached data
        from cache_manager import CacheManager
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

    # Get rate limit
    fetcher = GitHubFetcher()
    rate_limit = fetcher.get_rate_limit_status()
    print("GitHub API Rate Limit:")
    print(f"  Remaining: {rate_limit['remaining']}/{rate_limit['limit']}")
    print(f"  Resets at: {rate_limit['reset']}")
    print()

    # Check cache status
    from cache_manager import CacheManager
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
    from config import OUTPUT_DIR

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


def main():
    """Main entry point - runs the configured mode"""
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
