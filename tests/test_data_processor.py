"""
Tests for data processor module
"""
import pytest
import json
import os
from datetime import datetime, timedelta

from src.data_processor import DataProcessor


class TestDataProcessor:
    """Test data aggregation and processing"""

    def test_metrics_aggregation(self, temp_cache_dir, temp_output_dir):
        """Test that metrics are correctly aggregated per user"""
        # Create mock cache data
        cache_file = os.path.join(temp_cache_dir, 'commits', '2026-01-01.json')
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)

        cache_data = {
            'date': '2026-01-01',
            'commits': [
                {
                    'author': 'user1',
                    'repository': 'dolr-ai/repo1',
                    'stats': {'additions': 100, 'deletions': 50, 'total': 150}
                },
                {
                    'author': 'user1',
                    'repository': 'dolr-ai/repo2',
                    'stats': {'additions': 200, 'deletions': 75, 'total': 275}
                },
                {
                    'author': 'user2',
                    'repository': 'dolr-ai/repo1',
                    'stats': {'additions': 50, 'deletions': 25, 'total': 75}
                }
            ]
        }

        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)

        # Process data
        with patch('src.config.CACHE_COMMITS_DIR', os.path.join(temp_cache_dir, 'commits')):
            with patch('src.config.OUTPUT_DIR', temp_output_dir):
                processor = DataProcessor()
                processor.process_date(
                    '2026-01-01', ['user1', 'user2'], force_refresh=True)

        # Verify output
        user1_file = os.path.join(temp_output_dir, 'user1', '2026-01-01.json')
        assert os.path.exists(user1_file)

        with open(user1_file, 'r') as f:
            user1_data = json.load(f)

        assert user1_data['additions'] == 300
        assert user1_data['deletions'] == 125
        assert user1_data['commit_count'] == 2

    def test_zero_commits_handling(self, temp_cache_dir, temp_output_dir):
        """Test that users with no commits get zero metrics"""
        cache_file = os.path.join(temp_cache_dir, 'commits', '2026-01-02.json')
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)

        cache_data = {
            'date': '2026-01-02',
            'commits': []
        }

        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)

        # Process data
        with patch('src.config.CACHE_COMMITS_DIR', os.path.join(temp_cache_dir, 'commits')):
            with patch('src.config.OUTPUT_DIR', temp_output_dir):
                processor = DataProcessor()
                processor.process_date(
                    '2026-01-02', ['user1'], force_refresh=True)

        # Verify output has zeros
        user1_file = os.path.join(temp_output_dir, 'user1', '2026-01-02.json')
        with open(user1_file, 'r') as f:
            user1_data = json.load(f)

        assert user1_data['commit_count'] == 0
        assert user1_data['additions'] == 0
        assert user1_data['deletions'] == 0


# Need to mock imports for this test
try:
    from unittest.mock import patch
except ImportError:
    pass
