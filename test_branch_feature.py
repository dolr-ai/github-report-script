#!/usr/bin/env python3
"""
Quick test script to verify branch feature implementation
"""
import sys
from datetime import datetime, timedelta
from src.data_processor import DataProcessor
from src.chart_generator import ChartGenerator
from src.config import USER_IDS


def test_branch_feature():
    """Test the new branch feature"""
    print("Testing branch feature implementation...")

    # Test date range - last 5 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=5)

    print(f"\nDate range: {start_date.date()} to {end_date.date()}")
    print(f"Users: {USER_IDS}")

    # Initialize processor
    processor = DataProcessor()

    # Process data for the date range
    print("\n1. Processing data with branch breakdown...")
    processor.process_date_range(
        start_date, end_date, USER_IDS, force_refresh=True)

    # Read processed data
    print("\n2. Reading processed data...")
    all_data = processor.read_all_users_data(USER_IDS, start_date, end_date)

    # Check if branch_breakdown exists
    print("\n3. Checking branch_breakdown in processed data...")
    has_branch_data = False
    for username, date_data in all_data.items():
        for date, metrics in date_data.items():
            if 'branch_breakdown' in metrics and metrics['branch_breakdown']:
                print(f"   ✓ Found branch data for {username} on {date}")
                # Show a sample
                for repo, branches in list(metrics['branch_breakdown'].items())[:1]:
                    print(f"     Repository: {repo}")
                    for branch, branch_metrics in branches.items():
                        print(f"       Branch '{branch}': {branch_metrics['commit_count']} commits, "
                              f"{branch_metrics['additions']} additions")
                has_branch_data = True
                break
        if has_branch_data:
            break

    if not has_branch_data:
        print("   ⚠ No branch data found in processed output")
        return False

    # Test chart generation
    print("\n4. Generating charts with branch visualization...")
    generator = ChartGenerator()

    # Test branch detection
    branches = generator._detect_all_branches(all_data)
    print(f"   Detected branches: {branches}")

    # Test branch filtering
    if branches:
        test_branch = branches[0]
        print(f"   Testing filter for branch: {test_branch}")
        filtered_data = generator._filter_data_by_branch(all_data, test_branch)
        print(f"   ✓ Filtering works")

    # Test drill-down data preparation
    drill_down_rows = generator._prepare_drill_down_data(all_data)
    print(f"   Drill-down table has {len(drill_down_rows)} rows")
    if drill_down_rows:
        print(f"   Sample row: {drill_down_rows[0]}")

    # Generate actual reports
    print("\n5. Generating full reports...")
    try:
        results = generator.generate_all_charts(
            all_data,
            start_date.date().isoformat(),
            end_date.date().isoformat()
        )
        print(f"   ✓ HTML report: {results['html']}")
        print(f"   ✓ PNG report: {results['png']}")
        print(f"   ✓ PDF report: {results['pdf']}")
        return True
    except Exception as e:
        print(f"   ✗ Chart generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_branch_feature()
    if success:
        print("\n✅ Branch feature test completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Branch feature test failed")
        sys.exit(1)
