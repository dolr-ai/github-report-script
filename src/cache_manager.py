"""
Cache Manager Module
Handles day-wise JSON caching of commit data with thread-safe operations
"""
import os
import json
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional

from src.config import CACHE_COMMITS_DIR, CACHE_METADATA_FILE

logger = logging.getLogger(__name__)


class CacheManager:
    """Manages caching of commit data with thread-safe operations"""

    def __init__(self):
        self.cache_lock = threading.Lock()
        self._ensure_cache_directories()

    def _ensure_cache_directories(self):
        """Create cache directories if they don't exist"""
        os.makedirs(CACHE_COMMITS_DIR, exist_ok=True)

    def get_cache_file_path(self, date_str: str) -> str:
        """Get the file path for a specific date's cache

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            Full path to cache file
        """
        return os.path.join(CACHE_COMMITS_DIR, f"{date_str}.json")

    def cache_exists(self, date_str: str) -> bool:
        """Check if cache exists for a specific date

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            True if cache file exists
        """
        exists = os.path.exists(self.get_cache_file_path(date_str))
        if exists:
            logger.debug(f"Cache exists for {date_str}")
        return exists

    def read_cache(self, date_str: str) -> Optional[Dict]:
        """Read cached data for a specific date

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            Cached data dict or None if not found
        """
        cache_file = self.get_cache_file_path(date_str)

        if not os.path.exists(cache_file):
            return None

        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
                logger.debug(
                    f"Read cache for {date_str}: {len(data.get('commits', []))} commits")
                return data
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read cache for {date_str}: {e}")
            return None

    def write_cache(self, date_str: str, data: Dict):
        """Write data to cache for a specific date (thread-safe)
        Only updates cached_at timestamp if content actually changes.

        Args:
            date_str: Date in YYYY-MM-DD format
            data: Data dictionary to cache
        """
        cache_file = self.get_cache_file_path(date_str)
        new_commits = data.get('commits', [])

        # Check if existing cache has the same content
        existing_cached_at = None
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    existing_data = json.load(f)
                    existing_commits = existing_data.get('commits', [])

                    # Compare commits (excluding cached_at field)
                    if existing_commits == new_commits:
                        # Content hasn't changed, preserve cached_at
                        existing_cached_at = existing_data.get('cached_at')
                        logger.debug(
                            f"Cache content unchanged for {date_str}, preserving timestamp")
            except (json.JSONDecodeError, IOError):
                pass  # If we can't read, treat as new cache

        # Add metadata
        cache_data = {
            'date': date_str,
            'cached_at': existing_cached_at if existing_cached_at else datetime.utcnow().isoformat() + 'Z',
            'commits': new_commits,
            'commit_count': len(new_commits)
        }
        
        # Include contributor_stats if present
        if 'contributor_stats' in data:
            cache_data['contributor_stats'] = data['contributor_stats']

        with self.cache_lock:
            try:
                with open(cache_file, 'w') as f:
                    json.dump(cache_data, f, indent=2)
                if existing_cached_at:
                    logger.debug(
                        f"Cache unchanged for {date_str}: {cache_data['commit_count']} commits")
                else:
                    logger.debug(
                        f"Wrote cache for {date_str}: {cache_data['commit_count']} commits")
            except IOError as e:
                logger.error(f"Failed to write cache for {date_str}: {e}")

    def get_cached_dates(self) -> List[str]:
        """Get list of all cached dates

        Returns:
            List of date strings in YYYY-MM-DD format
        """
        if not os.path.exists(CACHE_COMMITS_DIR):
            return []

        dates = []
        for filename in os.listdir(CACHE_COMMITS_DIR):
            if filename.endswith('.json'):
                date_str = filename[:-5]  # Remove .json extension
                dates.append(date_str)

        return sorted(dates)

    def update_metadata(self, date_range: tuple):
        """Update cache metadata file

        Args:
            date_range: Tuple of (start_date, end_date) strings
        """
        metadata = {
            'last_updated': datetime.utcnow().isoformat() + 'Z',
            'cached_dates': self.get_cached_dates(),
            'date_range': {
                'start': date_range[0],
                'end': date_range[1]
            }
        }

        with self.cache_lock:
            try:
                os.makedirs(os.path.dirname(
                    CACHE_METADATA_FILE), exist_ok=True)
                with open(CACHE_METADATA_FILE, 'w') as f:
                    json.dump(metadata, f, indent=2)
            except IOError as e:
                print(f"Warning: Failed to update metadata: {e}")

    def clear_cache(self, date_str: Optional[str] = None):
        """Clear cache for specific date or all dates

        Args:
            date_str: Date to clear, or None to clear all
        """
        if date_str:
            cache_file = self.get_cache_file_path(date_str)
            if os.path.exists(cache_file):
                os.remove(cache_file)
                print(f"Cleared cache for {date_str}")
        else:
            # Clear all cache files
            for date in self.get_cached_dates():
                cache_file = self.get_cache_file_path(date)
                os.remove(cache_file)
            print("Cleared all cache files")

    def validate_cache_structure(self) -> bool:
        """Validate that cached commits have the expected structure with branches field

        Returns:
            True if cache structure is valid, False if outdated
        """
        cached_dates = self.get_cached_dates()
        if not cached_dates:
            return True  # No cache to validate

        # Check first cached file for structure
        first_date = cached_dates[0]
        cached_data = self.read_cache(first_date)

        if not cached_data:
            return True  # Empty cache is fine

        commits = cached_data.get('commits', [])
        if not commits:
            return True  # No commits to validate

        # Check if first commit has 'branches' field
        first_commit = commits[0]
        has_branches = 'branches' in first_commit

        if not has_branches:
            logger.warning(
                f"Cache structure is outdated (missing 'branches' field). "
                f"Cache will be cleared and re-fetched."
            )

        return has_branches

    def clear_all_cache(self):
        """Clear all cache files, metadata, and output directories"""
        import shutil
        from src.config import OUTPUT_DIR

        logger.info("Clearing all cache and output data...")

        # Clear cache commits
        if os.path.exists(CACHE_COMMITS_DIR):
            for date in self.get_cached_dates():
                cache_file = self.get_cache_file_path(date)
                if os.path.exists(cache_file):
                    os.remove(cache_file)
            logger.info(f"Cleared {len(self.get_cached_dates())} cache files")

        # Clear metadata
        if os.path.exists(CACHE_METADATA_FILE):
            os.remove(CACHE_METADATA_FILE)
            logger.info("Cleared cache metadata")

        # Clear output directories
        if os.path.exists(OUTPUT_DIR):
            for user_dir in os.listdir(OUTPUT_DIR):
                user_path = os.path.join(OUTPUT_DIR, user_dir)
                if os.path.isdir(user_path):
                    shutil.rmtree(user_path)
            logger.info("Cleared all user output directories")

        logger.info("Cache clearing complete")
