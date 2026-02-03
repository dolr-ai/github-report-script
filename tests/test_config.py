"""
Tests for configuration module
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from src.config import DateRangeMode, ExecutionMode, get_date_range, validate_config


class TestDateRangeCalculation:
    """Test date range calculation logic"""

    @pytest.mark.unit
    def test_last_n_days_excludes_today(self):
        """Test that LAST_N_DAYS mode excludes today's data"""
        with patch('src.config.DATE_RANGE_MODE', DateRangeMode.LAST_N_DAYS):
            with patch('src.config.DAYS_BACK', 7):
                start_date, end_date = get_date_range()

                # End date should be yesterday, not today
                expected_end = (datetime.now() - timedelta(days=1)).date()
                assert end_date.date() == expected_end, \
                    f"End date should be yesterday, got {end_date.date()}"

                # Should be at end of day
                assert end_date.hour == 23
                assert end_date.minute == 59
                assert end_date.second == 59

    @pytest.mark.unit
    def test_last_n_days_correct_span(self):
        """Test that LAST_N_DAYS calculates correct date span"""
        with patch('src.config.DATE_RANGE_MODE', DateRangeMode.LAST_N_DAYS):
            with patch('src.config.DAYS_BACK', 7):
                start_date, end_date = get_date_range()

                # Should span 7 days
                days_diff = (end_date.date() - start_date.date()).days
                assert days_diff == 6, f"Expected 6 days difference, got {days_diff}"

    @pytest.mark.unit
    def test_custom_range_validation(self):
        """Test that CUSTOM_RANGE validates start < end"""
        with patch('src.config.DATE_RANGE_MODE', DateRangeMode.CUSTOM_RANGE):
            with patch('src.config.START_DATE', '2026-01-31'):
                with patch('src.config.END_DATE', '2026-01-01'):
                    with pytest.raises(ValueError, match="START_DATE.*must be before.*END_DATE"):
                        get_date_range()

    @pytest.mark.unit
    def test_specific_date_mode(self):
        """Test that SPECIFIC_DATE returns same start and end"""
        with patch('src.config.DATE_RANGE_MODE', DateRangeMode.SPECIFIC_DATE):
            with patch('src.config.START_DATE', '2026-01-15'):
                start_date, end_date = get_date_range()
                assert start_date.date() == end_date.date()
                assert start_date.date() == datetime(2026, 1, 15).date()


class TestConfigValidation:
    """Test configuration validation"""

    @pytest.mark.unit
    def test_missing_github_token_raises_error(self):
        """Test that missing GITHUB_TOKEN raises ValueError"""
        with patch('src.config.GITHUB_TOKEN', None):
            with pytest.raises(ValueError, match="GITHUB_TOKEN"):
                validate_config()

    @pytest.mark.unit
    def test_empty_user_ids_raises_error(self):
        """Test that empty USER_IDS raises ValueError"""
        with patch('src.config.GITHUB_TOKEN', 'fake-token'):
            with patch('src.config.USER_IDS', []):
                with pytest.raises(ValueError, match="USER_IDS"):
                    validate_config()

    @pytest.mark.unit
    def test_valid_config_passes(self):
        """Test that valid configuration passes validation"""
        with patch('src.config.GITHUB_TOKEN', 'fake-token'):
            with patch('src.config.USER_IDS', ['user1', 'user2']):
                with patch('src.config.MODE', ExecutionMode.FETCH):
                    with patch('src.config.DATE_RANGE_MODE', DateRangeMode.LAST_N_DAYS):
                        with patch('src.config.DAYS_BACK', 7):
                            # Should not raise
                            validate_config()
