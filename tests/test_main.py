"""
Unit tests for main.py entry-point commands, with particular focus on
cmd_fetch_and_leaderboard which was missing and caused the nightly CI failure.
"""
import sys
import pytest
from unittest.mock import call, patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(
    mode=None,
    days=None,
    dry_run=False,
    test_channel=False,
):
    """Return a minimal Namespace that looks like parse_args() output."""
    import argparse
    return argparse.Namespace(
        mode=mode,
        days=days,
        dry_run=dry_run,
        test_channel=test_channel,
    )


# ---------------------------------------------------------------------------
# cmd_fetch_and_leaderboard
# ---------------------------------------------------------------------------

class TestCmdFetchAndLeaderboard:
    """Tests for the cmd_fetch_and_leaderboard composite command."""

    @pytest.mark.unit
    def test_calls_fetch_then_leaderboard(self):
        """cmd_fetch_and_leaderboard must call cmd_fetch and then cmd_leaderboard."""
        with patch('src.main.cmd_fetch') as mock_fetch, \
                patch('src.main.cmd_leaderboard') as mock_leaderboard:

            from src.main import cmd_fetch_and_leaderboard
            cmd_fetch_and_leaderboard()

            mock_fetch.assert_called_once_with()
            mock_leaderboard.assert_called_once_with(
                dry_run=False, test_channel=False)

    @pytest.mark.unit
    def test_forwards_dry_run_flag(self):
        """dry_run=True must be forwarded to cmd_leaderboard."""
        with patch('src.main.cmd_fetch'), \
                patch('src.main.cmd_leaderboard') as mock_leaderboard:

            from src.main import cmd_fetch_and_leaderboard
            cmd_fetch_and_leaderboard(dry_run=True)

            mock_leaderboard.assert_called_once_with(
                dry_run=True, test_channel=False)

    @pytest.mark.unit
    def test_forwards_test_channel_flag(self):
        """test_channel=True must be forwarded to cmd_leaderboard."""
        with patch('src.main.cmd_fetch'), \
                patch('src.main.cmd_leaderboard') as mock_leaderboard:

            from src.main import cmd_fetch_and_leaderboard
            cmd_fetch_and_leaderboard(test_channel=True)

            mock_leaderboard.assert_called_once_with(
                dry_run=False, test_channel=True)

    @pytest.mark.unit
    def test_forwards_both_flags(self):
        """Both dry_run and test_channel must be forwarded together."""
        with patch('src.main.cmd_fetch'), \
                patch('src.main.cmd_leaderboard') as mock_leaderboard:

            from src.main import cmd_fetch_and_leaderboard
            cmd_fetch_and_leaderboard(dry_run=True, test_channel=True)

            mock_leaderboard.assert_called_once_with(
                dry_run=True, test_channel=True)

    @pytest.mark.unit
    def test_fetch_runs_before_leaderboard(self):
        """cmd_fetch must complete before cmd_leaderboard is invoked."""
        call_order = []

        with patch('src.main.cmd_fetch', side_effect=lambda: call_order.append('fetch')), \
                patch('src.main.cmd_leaderboard', side_effect=lambda **_: call_order.append('leaderboard')):

            from src.main import cmd_fetch_and_leaderboard
            cmd_fetch_and_leaderboard()

            assert call_order == ['fetch', 'leaderboard']

    @pytest.mark.unit
    def test_propagates_fetch_exception(self):
        """If cmd_fetch raises, the exception must not be swallowed."""
        with patch('src.main.cmd_fetch', side_effect=RuntimeError("fetch failed")), \
                patch('src.main.cmd_leaderboard') as mock_leaderboard:

            from src.main import cmd_fetch_and_leaderboard
            with pytest.raises(RuntimeError, match="fetch failed"):
                cmd_fetch_and_leaderboard()

            # leaderboard should NOT have been called
            mock_leaderboard.assert_not_called()


# ---------------------------------------------------------------------------
# main() dispatch — FETCH_AND_LEADERBOARD mode
# ---------------------------------------------------------------------------

