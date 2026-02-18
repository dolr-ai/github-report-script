"""
Tests for Cache Manager module
Tests cache read/write operations and data integrity
"""
import pytest
import json
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.cache_manager import CacheManager


class TestCacheManagerUnit:
    """Unit tests for cache manager"""

    @pytest.fixture
    def cache_manager(self, temp_cache_dir, monkeypatch):
        """Create a cache manager with temporary directory"""
        monkeypatch.setattr(
            'src.cache_manager.CACHE_COMMITS_DIR', temp_cache_dir)
        return CacheManager()

    @pytest.mark.unit
    def test_write_and_read_cache(self, cache_manager):
        """Test basic cache write and read operations"""
        date_str = '2026-01-15'
        data = {
            'date': date_str,
            'commits': [
                {
                    'sha': 'abc123',
                    'author': 'test-user',
                    'repository': 'dolr-ai/test-repo',
                    'timestamp': '2026-01-15T12:00:00Z',
                    'message': 'Test commit',
                    'stats': {'additions': 10, 'deletions': 5, 'total': 15}
                }
            ],
            'issues': []
        }

        # Write cache
        cache_manager.write_cache(date_str, data)

        # Verify file exists
        assert cache_manager.cache_exists(date_str)

        # Read cache
        cached_data = cache_manager.read_cache(date_str)
        assert cached_data is not None
        assert cached_data['date'] == date_str
        assert len(cached_data['commits']) == 1
        assert cached_data['commits'][0]['sha'] == 'abc123'

    @pytest.mark.unit
    def test_preserve_issues_data(self, cache_manager):
        """Test that issues data is properly stored and retrieved"""
        date_str = '2026-01-15'

        data = {
            'date': date_str,
            'commits': [],
            'issues': [
                {
                    'number': 123,
                    'title': 'Test issue',
                    'closed_at': '2026-01-15T14:00:00Z',
                    'assignee': 'test-user',
                    'repository': 'dolr-ai/test-repo',
                    'url': 'https://github.com/dolr-ai/test-repo/issues/123',
                    'labels': ['bug', 'priority-high']
                }
            ],
            'issue_count': 1
        }

        cache_manager.write_cache(date_str, data)

        result = cache_manager.read_cache(date_str)
        assert result['issue_count'] == 1
        assert len(result['issues']) == 1
        assert result['issues'][0]['number'] == 123
        assert result['issues'][0]['title'] == 'Test issue'

    @pytest.mark.unit
    def test_cached_at_timestamp_preservation(self, cache_manager):
        """Test that cached_at timestamp is preserved when content unchanged"""
        date_str = '2026-01-15'

        commits = [
            {
                'sha': 'abc123',
                'author': 'test-user',
                'repository': 'dolr-ai/test-repo',
                'timestamp': '2026-01-15T12:00:00Z',
                'message': 'Test commit',
                'stats': {'additions': 10, 'deletions': 5, 'total': 15}
            }
        ]

        data = {
            'date': date_str,
            'commits': commits,
            'issues': []
        }

        # First write
        cache_manager.write_cache(date_str, data)
        first_result = cache_manager.read_cache(date_str)
        first_cached_at = first_result['cached_at']

        # Second write with same content (should preserve timestamp)
        cache_manager.write_cache(date_str, data)
        second_result = cache_manager.read_cache(date_str)
        second_cached_at = second_result['cached_at']

        assert first_cached_at == second_cached_at

    @pytest.mark.unit
    def test_get_cached_dates(self, cache_manager):
        """Test retrieval of all cached dates"""
        dates = ['2026-01-15', '2026-01-16', '2026-01-17']

        for date_str in dates:
            data = {
                'date': date_str,
                'commits': [],
                'issues': []
            }
            cache_manager.write_cache(date_str, data)

        cached_dates = cache_manager.get_cached_dates()
        assert len(cached_dates) >= 3
        for date in dates:
            assert date in cached_dates
