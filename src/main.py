#!/usr/bin/env python3
"""
GitHub Report Script - Main CLI
Fetch GitHub commits and lines of code, generate comparative visualizations
"""
import sys
import argparse
from datetime import datetime, timedelta

from src.config import (
    USER_IDS, DEFAULT_THREAD_COUNT, DEFAULT_DAYS_BACK,
    GITHUB_ORG, validate_config
)
from src.github_fetcher import GitHubFetcher
from src.data_processor import DataProcessor
from src.chart_generator import ChartGenerator


def parse_date(date_str: str) -> datetime:
    """Parse date string in YYYY-MM-DD format

    Args:
        date_str: Date string

    Returns:
        datetime object
    """
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError(
            f"Invalid date format: {date_str}. Use YYYY-MM-DD format.")


def get_date_range(args) -> tuple:
    """Get start and end dates from arguments

    Args:
        args: Parsed command line arguments

    Returns:
        Tuple of (start_date, end_date) datetime objects
    """
    if args.start_date and args.end_date:
        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date)
    elif args.start_date:
        start_date = parse_date(args.start_date)
        end_date = datetime.now()
    elif args.end_date:
        end_date = parse_date(args.end_date)
        start_date = end_date - timedelta(days=DEFAULT_DAYS_BACK - 1)
    else:
        # Default: last N days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=DEFAULT_DAYS_BACK - 1)

    # Ensure start is before end
    if start_date > end_date:
        raise ValueError("Start date must be before end date")

    return start_date, end_date


def cmd_fetch(args):
    """Fetch commits, cache, and process to output directory"""
    print("=" * 70)
    print("GitHub Report Script - Fetch Mode")
    print("=" * 70)
    print(f"Organization: {GITHUB_ORG}")
    print(f"Users: {', '.join(USER_IDS)}")
    print(f"Threads: {args.threads}")

    # Get date range
    start_date, end_date = get_date_range(args)
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print()

    # Fetch commits
    fetcher = GitHubFetcher(thread_count=args.threads)
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
    print("Fetch complete! Use 'chart' command to generate visualizations.")
    print("=" * 70)


def cmd_refresh(args):
    """Refresh cache for specific date range"""
    print("=" * 70)
    print("GitHub Report Script - Refresh Mode")
    print("=" * 70)
    print(f"Organization: {GITHUB_ORG}")
    print(f"Users: {', '.join(USER_IDS)}")
    print(f"Threads: {args.threads}")

    # Get date range
    start_date, end_date = get_date_range(args)
    print(f"Refreshing date range: {start_date.date()} to {end_date.date()}")
    print()

    # Fetch commits with force refresh
    fetcher = GitHubFetcher(thread_count=args.threads)
    fetcher.fetch_commits(start_date, end_date, USER_IDS, force_refresh=True)

    # Process data with force refresh
    processor = DataProcessor()
    processor.process_date_range(
        start_date, end_date, USER_IDS, force_refresh=True)

    print("\n" + "=" * 70)
    print("Refresh complete!")
    print("=" * 70)


def cmd_chart(args):
    """Generate charts from processed data"""
    print("=" * 70)
    print("GitHub Report Script - Chart Mode")
    print("=" * 70)
    print(f"Users: {', '.join(USER_IDS)}")

    # Get date range
    start_date, end_date = get_date_range(args)
    print(f"Date range: {start_date.date()} to {end_date.date()}")

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
        print("\nWarning: No commit data found for the specified date range.")
        print("Run 'fetch' command first to collect data.")
        return

    # Generate charts
    generator = ChartGenerator()
    results = generator.generate_all_charts(
        all_data,
        start_date.date().isoformat(),
        end_date.date().isoformat()
    )

    print("\n" + "=" * 70)
    print("Chart generation complete!")
    print("=" * 70)


def cmd_status(args):
    """Show current status and rate limit"""
    print("=" * 70)
    print("GitHub Report Script - Status")
    print("=" * 70)
    print(f"Organization: {GITHUB_ORG}")
    print(f"Tracked users: {', '.join(USER_IDS)}")
    print()

    # Get rate limit
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
        print(f"Processed users: {len(user_dirs)}")
        for user_dir in sorted(user_dirs):
            user_path = os.path.join(OUTPUT_DIR, user_dir)
            file_count = len([f for f in os.listdir(
                user_path) if f.endswith('.json')])
            print(f"  {user_dir}: {file_count} date(s)")
    else:
        print("No processed data found.")

    print("\n" + "=" * 70)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='GitHub Report Script - Fetch and visualize commit metrics',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch last 7 days for configured users
  python src/main.py fetch
  
  # Fetch specific date range
  python src/main.py fetch --start-date 2026-01-01 --end-date 2026-01-31
  
  # Refresh cache for last 7 days
  python src/main.py refresh
  
  # Refresh specific date range
  python src/main.py refresh --start-date 2026-01-27 --end-date 2026-01-28
  
  # Generate charts from existing data
  python src/main.py chart
  
  # Generate charts for specific date range
  python src/main.py chart --start-date 2026-01-01 --end-date 2026-01-31
  
  # Check status
  python src/main.py status
        """
    )

    subparsers = parser.add_subparsers(
        dest='command', help='Command to execute')

    # Fetch command
    fetch_parser = subparsers.add_parser(
        'fetch', help='Fetch commits and process data')
    fetch_parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    fetch_parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    fetch_parser.add_argument('--threads', type=int, default=DEFAULT_THREAD_COUNT,
                              help=f'Number of concurrent threads (default: {DEFAULT_THREAD_COUNT})')

    # Refresh command
    refresh_parser = subparsers.add_parser(
        'refresh', help='Refresh cache for date range')
    refresh_parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    refresh_parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    refresh_parser.add_argument('--threads', type=int, default=DEFAULT_THREAD_COUNT,
                                help=f'Number of concurrent threads (default: {DEFAULT_THREAD_COUNT})')

    # Chart command
    chart_parser = subparsers.add_parser(
        'chart', help='Generate charts from processed data')
    chart_parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    chart_parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')

    # Status command
    status_parser = subparsers.add_parser('status', help='Show current status')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        # Validate configuration
        validate_config()

        # Execute command
        if args.command == 'fetch':
            cmd_fetch(args)
        elif args.command == 'refresh':
            cmd_refresh(args)
        elif args.command == 'chart':
            cmd_chart(args)
        elif args.command == 'status':
            cmd_status(args)

    except ValueError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