class TestMainDispatch:
    """Tests that main() dispatches to the correct command functions."""

    @pytest.mark.unit
    def test_main_dispatches_fetch_and_leaderboard_mode(self):
        """main() with FETCH_AND_LEADERBOARD mode must call cmd_fetch_and_leaderboard."""
        from src.config import ExecutionMode

        with patch('src.main.parse_args', return_value=_make_args(mode='fetch_and_leaderboard')), \
                patch('src.main.validate_config'), \
                patch('src.main.MODE', ExecutionMode.FETCH_AND_LEADERBOARD), \
                patch('src.main.cmd_fetch_and_leaderboard') as mock_cmd:

            from src.main import main
            main()

            mock_cmd.assert_called_once_with(dry_run=False, test_channel=False)

    @pytest.mark.unit
    def test_main_fetch_and_leaderboard_passes_dry_run(self):
        """--dry-run must reach cmd_fetch_and_leaderboard."""
        from src.config import ExecutionMode

        with patch('src.main.parse_args', return_value=_make_args(mode='fetch_and_leaderboard', dry_run=True)), \
                patch('src.main.validate_config'), \
                patch('src.main.MODE', ExecutionMode.FETCH_AND_LEADERBOARD), \
                patch('src.main.cmd_fetch_and_leaderboard') as mock_cmd:

            from src.main import main
            main()

            mock_cmd.assert_called_once_with(dry_run=True, test_channel=False)

    @pytest.mark.unit
    def test_main_fetch_and_leaderboard_passes_test_channel(self):
        """--test-channel must reach cmd_fetch_and_leaderboard."""
        from src.config import ExecutionMode

        with patch('src.main.parse_args', return_value=_make_args(mode='fetch_and_leaderboard', test_channel=True)), \
                patch('src.main.validate_config'), \
                patch('src.main.MODE', ExecutionMode.FETCH_AND_LEADERBOARD), \
                patch('src.main.cmd_fetch_and_leaderboard') as mock_cmd:

            from src.main import main
            main()

            mock_cmd.assert_called_once_with(dry_run=False, test_channel=True)

    @pytest.mark.unit
    def test_main_exits_1_on_unexpected_error(self):
        """main() must sys.exit(1) when an unexpected error occurs."""
        from src.config import ExecutionMode

        with patch('src.main.parse_args', return_value=_make_args(mode='fetch_and_leaderboard')), \
                patch('src.main.validate_config'), \
                patch('src.main.MODE', ExecutionMode.FETCH_AND_LEADERBOARD), \
                patch('src.main.cmd_fetch_and_leaderboard', side_effect=Exception("boom")):

            from src.main import main
            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

class TestParseArgs:
    """Tests for CLI argument parsing."""

    @pytest.mark.unit
    def test_fetch_and_leaderboard_is_valid_mode(self):
        """fetch_and_leaderboard must be accepted as a valid --mode value."""
        from src.main import parse_args

        with patch('sys.argv', ['main.py', '--mode', 'fetch_and_leaderboard']):
            args = parse_args()
            assert args.mode == 'fetch_and_leaderboard'

    @pytest.mark.unit
    def test_dry_run_default_is_false(self):
        """--dry-run should default to False when not supplied."""
        from src.main import parse_args

        with patch('sys.argv', ['main.py']):
            args = parse_args()
            assert args.dry_run is False

    @pytest.mark.unit
    def test_test_channel_default_is_false(self):
        """--test-channel should default to False when not supplied."""
        from src.main import parse_args

        with patch('sys.argv', ['main.py']):
            args = parse_args()
            assert args.test_channel is False

    @pytest.mark.unit
    def test_dry_run_and_test_channel_together(self):
        """Both --dry-run and --test-channel can be combined."""
        from src.main import parse_args

        with patch('sys.argv', ['main.py', '--mode', 'fetch_and_leaderboard',
                                '--dry-run', '--test-channel']):
            args = parse_args()
            assert args.dry_run is True
            assert args.test_channel is True
            assert args.mode == 'fetch_and_leaderboard'
