#!/usr/bin/env python3
"""
Local test script for leaderboard generation

Tests the leaderboard logic WITHOUT posting to Google Chat.
This is safe to run locally without spamming the team.
"""
import sys
import os
from datetime import datetime

# Setup Python path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config import IST_TIMEZONE, get_date_range, DATE_RANGE_MODE
from src.cache_manager import CacheManager
from src.leaderboard_generator import LeaderboardGenerator
from src.google_chat_poster import GoogleChatPoster

def test_dates():
    """Show what dates are being used"""
    print("=" * 70)
    print("DATE CALCULATIONS TEST")
    print("=" * 70)
    
    # Show current time in both timezones
    now_utc = datetime.utcnow()
    now_ist = datetime.now(IST_TIMEZONE)
    
    print(f"\nCurrent UTC time:     {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Current IST time:     {now_ist.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    # Show what get_date_range returns
    start_date, end_date = get_date_range()
    print(f"\nFetch date range (MODE: {DATE_RANGE_MODE.value}):")
    print(f"  Start: {start_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  End:   {end_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    # Show what leaderboard will look for
    leaderboard = LeaderboardGenerator(CacheManager())
    yesterday_ist = leaderboard.get_yesterday_ist()
    should_post_weekly = leaderboard.should_post_weekly()
    
    print(f"\nLeaderboard configuration:")
    print(f"  Should post weekly: {should_post_weekly}")
    print(f"  Yesterday (IST):    {yesterday_ist}")
    
    if should_post_weekly:
        last_7_days = leaderboard.get_last_7_days_ist()
        print(f"  Last 7 days:        {last_7_days[0]} to {last_7_days[-1]}")
    
    print("\n" + "=" * 70)

def test_leaderboard_generation():
    """Test leaderboard generation WITHOUT posting"""
    print("\n" + "=" * 70)
    print("LEADERBOARD GENERATION TEST (NO POSTING)")
    print("=" * 70)
    
    cache_manager = CacheManager()
    leaderboard_generator = LeaderboardGenerator(cache_manager)
    
    # Check if we should post weekly
    should_post_weekly = leaderboard_generator.should_post_weekly()
    
    if should_post_weekly:
        print("\nGenerating WEEKLY leaderboard...")
        contributors_by_impact, date_string = leaderboard_generator.generate_weekly_leaderboard()
        period_type = "Weekly"
        
        # Get breakdown
        date_strings = leaderboard_generator.get_last_7_days_ist()
        print(f"Date range: {date_strings[0]} to {date_strings[-1]}")
    else:
        print("\nGenerating DAILY leaderboard...")
        contributors_by_impact, date_string = leaderboard_generator.generate_daily_leaderboard()
        period_type = "Daily"
        
        # Get breakdown
        date_strings = [leaderboard_generator.get_yesterday_ist()]
        print(f"Date: {date_strings[0]}")
    
    print(f"\nFound {len(contributors_by_impact)} contributors")
    
    # Format the message (without posting)
    chat_poster = GoogleChatPoster()
    message = chat_poster.format_leaderboard_message(
        period_type=period_type,
        date_string=date_string,
        contributors_by_impact=contributors_by_impact
    )
    
    print("\n" + "-" * 70)
    print("MESSAGE THAT WOULD BE POSTED:")
    print("-" * 70)
    print(message)
    print("-" * 70)
    
    # Get and format breakdown message
    user_commits = leaderboard_generator.get_commits_breakdown(
        date_strings, contributors_by_impact)
    user_issues = leaderboard_generator.get_issues_breakdown(
        date_strings, contributors_by_impact)
    
    breakdown_message = chat_poster.format_commits_breakdown_message(
        period_type=period_type,
        date_string=date_string,
        leaderboard_order=contributors_by_impact,
        user_commits=user_commits,
        user_issues=user_issues
    )
    
    print("\nBREAKDOWN MESSAGE THAT WOULD BE POSTED:")
    print("-" * 70)
    print(breakdown_message)
    print("-" * 70)
    
    # Show detailed stats
    if contributors_by_impact:
        print("\n" + "=" * 70)
        print("DETAILED STATISTICS")
        print("=" * 70)
        for username, metrics in contributors_by_impact:
            print(f"\n{username}:")
            print(f"  Issues closed: {metrics.get('issues_closed', 0)}")
            print(f"  Commits:       {metrics.get('commit_count', 0)}")
            print(f"  Total LOC:     {metrics.get('total_loc', 0):,}")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    print("\n🧪 TESTING LEADERBOARD LOCALLY (NO POSTING TO GOOGLE CHAT)\n")
    
    test_dates()
    test_leaderboard_generation()
    
    print("\n✅ Test complete! No messages were posted to Google Chat.\n")
