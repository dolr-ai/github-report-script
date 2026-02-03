"""
Test configuration and fixtures for pytest
"""
import os
import pytest
import shutil
import tempfile
from datetime import datetime, timedelta
from github import Github

from src.config import GITHUB_TOKEN


@pytest.fixture
def temp_cache_dir():
    """Create a temporary cache directory for testing"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def temp_output_dir():
    """Create a temporary output directory for testing"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def github_client():
    """Create a GitHub client for integration tests"""
    if not GITHUB_TOKEN:
        pytest.skip("GITHUB_TOKEN not available")
    return Github(GITHUB_TOKEN, per_page=100)


@pytest.fixture
def sample_date_range():
    """Provide a sample date range for testing"""
    end_date = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(days=6)  # 7 days
    return start_date, end_date


@pytest.fixture
def dolr_ai_org():
    """Get the dolr-ai organization for integration tests"""
    client = Github(GITHUB_TOKEN, per_page=100)
    return client.get_organization("dolr-ai")
