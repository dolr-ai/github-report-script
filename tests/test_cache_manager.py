"""
Tests for Cache Manager module
Tests contributor_stats preservation logic and cache operations
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
            'issues': [],
            'contributor_stats': {}
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
    def test_preserve_contributor_stats_on_empty_update(self, cache_manager):
        """Test that existing contributor_stats are preserved when new data is empty

        This is the critical fix - when GitHub API returns 202 (still computing),
        the fetcher provides empty contributor_stats. The cache manager should
        preserve existing stats rather than overwriting with empty dict.
        """
        date_str = '2026-01-15'

        # Initial data with contributor_stats
        initial_data = {
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
            'issues': [],
            'contributor_stats': {
                'test-user': {
                    '2026-01-15': {
                        'commits': 5,
                        'additions': 100,
                        'deletions': 50,
                        'total': 150,
                        'repos': ['dolr-ai/test-repo']
                    }
                }
            }
        }

        # Write initial data
        cache_manager.write_cache(date_str, initial_data)

        # Simulate a refresh where API returns 202 (empty contributor_stats)
        refresh_data = {
            'date': date_str,
            'commits': initial_data['commits'],  # Same commits
            'issues': [],
            'contributor_stats': {}  # Empty - API still computing
        }

        # Write refresh data
        cache_manager.write_cache(date_str, refresh_data)

        # Read back and verify contributor_stats were preserved
        result = cache_manager.read_cache(date_str)

        assert result is not None
        assert 'contributor_stats' in result
        assert 'test-user' in result['contributor_stats']
        assert result['contributor_stats']['test-user']['2026-01-15']['commits'] == 5
        assert result['contributor_stats']['test-user']['2026-01-15']['additions'] == 100

    @pytest.mark.unit
    def test_update_contributor_stats_when_new_data_provided(self, cache_manager):
        """Test that contributor_stats are updated when new data is provided"""
        date_str = '2026-01-15'

        # Initial data with old stats
        initial_data = {
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
            'issues': [],
            'contributor_stats': {
                'test-user': {
                    '2026-01-15': {
                        'commits': 5,
                        'additions': 100,
                        'deletions': 50,
                        'total': 150
                    }
                }
            }
        }

        cache_manager.write_cache(date_str, initial_data)

        # Update with new contributor_stats
        updated_data = {
            'date': date_str,
            'commits': initial_data['commits'],
            'issues': [],
            'contributor_stats': {
                'test-user': {
                    '2026-01-15': {
                        'commits': 10,  # Updated
                        'additions': 200,  # Updated
                        'deletions': 100,  # Updated
                        'total': 300
                    }
                },
                'another-user': {  # New user
                    '2026-01-15': {
                        'commits': 3,
                        'additions': 50,
                        'deletions': 25,
                        'total': 75
                    }
                }
            }
        }

        cache_manager.write_cache(date_str, updated_data)

        # Verify stats were updated
        result = cache_manager.read_cache(date_str)

        assert result['contributor_stats']['test-user']['2026-01-15']['commits'] == 10
        assert result['contributor_stats']['test-user']['2026-01-15']['additions'] == 200
        assert 'another-user' in result['contributor_stats']

    @pytest.mark.unit
    def test_empty_contributor_stats_on_first_write(self, cache_manager):
        """Test that empty contributor_stats work correctly on initial write"""
        date_str = '2026-01-15'

        # Initial data with no contributor_stats (recent date, < 7 days)
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
            'issues': [],
            'contributor_stats': {}  # Empty on first write is OK
        }

        cache_manager.write_cache(date_str, data)

        result = cache_manager.read_cache(date_str)
        assert result['contributor_stats'] == {}

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
            'issue_count': 1,
            'contributor_stats': {}
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
            'issues': [],
            'contributor_stats': {}
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
                'issues': [],
                'contributor_stats': {}
            }
            cache_manager.write_cache(date_str, data)

        cached_dates = cache_manager.get_cached_dates()
        assert len(cached_dates) >= 3
        for date in dates:
            assert date in cached_dates

    @pytest.mark.unit
    def test_multiple_users_contributor_stats(self, cache_manager):
        """Test handling of contributor_stats for multiple users"""
        date_str = '2026-01-15'

        data = {
            'date': date_str,
            'commits': [],
            'issues': [],
            'contributor_stats': {
                'user1': {
                    '2026-01-15': {'commits': 5, 'additions': 100, 'deletions': 50, 'total': 150}
                },
                'user2': {
                    '2026-01-15': {'commits': 3, 'additions': 200, 'deletions': 75, 'total': 275}
                },
                'user3': {
                    '2026-01-15': {'commits': 10, 'additions': 500, 'deletions': 250, 'total': 750}
                }
            }
        }

        cache_manager.write_cache(date_str, data)

        # Update with empty stats (simulate 202 response)
        refresh_data = {
            'date': date_str,
            'commits': [],
            'issues': [],
            'contributor_stats': {}
        }

        cache_manager.write_cache(date_str, refresh_data)

        result = cache_manager.read_cache(date_str)

        # All three users should still be present
        assert 'user1' in result['contributor_stats']
        assert 'user2' in result['contributor_stats']
        assert 'user3' in result['contributor_stats']
        assert result['contributor_stats']['user1']['2026-01-15']['commits'] == 5
        assert result['contributor_stats']['user2']['2026-01-15']['commits'] == 3
        assert result['contributor_stats']['user3']['2026-01-15']['commits'] == 10


class TestCacheManagerIntegration:
    """Integration tests for cache manager"""

    @pytest.mark.integration
    def test_real_world_refresh_scenario(self, temp_cache_dir, monkeypatch):
        """Test a realistic scenario of cache refresh with API 202 responses

        This simulates what happens during a real refresh when GitHub API
        returns 202 for some repositories while computing stats.
        """
        monkeypatch.setattr(
            'src.cache_manager.CACHE_COMMITS_DIR', temp_cache_dir)
        cache_manager = CacheManager()

        date_str = '2026-01-15'

        # Simulate initial successful fetch with complete data
        initial_data = {
            'date': date_str,
            'commits': [
                {
                    'sha': 'commit1',
                    'author': 'developer1',
                    'repository': 'dolr-ai/repo1',
                    'timestamp': '2026-01-15T10:00:00Z',
                    'message': 'Feature implementation',
                    'stats': {'additions': 150, 'deletions': 30, 'total': 180}
                },
                {
                    'sha': 'commit2',
                    'author': 'developer2',
                    'repository': 'dolr-ai/repo2',
                    'timestamp': '2026-01-15T14:00:00Z',
                    'message': 'Bug fix',
                    'stats': {'additions': 20, 'deletions': 15, 'total': 35}
                }
            ],
            'issues': [
                {
                    'number': 456,
                    'title': 'Critical bug',
                    'closed_at': '2026-01-15T16:00:00Z',
                    'assignee': 'developer1',
                    'repository': 'dolr-ai/repo1',
                    'url': 'https://github.com/dolr-ai/repo1/issues/456',
                    'labels': ['bug', 'critical']
                }
            ],
            'issue_count': 1,
            'contributor_stats': {
                'developer1': {
                    '2026-01-15': {
                        'commits': 8,
                        'additions': 500,
                        'deletions': 120,
                        'total': 620,
                        'repos': ['dolr-ai/repo1', 'dolr-ai/repo3']
                    }
                },
                'developer2': {
                    '2026-01-15': {
                        'commits': 4,
                        'additions': 250,
                        'deletions': 80,
                        'total': 330,
                        'repos': ['dolr-ai/repo2']
                    }
                }
            }
        }

        cache_manager.write_cache(date_str, initial_data)

        # Simulate refresh where:
        # - Commits are re-fetched (same data)
        # - Issues are re-fetched and one new issue found
        # - Contributor stats fetch hits 202 for some repos (returns empty)
        refresh_data = {
            'date': date_str,
            'commits': initial_data['commits'],  # Same commits
            'issues': initial_data['issues'] + [
                {
                    'number': 789,
                    'title': 'New issue closed',
                    'closed_at': '2026-01-15T18:00:00Z',
                    'assignee': 'developer2',
                    'repository': 'dolr-ai/repo2',
                    'url': 'https://github.com/dolr-ai/repo2/issues/789',
                    'labels': ['enhancement']
                }
            ],
            'issue_count': 2,
            'contributor_stats': {}  # Empty due to 202 responses
        }

        cache_manager.write_cache(date_str, refresh_data)

        # Verify the final state
        result = cache_manager.read_cache(date_str)

        # Commits should be unchanged
        assert len(result['commits']) == 2

        # Issues should be updated with new data
        assert result['issue_count'] == 2
        assert len(result['issues']) == 2

        # Contributor stats should be PRESERVED from initial fetch
        assert 'developer1' in result['contributor_stats']
        assert 'developer2' in result['contributor_stats']
        assert result['contributor_stats']['developer1']['2026-01-15']['commits'] == 8
        assert result['contributor_stats']['developer2']['2026-01-15']['commits'] == 4

        # Verify the full stats structure is intact
        assert result['contributor_stats']['developer1']['2026-01-15']['additions'] == 500
        assert result['contributor_stats']['developer2']['2026-01-15']['repos'] == ['dolr-ai/repo2']
