"""
Tests for Leaderboard Generator module
Tests date calculations, timezone handling, and leaderboard generation
"""
import pytest
import json
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock
import pytz

from src.leaderboard_generator import LeaderboardGenerator
from src.cache_manager import CacheManager
from src.config import IST_TIMEZONE


class TestLeaderboardDateCalculations:
    """Unit tests for date calculation methods"""

    @pytest.fixture
    def cache_manager(self, temp_cache_dir, monkeypatch):
        """Create a cache manager with temporary directory"""
        monkeypatch.setattr(
            'src.cache_manager.CACHE_COMMITS_DIR', temp_cache_dir)
        return CacheManager()

    @pytest.fixture
    def leaderboard_gen(self, cache_manager):
        """Create a leaderboard generator"""
        return LeaderboardGenerator(cache_manager)

    @pytest.mark.unit
    def test_get_yesterday_ist_uses_ist_timezone(self, leaderboard_gen):
        """Test that get_yesterday_ist uses IST timezone correctly"""
        # Mock current time in IST: Feb 17, 2026 at 09:15 AM IST
        mock_ist_time = IST_TIMEZONE.localize(
            datetime(2026, 2, 17, 9, 15, 0))

        with patch('src.leaderboard_generator.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_ist_time
            yesterday = leaderboard_gen.get_yesterday_ist()

            # Should return Feb 16
            assert yesterday == '2026-02-16'
            mock_datetime.now.assert_called_once_with(IST_TIMEZONE)

    @pytest.mark.unit
    def test_get_yesterday_ist_at_midnight(self, leaderboard_gen):
        """Test get_yesterday_ist at midnight IST (critical time for CI)"""
        # Mock current time: Feb 17, 2026 at 00:00 AM IST (just after midnight)
        mock_ist_time = IST_TIMEZONE.localize(datetime(2026, 2, 17, 0, 0, 0))

        with patch('src.leaderboard_generator.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_ist_time
            yesterday = leaderboard_gen.get_yesterday_ist()

            # Should return Feb 16
            assert yesterday == '2026-02-16'

    @pytest.mark.unit
    def test_get_last_7_days_ist(self, leaderboard_gen):
        """Test that get_last_7_days_ist returns correct date range"""
        # Mock current time: Feb 17, 2026 at 09:15 AM IST
        mock_ist_time = IST_TIMEZONE.localize(
            datetime(2026, 2, 17, 9, 15, 0))

        with patch('src.leaderboard_generator.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_ist_time
            last_7_days = leaderboard_gen.get_last_7_days_ist()

            # Should return Feb 10-16 (7 days ending yesterday)
            assert len(last_7_days) == 7
            assert last_7_days[0] == '2026-02-10'  # Oldest
            assert last_7_days[-1] == '2026-02-16'  # Most recent (yesterday)

    @pytest.mark.unit
    def test_should_post_weekly_on_monday(self, leaderboard_gen):
        """Test that should_post_weekly returns True on Monday"""
        # Monday, Feb 17, 2026 is actually a Tuesday in real calendar
        # But we can use a real Monday: Feb 16, 2026 was a Monday
        mock_monday = IST_TIMEZONE.localize(datetime(2026, 2, 16, 0, 0, 0))

        with patch('src.leaderboard_generator.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_monday

            result = leaderboard_gen.should_post_weekly()
            # Feb 16, 2026 is actually a Monday (weekday 0)
            assert result is True

    @pytest.mark.unit
    def test_should_post_weekly_on_tuesday(self, leaderboard_gen):
        """Test that should_post_weekly returns False on other weekdays"""
        # Feb 17, 2026 is a Tuesday
        mock_tuesday = IST_TIMEZONE.localize(datetime(2026, 2, 17, 0, 0, 0))

        with patch('src.leaderboard_generator.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_tuesday

            result = leaderboard_gen.should_post_weekly()
            # Feb 17, 2026 is a Tuesday (weekday 1)
            assert result is False


class TestLeaderboardTimezoneConsistency:
    """Integration tests for timezone consistency between fetch and leaderboard"""

    @pytest.fixture
    def cache_manager(self, temp_cache_dir, monkeypatch):
        """Create a cache manager with temporary directory"""
        monkeypatch.setattr(
            'src.cache_manager.CACHE_COMMITS_DIR', temp_cache_dir)
        return CacheManager()

    @pytest.fixture
    def leaderboard_gen(self, cache_manager):
        """Create a leaderboard generator"""
        return LeaderboardGenerator(cache_manager)

    @pytest.mark.integration
    def test_fetch_and_leaderboard_date_alignment(self, cache_manager, leaderboard_gen, monkeypatch):
        """
        Critical test: Verify that get_date_range and get_yesterday_ist 
        return the same date when run at midnight IST.
        
        This is the fix for the "No activity" bug.
        """
        # Mock current time: Feb 17, 2026 at 00:00 AM IST
        # This is when the GitHub Action runs (12:00 AM IST = 6:30 PM UTC previous day)
        mock_ist_midnight = IST_TIMEZONE.localize(
            datetime(2026, 2, 17, 0, 0, 0))

        with patch('src.config.datetime') as mock_config_datetime, \
             patch('src.leaderboard_generator.datetime') as mock_leaderboard_datetime:

            # Mock both modules to return the same time
            mock_config_datetime.now.return_value = mock_ist_midnight
            mock_leaderboard_datetime.now.return_value = mock_ist_midnight

            # Mock timedelta to work properly
            mock_config_datetime.strptime = datetime.strptime
            mock_leaderboard_datetime.strftime = datetime.strftime

            def mock_timedelta(days=0):
                return timedelta(days=days)

            mock_config_datetime.timedelta = mock_timedelta
            mock_leaderboard_datetime.timedelta = mock_timedelta

            # Import get_date_range after patching
            from src.config import get_date_range

            # Get the date range that fetch would use
            start_date, end_date = get_date_range()

            # Get the date that leaderboard would look for
            yesterday_ist = leaderboard_gen.get_yesterday_ist()

            # The end_date from fetch should match the date leaderboard looks for
            # This is the critical fix - both should calculate "yesterday" as Feb 16
            assert end_date.strftime('%Y-%m-%d') == '2026-02-16'
            assert yesterday_ist == '2026-02-16'

            # They should be the same!
            assert end_date.strftime('%Y-%m-%d') == yesterday_ist, \
                "Fetch end date and leaderboard yesterday must match!"


class TestLeaderboardGeneration:
    """Integration tests for leaderboard generation with real data"""

    @pytest.fixture
    def cache_manager_with_data(self, temp_cache_dir, monkeypatch):
        """Create a cache manager with sample data"""
        monkeypatch.setattr(
            'src.cache_manager.CACHE_COMMITS_DIR', temp_cache_dir)
        cache_manager = CacheManager()

        # Create sample data for Feb 16, 2026
        sample_data = {
            'date': '2026-02-16',
            'cached_at': '2026-02-17T00:00:00Z',
            'commits': [
                {
                    'sha': 'abc123',
                    'author': 'saikatdas0790',
                    'repository': 'dolr-ai/test-repo',
                    'timestamp': '2026-02-16T14:30:00Z',
                    'message': 'Test commit 1',
                    'stats': {'additions': 100, 'deletions': 50, 'total': 150}
                },
                {
                    'sha': 'def456',
                    'author': 'saikatdas0790',
                    'repository': 'dolr-ai/test-repo',
                    'timestamp': '2026-02-16T15:30:00Z',
                    'message': 'Test commit 2',
                    'stats': {'additions': 200, 'deletions': 100, 'total': 300}
                },
                {
                    'sha': 'ghi789',
                    'author': 'gravityvi',
                    'repository': 'dolr-ai/another-repo',
                    'timestamp': '2026-02-16T16:30:00Z',
                    'message': 'Test commit 3',
                    'stats': {'additions': 50, 'deletions': 25, 'total': 75}
                }
            ],
            'issues': [
                {
                    'number': 123,
                    'assignee': 'saikatdas0790',
                    'title': 'Test issue 1',
                    'repository': 'dolr-ai/test-repo',
                    'html_url': 'https://github.com/dolr-ai/test-repo/issues/123',
                    'closed_at': '2026-02-16T14:00:00Z'
                },
                {
                    'number': 456,
                    'assignee': 'saikatdas0790',
                    'title': 'Test issue 2',
                    'repository': 'dolr-ai/test-repo',
                    'html_url': 'https://github.com/dolr-ai/test-repo/issues/456',
                    'closed_at': '2026-02-16T15:00:00Z'
                }
            ],
            'contributor_stats': {}
        }

        cache_manager.write_cache('2026-02-16', sample_data)
        return cache_manager

    @pytest.fixture
    def leaderboard_gen_with_data(self, cache_manager_with_data):
        """Create a leaderboard generator with sample data"""
        return LeaderboardGenerator(cache_manager_with_data)

    @pytest.mark.integration
    def test_aggregate_metrics_single_date(self, leaderboard_gen_with_data):
        """Test aggregating metrics for a single date"""
        metrics = leaderboard_gen_with_data.aggregate_metrics(['2026-02-16'])

        # Check saikatdas0790 metrics
        assert 'saikatdas0790' in metrics
        assert metrics['saikatdas0790']['commit_count'] == 2
        assert metrics['saikatdas0790']['total_loc'] == 450  # 150 + 300
        assert metrics['saikatdas0790']['issues_closed'] == 2

        # Check gravityvi metrics
        assert 'gravityvi' in metrics
        assert metrics['gravityvi']['commit_count'] == 1
        assert metrics['gravityvi']['total_loc'] == 75
        assert metrics['gravityvi']['issues_closed'] == 0

    @pytest.mark.integration
    def test_get_all_contributors_by_impact_sorting(self, leaderboard_gen_with_data):
        """Test that contributors are sorted by impact (issues > commits > loc)"""
        metrics = leaderboard_gen_with_data.aggregate_metrics(['2026-02-16'])
        sorted_contributors = leaderboard_gen_with_data.get_all_contributors_by_impact(
            metrics)

        # saikatdas0790 should be first (has issues closed)
        assert sorted_contributors[0][0] == 'saikatdas0790'
        assert sorted_contributors[0][1]['issues_closed'] == 2
        assert sorted_contributors[0][1]['commit_count'] == 2

        # gravityvi should be second (no issues, fewer commits)
        assert sorted_contributors[1][0] == 'gravityvi'
        assert sorted_contributors[1][1]['issues_closed'] == 0
        assert sorted_contributors[1][1]['commit_count'] == 1

    @pytest.mark.integration
    def test_generate_daily_leaderboard(self, leaderboard_gen_with_data):
        """Test generating a daily leaderboard"""
        # Mock the date to return Feb 17 (so yesterday is Feb 16)
        mock_ist_time = IST_TIMEZONE.localize(datetime(2026, 2, 17, 9, 0, 0))

        with patch('src.leaderboard_generator.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_ist_time
            mock_datetime.strptime = datetime.strptime

            def mock_timedelta(days=0):
                return timedelta(days=days)
            mock_datetime.timedelta = mock_timedelta

            contributors, date_string = leaderboard_gen_with_data.generate_daily_leaderboard()

            # Check results
            assert len(contributors) == 2
            assert contributors[0][0] == 'saikatdas0790'
            assert date_string == 'Feb 16, 2026'

    @pytest.mark.integration
    def test_get_commits_breakdown(self, leaderboard_gen_with_data):
        """Test getting commit breakdown for users"""
        metrics = leaderboard_gen_with_data.aggregate_metrics(['2026-02-16'])
        sorted_contributors = leaderboard_gen_with_data.get_all_contributors_by_impact(
            metrics)

        commits_breakdown = leaderboard_gen_with_data.get_commits_breakdown(
            ['2026-02-16'], sorted_contributors)

        # Check saikatdas0790 commits
        assert 'saikatdas0790' in commits_breakdown
        assert len(commits_breakdown['saikatdas0790']) == 2
        assert commits_breakdown['saikatdas0790'][0]['sha'] == 'abc123'
        assert commits_breakdown['saikatdas0790'][0]['message'] == 'Test commit 1'

        # Check gravityvi commits
        assert 'gravityvi' in commits_breakdown
        assert len(commits_breakdown['gravityvi']) == 1

    @pytest.mark.integration
    def test_get_issues_breakdown(self, leaderboard_gen_with_data):
        """Test getting issue breakdown for users"""
        metrics = leaderboard_gen_with_data.aggregate_metrics(['2026-02-16'])
        sorted_contributors = leaderboard_gen_with_data.get_all_contributors_by_impact(
            metrics)

        issues_breakdown = leaderboard_gen_with_data.get_issues_breakdown(
            ['2026-02-16'], sorted_contributors)

        # Check saikatdas0790 issues
        assert 'saikatdas0790' in issues_breakdown
        assert len(issues_breakdown['saikatdas0790']) == 2
        assert issues_breakdown['saikatdas0790'][0]['number'] == 123

        # gravityvi should not have issues
        assert 'gravityvi' not in issues_breakdown or len(
            issues_breakdown['gravityvi']) == 0

    @pytest.mark.integration
    def test_format_date_range_single_date(self, leaderboard_gen_with_data):
        """Test formatting a single date"""
        result = leaderboard_gen_with_data.format_date_range(['2026-02-16'])
        assert result == 'Feb 16, 2026'

    @pytest.mark.integration
    def test_format_date_range_same_month(self, leaderboard_gen_with_data):
        """Test formatting date range within same month"""
        result = leaderboard_gen_with_data.format_date_range(
            ['2026-02-10', '2026-02-11', '2026-02-12', '2026-02-13',
             '2026-02-14', '2026-02-15', '2026-02-16'])
        assert result == 'Feb 10-16, 2026'

    @pytest.mark.integration
    def test_format_date_range_different_months(self, leaderboard_gen_with_data):
        """Test formatting date range across different months"""
        result = leaderboard_gen_with_data.format_date_range(
            ['2026-01-28', '2026-01-29', '2026-01-30', '2026-01-31',
             '2026-02-01', '2026-02-02', '2026-02-03'])
        # strftime uses %d which adds leading zero for single-digit days
        assert result == 'Jan 28 - Feb 03, 2026'

    @pytest.mark.integration
    def test_no_activity_returns_empty_list(self, temp_cache_dir, monkeypatch):
        """Test that no activity results in empty contributor list"""
        monkeypatch.setattr(
            'src.cache_manager.CACHE_COMMITS_DIR', temp_cache_dir)

        cache_manager = CacheManager()
        leaderboard_gen = LeaderboardGenerator(cache_manager)

        # Mock the date
        mock_ist_time = IST_TIMEZONE.localize(datetime(2026, 2, 17, 9, 0, 0))

        with patch('src.leaderboard_generator.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_ist_time
            mock_datetime.strptime = datetime.strptime

            def mock_timedelta(days=0):
                return timedelta(days=days)
            mock_datetime.timedelta = mock_timedelta

            contributors, date_string = leaderboard_gen.generate_daily_leaderboard()

            # No data in cache, should return empty list
            assert len(contributors) == 0
            assert date_string == 'Feb 16, 2026'
