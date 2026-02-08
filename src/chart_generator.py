"""
Chart Generator Module
Generates dual output (Plotly HTML + Matplotlib PNG/PDF) for commit metrics
"""
import os
import logging
import shutil
from datetime import datetime, timedelta
from typing import Dict, List
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.config import REPORTS_DIR

logger = logging.getLogger(__name__)


class ChartGenerator:
    """Generates interactive and static charts for GitHub activity"""

    def __init__(self):
        os.makedirs(REPORTS_DIR, exist_ok=True)

        # Color palette for users (consistent across charts)
        self.colors = [
            '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
            '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'
        ]

    def _prepare_data(self, all_data: Dict[str, Dict[str, Dict]]) -> tuple:
        """Prepare data for charting

        Args:
            all_data: Dictionary mapping usernames to date-indexed metrics

        Returns:
            Tuple of (dates, usernames, additions_data, deletions_data, 
                     total_loc_data, commits_data)
        """
        # Get sorted list of dates
        first_user = next(iter(all_data.values()))
        dates = sorted(first_user.keys())
        usernames = sorted(all_data.keys())

        # Prepare data arrays
        additions_data = {user: [] for user in usernames}
        deletions_data = {user: [] for user in usernames}
        total_loc_data = {user: [] for user in usernames}
        commits_data = {user: [] for user in usernames}

        for username in usernames:
            user_data = all_data[username]
            for date in dates:
                day_data = user_data.get(date, {})
                additions_data[username].append(day_data.get('additions', 0))
                deletions_data[username].append(day_data.get('deletions', 0))
                total_loc_data[username].append(day_data.get('total_loc', 0))
                commits_data[username].append(day_data.get('commit_count', 0))

        return dates, usernames, additions_data, deletions_data, total_loc_data, commits_data

    def _prepare_github_stats_data(self, github_stats: Dict[str, Dict[str, Dict]]) -> tuple:
        """Prepare GitHub contributor stats data for charting

        Args:
            github_stats: Dictionary mapping usernames to week-indexed metrics

        Returns:
            Tuple of (weeks, usernames, additions_data, deletions_data,
                     total_loc_data, commits_data)
        """
        if not github_stats:
            return [], [], {}, {}, {}, {}

        # Get sorted list of weeks across all users
        all_weeks = set()
        for user_data in github_stats.values():
            all_weeks.update(user_data.keys())
        weeks = sorted(all_weeks)

        usernames = sorted(github_stats.keys())

        # Prepare data arrays
        additions_data = {user: [] for user in usernames}
        deletions_data = {user: [] for user in usernames}
        total_loc_data = {user: [] for user in usernames}
        commits_data = {user: [] for user in usernames}

        for username in usernames:
            user_data = github_stats.get(username, {})
            for week in weeks:
                week_data = user_data.get(week, {})
                additions_data[username].append(week_data.get('additions', 0))
                deletions_data[username].append(week_data.get('deletions', 0))
                total_loc_data[username].append(week_data.get('total_loc', 0))
                commits_data[username].append(week_data.get('commits', 0))

        return weeks, usernames, additions_data, deletions_data, total_loc_data, commits_data

    def _detect_all_branches(self, all_data: Dict[str, Dict[str, Dict]]) -> List[str]:
        """Detect all unique branch names from user data

        Args:
            all_data: Dictionary mapping usernames to date-indexed metrics

        Returns:
            Sorted list of unique branch names
        """
        branches = set()
        for username, date_data in all_data.items():
            for date, metrics in date_data.items():
                branch_breakdown = metrics.get('branch_breakdown', {})
                for repo, repo_branches in branch_breakdown.items():
                    branches.update(repo_branches.keys())

        # Sort branches, prioritizing common ones
        priority_branches = ['main', 'master', 'develop',
                             'development', 'staging', 'production']
        sorted_branches = []

        for branch in priority_branches:
            if branch in branches:
                sorted_branches.append(branch)
                branches.remove(branch)

        # Add remaining branches alphabetically
        sorted_branches.extend(sorted(branches))

        return sorted_branches

    def _filter_data_by_branch(self, all_data: Dict[str, Dict[str, Dict]],
                               branch_filter: str) -> Dict[str, Dict[str, Dict]]:
        """Filter data to include only commits from specific branch(es)

        Args:
            all_data: Dictionary mapping usernames to date-indexed metrics
            branch_filter: Branch name to filter by, or 'all' for all branches

        Returns:
            Filtered data dictionary with same structure
        """
        if branch_filter == 'all':
            return all_data

        filtered_data = {}

        for username, date_data in all_data.items():
            filtered_data[username] = {}

            for date, metrics in date_data.items():
                # Start with zero values
                filtered_metrics = {
                    'date': date,
                    'username': username,
                    'additions': 0,
                    'deletions': 0,
                    'total_loc': 0,
                    'commit_count': 0,
                    'repositories': [],
                    'repo_count': 0,
                    'branch_breakdown': {}
                }

                branch_breakdown = metrics.get('branch_breakdown', {})
                repos_with_branch = set()

                for repo, repo_branches in branch_breakdown.items():
                    if branch_filter in repo_branches:
                        branch_metrics = repo_branches[branch_filter]
                        filtered_metrics['additions'] += branch_metrics.get(
                            'additions', 0)
                        filtered_metrics['deletions'] += branch_metrics.get(
                            'deletions', 0)
                        filtered_metrics['total_loc'] += branch_metrics.get(
                            'total_loc', 0)
                        filtered_metrics['commit_count'] += branch_metrics.get(
                            'commit_count', 0)
                        repos_with_branch.add(repo)

                filtered_metrics['repositories'] = sorted(
                    list(repos_with_branch))
                filtered_metrics['repo_count'] = len(repos_with_branch)

                filtered_data[username][date] = filtered_metrics

        return filtered_data

    def _prepare_drill_down_data(self, all_data: Dict[str, Dict[str, Dict]]) -> List[Dict]:
        """Prepare detailed drill-down data for interactive table

        Args:
            all_data: Dictionary mapping usernames to date-indexed metrics

        Returns:
            List of dictionaries, each representing a row in the drill-down table
        """
        rows = []

        for username, date_data in all_data.items():
            for date, metrics in date_data.items():
                branch_breakdown = metrics.get('branch_breakdown', {})

                for repo, repo_branches in branch_breakdown.items():
                    for branch, branch_metrics in repo_branches.items():
                        if branch_metrics.get('commit_count', 0) > 0:
                            rows.append({
                                'user': username,
                                'date': date,
                                'repository': repo,
                                'branch': branch,
                                'commits': branch_metrics.get('commit_count', 0),
                                'additions': branch_metrics.get('additions', 0),
                                'deletions': branch_metrics.get('deletions', 0),
                                'total_loc': branch_metrics.get('total_loc', 0)
                            })

        # Sort by date (descending), then user, then repository, then branch
        rows.sort(key=lambda x: (x['date'], x['user'],
                  x['repository'], x['branch']), reverse=True)

        return rows

    def _get_filename_base(self, start_date: str, end_date: str) -> str:
        """Generate base filename for reports and create dated folder

        Args:
            start_date: Start date string
            end_date: End date string

        Returns:
            Base filename without timestamp (date only)
        """
        # Create folder with generation date
        generation_date = datetime.now().strftime('%Y%m%d')
        dated_folder = os.path.join(REPORTS_DIR, generation_date)
        os.makedirs(dated_folder, exist_ok=True)

        # Return path with folder
        base_name = f"report_{start_date}_to_{end_date}"
        return os.path.join(generation_date, base_name)

    def generate_plotly_chart(self, all_data: Dict[str, Dict[str, Dict]],
                              start_date: str, end_date: str,
                              github_stats: Dict[str, Dict[str, Dict]] = None) -> str:
        """Generate interactive Plotly HTML chart

        Args:
            all_data: Dictionary mapping usernames to date-indexed metrics
            start_date: Start date string
            end_date: End date string
            github_stats: Optional dictionary mapping usernames to week-indexed GitHub stats

        Returns:
            Path to generated HTML file
        """
        logger.info(
            f"Generating Plotly chart for {len(all_data)} users")

        # Prepare data (show all branches)
        dates, usernames, additions_data, deletions_data, total_loc_data, commits_data = \
            self._prepare_data(all_data)

        # Create 2x2 subplot layout
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                'Daily Additions (Lines Added)',
                'Daily Deletions (Lines Removed)',
                'Daily Total LOC Changed',
                'Daily Commit Count'
            ),
            vertical_spacing=0.12,
            horizontal_spacing=0.1
        )

        # Add traces for each user
        for idx, username in enumerate(usernames):
            color = self.colors[idx % len(self.colors)]

            # Additions
            fig.add_trace(
                go.Scatter(
                    name=username,
                    x=dates,
                    y=additions_data[username],
                    mode='lines+markers',
                    line=dict(color=color, width=2),
                    marker=dict(size=6),
                    legendgroup=username,
                    showlegend=True,
                    hovertemplate='%{x}<br>Additions: %{y}<extra></extra>'
                ),
                row=1, col=1
            )

            # Deletions
            fig.add_trace(
                go.Scatter(
                    name=username,
                    x=dates,
                    y=deletions_data[username],
                    mode='lines+markers',
                    line=dict(color=color, width=2),
                    marker=dict(size=6),
                    legendgroup=username,
                    showlegend=False,
                    hovertemplate='%{x}<br>Deletions: %{y}<extra></extra>'
                ),
                row=1, col=2
            )

            # Total LOC
            fig.add_trace(
                go.Scatter(
                    name=username,
                    x=dates,
                    y=total_loc_data[username],
                    mode='lines+markers',
                    line=dict(color=color, width=2),
                    marker=dict(size=6),
                    legendgroup=username,
                    showlegend=False,
                    hovertemplate='%{x}<br>Total LOC: %{y}<extra></extra>'
                ),
                row=2, col=1
            )

            # Commits
            fig.add_trace(
                go.Scatter(
                    name=username,
                    x=dates,
                    y=commits_data[username],
                    mode='lines+markers',
                    line=dict(color=color, width=2),
                    marker=dict(size=6),
                    legendgroup=username,
                    showlegend=False,
                    hovertemplate='%{x}<br>Commits: %{y}<extra></extra>'
                ),
                row=2, col=2
            )

        # Update layout without dropdown menu
        fig.update_layout(
            title_text=f"GitHub Activity Report ({start_date} to {end_date})",
            title_font_size=20,
            showlegend=True,
            height=900,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            hovermode='x unified'
        )

        # Update axes
        fig.update_xaxes(title_text="Date", row=2, col=1)
        fig.update_xaxes(title_text="Date", row=2, col=2)
        fig.update_yaxes(title_text="Lines", row=1, col=1)
        fig.update_yaxes(title_text="Lines", row=1, col=2)
        fig.update_yaxes(title_text="Lines", row=2, col=1)
        fig.update_yaxes(title_text="Commits", row=2, col=2)

        # Save main chart to file
        filename = self._get_filename_base(start_date, end_date) + '.html'
        filepath = os.path.join(REPORTS_DIR, filename)

        # Generate drill-down table HTML
        table_html = self._create_drill_down_table(all_data)

        # Generate GitHub stats charts if data is available
        github_stats_fig = None
        if github_stats:
            github_stats_fig = self._generate_github_stats_charts(
                github_stats, start_date, end_date)

        # Combine both figures into a single HTML file
        with open(filepath, 'w') as f:
            f.write('<html><head><meta charset="utf-8" />')
            f.write('<title>GitHub Activity Report</title>')
            f.write(
                '</head><body style="margin: 0; padding: 0; font-family: Arial, sans-serif;">')

            # Section 1: Branch-Based Calculations
            f.write('<div style="width: 100%; margin-bottom: 40px;">')
            f.write('<h2 style="margin: 20px; padding: 20px 0 10px 0; color: #333; border-bottom: 2px solid #4a90e2;">Branch-Based Calculations</h2>')
            f.write(fig.to_html(include_plotlyjs='cdn',
                    full_html=False, div_id='main-chart'))
            f.write('</div>')

            # Section 2: GitHub Official Stats (if available)
            if github_stats_fig:
                f.write(
                    '<div style="width: 100%; margin-bottom: 40px; margin-top: 60px;">')
                f.write(
                    '<h2 style="margin: 20px; padding: 20px 0 10px 0; color: #333; border-bottom: 2px solid #4a90e2;">GitHub Official Stats</h2>')
                f.write(github_stats_fig.to_html(include_plotlyjs=False,
                        full_html=False, div_id='github-stats-chart'))
                f.write('</div>')

            # Drill-down table section with header
            f.write(
                '<div style="margin: 60px 20px 20px 20px; padding: 20px; background-color: #f5f5f5; border-radius: 8px;">')
            f.write(
                '<h2 style="margin-top: 0; color: #333;">Detailed Breakdown by Repository and Branch</h2>')
            f.write('<p style="color: #666; margin-bottom: 20px;">Click on contributors to expand and see their repositories. Click on repositories to see branches. Click column headers to sort.</p>')
            f.write(table_html)
            f.write('</div>')

            f.write('</body></html>')

        return filepath

    def _generate_github_stats_charts(self, github_stats: Dict[str, Dict[str, Dict]],
                                      start_date: str, end_date: str) -> go.Figure:
        """Generate GitHub contributor stats charts (4 charts in 2x2 layout)

        Args:
            github_stats: Dictionary mapping usernames to week-indexed metrics
            start_date: Start date string
            end_date: End date string

        Returns:
            Plotly figure with 4 subplots showing GitHub's official stats
        """
        logger.info(
            f"Generating GitHub stats charts for {len(github_stats)} users")

        # Prepare GitHub stats data
        weeks, usernames, additions_data, deletions_data, total_loc_data, commits_data = \
            self._prepare_github_stats_data(github_stats)

        if not weeks or not usernames:
            logger.warning("No GitHub stats data available for charting")
            return None

        # Create 2x2 subplot layout
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                'GitHub Stats: Weekly Additions (Lines Added)',
                'GitHub Stats: Weekly Deletions (Lines Removed)',
                'GitHub Stats: Weekly Total LOC Changed',
                'GitHub Stats: Weekly Commit Count'
            ),
            vertical_spacing=0.12,
            horizontal_spacing=0.1
        )

        # Add bar traces for each user
        for idx, username in enumerate(usernames):
            color = self.colors[idx % len(self.colors)]

            # Additions
            fig.add_trace(
                go.Bar(
                    name=username,
                    x=weeks,
                    y=additions_data[username],
                    marker=dict(color=color),
                    legendgroup=username,
                    showlegend=True,
                    hovertemplate='%{x}<br>Additions: %{y}<extra></extra>'
                ),
                row=1, col=1
            )

            # Deletions
            fig.add_trace(
                go.Bar(
                    name=username,
                    x=weeks,
                    y=deletions_data[username],
                    marker=dict(color=color),
                    legendgroup=username,
                    showlegend=False,
                    hovertemplate='%{x}<br>Deletions: %{y}<extra></extra>'
                ),
                row=1, col=2
            )

            # Total LOC
            fig.add_trace(
                go.Bar(
                    name=username,
                    x=weeks,
                    y=total_loc_data[username],
                    marker=dict(color=color),
                    legendgroup=username,
                    showlegend=False,
                    hovertemplate='%{x}<br>Total LOC: %{y}<extra></extra>'
                ),
                row=2, col=1
            )

            # Commits
            fig.add_trace(
                go.Bar(
                    name=username,
                    x=weeks,
                    y=commits_data[username],
                    marker=dict(color=color),
                    legendgroup=username,
                    showlegend=False,
                    hovertemplate='%{x}<br>Commits: %{y}<extra></extra>'
                ),
                row=2, col=2
            )

        # Update layout
        fig.update_layout(
            title_text=f"GitHub Official Stats ({start_date} to {end_date})",
            title_font_size=20,
            showlegend=True,
            height=900,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            hovermode='x unified',
            barmode='group'
        )

        # Update axes
        fig.update_xaxes(title_text="Week", row=2, col=1)
        fig.update_xaxes(title_text="Week", row=2, col=2)
        fig.update_yaxes(title_text="Lines", row=1, col=1)
        fig.update_yaxes(title_text="Lines", row=1, col=2)
        fig.update_yaxes(title_text="Lines", row=2, col=1)
        fig.update_yaxes(title_text="Commits", row=2, col=2)

        return fig

    def _create_drill_down_table(self, all_data: Dict[str, Dict[str, Dict]]) -> str:
        """Create interactive drill-down table HTML showing repository and branch details

        Args:
            all_data: Dictionary mapping usernames to date-indexed metrics

        Returns:
            HTML string containing the interactive drill-down table
        """
        # Aggregate data hierarchically: user -> repo -> branch
        hierarchy = {}

        for username, date_data in all_data.items():
            if username not in hierarchy:
                hierarchy[username] = {
                    'repos': {},
                    'total_commits': 0,
                    'total_additions': 0,
                    'total_deletions': 0,
                    'total_loc': 0
                }

            for date, metrics in date_data.items():
                branch_breakdown = metrics.get('branch_breakdown', {})

                for repo, repo_branches in branch_breakdown.items():
                    if repo not in hierarchy[username]['repos']:
                        hierarchy[username]['repos'][repo] = {
                            'branches': {},
                            'total_commits': 0,
                            'total_additions': 0,
                            'total_deletions': 0,
                            'total_loc': 0
                        }

                    for branch, branch_metrics in repo_branches.items():
                        if branch not in hierarchy[username]['repos'][repo]['branches']:
                            hierarchy[username]['repos'][repo]['branches'][branch] = {
                                'commits': 0,
                                'additions': 0,
                                'deletions': 0,
                                'total_loc': 0
                            }

                        # Aggregate metrics
                        commits = branch_metrics.get('commit_count', 0)
                        additions = branch_metrics.get('additions', 0)
                        deletions = branch_metrics.get('deletions', 0)
                        total_loc = branch_metrics.get('total_loc', 0)

                        hierarchy[username]['repos'][repo]['branches'][branch]['commits'] += commits
                        hierarchy[username]['repos'][repo]['branches'][branch]['additions'] += additions
                        hierarchy[username]['repos'][repo]['branches'][branch]['deletions'] += deletions
                        hierarchy[username]['repos'][repo]['branches'][branch]['total_loc'] += total_loc

                        hierarchy[username]['repos'][repo]['total_commits'] += commits
                        hierarchy[username]['repos'][repo]['total_additions'] += additions
                        hierarchy[username]['repos'][repo]['total_deletions'] += deletions
                        hierarchy[username]['repos'][repo]['total_loc'] += total_loc

                        hierarchy[username]['total_commits'] += commits
                        hierarchy[username]['total_additions'] += additions
                        hierarchy[username]['total_deletions'] += deletions
                        hierarchy[username]['total_loc'] += total_loc

        # Generate HTML with JavaScript for interactivity
        html = """
        <style>
            .drill-down-table {
                width: 100%;
                border-collapse: collapse;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                font-size: 14px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }
            .drill-down-table th {
                background-color: #4a90e2;
                color: white;
                padding: 12px;
                text-align: left;
                font-weight: 600;
                position: sticky;
                top: 0;
                z-index: 10;
            }
            .drill-down-table td {
                padding: 10px 12px;
                border-bottom: 1px solid #e0e0e0;
            }
            .drill-down-table .numeric {
                text-align: right;
                font-family: 'Courier New', monospace;
            }
            .user-row {
                background-color: #f8f9fa;
                font-weight: 600;
                cursor: pointer;
                transition: background-color 0.2s;
            }
            .user-row:hover {
                background-color: #e9ecef;
            }
            .repo-row {
                background-color: #ffffff;
                cursor: pointer;
                transition: background-color 0.2s;
                padding-left: 30px !important;
            }
            .repo-row:hover {
                background-color: #f1f3f5;
            }
            .branch-row {
                background-color: #fafbfc;
                padding-left: 60px !important;
            }
            .branch-row.main-branch {
                background-color: #d4edda;
            }
            .branch-row.unknown-branch {
                background-color: #f8d7da;
            }
            .expandable::before {
                content: '▶';
                display: inline-block;
                margin-right: 8px;
                transition: transform 0.2s;
                font-size: 12px;
            }
            .expanded::before {
                transform: rotate(90deg);
            }
            .hidden {
                display: none;
            }
            .positive {
                color: #28a745;
            }
            .negative {
                color: #dc3545;
            }
            .sort-icon {
                cursor: pointer;
                user-select: none;
                margin-left: 5px;
                opacity: 0.5;
            }
            .sort-icon:hover {
                opacity: 1;
            }
            .sort-icon.active {
                opacity: 1;
                font-weight: bold;
            }
        </style>
        
        <table class="drill-down-table" id="drillDownTable">
            <thead>
                <tr>
                    <th style="width: 30%;">
                        Contributor / Repository / Branch 
                        <span class="sort-icon" onclick="sortTable(0)">↕</span>
                    </th>
                    <th style="width: 12%;" class="numeric">
                        Commits
                        <span class="sort-icon" onclick="sortTable(1)">↕</span>
                    </th>
                    <th style="width: 16%;" class="numeric">
                        Lines Added
                        <span class="sort-icon" onclick="sortTable(2)">↕</span>
                    </th>
                    <th style="width: 16%;" class="numeric">
                        Lines Removed
                        <span class="sort-icon" onclick="sortTable(3)">↕</span>
                    </th>
                    <th style="width: 16%;" class="numeric">
                        Total LOC
                        <span class="sort-icon" onclick="sortTable(4)">↕</span>
                    </th>
                    <th style="width: 10%;" class="numeric">
                        Repos/Branches
                    </th>
                </tr>
            </thead>
            <tbody>
        """

        # Sort users by total commits (descending)
        sorted_users = sorted(
            hierarchy.items(), key=lambda x: x[1]['total_commits'], reverse=True)

        for username, user_data in sorted_users:
            repo_count = len(user_data['repos'])
            total_branches = sum(len(r['branches'])
                                 for r in user_data['repos'].values())

            html += f"""
                <tr class="user-row" onclick="toggleUser('{username}')" data-level="user" data-id="{username}">
                    <td class="expandable">{username}</td>
                    <td class="numeric">{user_data['total_commits']:,}</td>
                    <td class="numeric positive">+{user_data['total_additions']:,}</td>
                    <td class="numeric negative">-{user_data['total_deletions']:,}</td>
                    <td class="numeric">{user_data['total_loc']:,}</td>
                    <td class="numeric">{repo_count} / {total_branches}</td>
                </tr>
            """

            # Sort repos by commits
            sorted_repos = sorted(user_data['repos'].items(
            ), key=lambda x: x[1]['total_commits'], reverse=True)

            for repo, repo_data in sorted_repos:
                branch_count = len(repo_data['branches'])
                repo_id = f"{username}_{repo}".replace(
                    '/', '_').replace('.', '_')

                html += f"""
                    <tr class="repo-row hidden" data-parent="{username}" data-level="repo" data-id="{repo_id}" onclick="toggleRepo('{repo_id}', event)">
                        <td class="expandable" style="padding-left: 30px;">{repo}</td>
                        <td class="numeric">{repo_data['total_commits']:,}</td>
                        <td class="numeric positive">+{repo_data['total_additions']:,}</td>
                        <td class="numeric negative">-{repo_data['total_deletions']:,}</td>
                        <td class="numeric">{repo_data['total_loc']:,}</td>
                        <td class="numeric">{branch_count}</td>
                    </tr>
                """

                # Sort branches by commits
                sorted_branches = sorted(repo_data['branches'].items(
                ), key=lambda x: x[1]['commits'], reverse=True)

                for branch, branch_data in sorted_branches:
                    branch_class = ""
                    if branch in ['main', 'master']:
                        branch_class = "main-branch"
                    elif branch == 'unknown':
                        branch_class = "unknown-branch"

                    html += f"""
                        <tr class="branch-row {branch_class} hidden" data-parent="{repo_id}" data-level="branch">
                            <td style="padding-left: 60px;">{branch}</td>
                            <td class="numeric">{branch_data['commits']:,}</td>
                            <td class="numeric positive">+{branch_data['additions']:,}</td>
                            <td class="numeric negative">-{branch_data['deletions']:,}</td>
                            <td class="numeric">{branch_data['total_loc']:,}</td>
                            <td class="numeric">-</td>
                        </tr>
                    """

        html += """
            </tbody>
        </table>
        
        <script>
            function toggleUser(username) {
                const userRow = document.querySelector(`[data-id="${username}"]`);
                const repoRows = document.querySelectorAll(`[data-parent="${username}"]`);
                const isExpanded = userRow.classList.contains('expanded');
                
                if (isExpanded) {
                    userRow.classList.remove('expanded');
                    repoRows.forEach(row => {
                        row.classList.add('hidden');
                        row.classList.remove('expanded');
                        // Also hide all branch rows under this user
                        const repoId = row.getAttribute('data-id');
                        if (repoId) {
                            document.querySelectorAll(`[data-parent="${repoId}"]`).forEach(br => {
                                br.classList.add('hidden');
                            });
                        }
                    });
                } else {
                    userRow.classList.add('expanded');
                    repoRows.forEach(row => row.classList.remove('hidden'));
                }
            }
            
            function toggleRepo(repoId, event) {
                event.stopPropagation();
                const repoRow = document.querySelector(`[data-id="${repoId}"]`);
                const branchRows = document.querySelectorAll(`[data-parent="${repoId}"]`);
                const isExpanded = repoRow.classList.contains('expanded');
                
                if (isExpanded) {
                    repoRow.classList.remove('expanded');
                    branchRows.forEach(row => row.classList.add('hidden'));
                } else {
                    repoRow.classList.add('expanded');
                    branchRows.forEach(row => row.classList.remove('hidden'));
                }
            }
            
            let sortColumn = -1;
            let sortAscending = true;
            
            function sortTable(columnIndex) {
                const table = document.getElementById('drillDownTable');
                const tbody = table.querySelector('tbody');
                const rows = Array.from(tbody.querySelectorAll('tr[data-level="user"]'));
                
                // Toggle sort direction if same column
                if (sortColumn === columnIndex) {
                    sortAscending = !sortAscending;
                } else {
                    sortColumn = columnIndex;
                    sortAscending = false; // Default to descending for numbers
                }
                
                // Update sort icons
                document.querySelectorAll('.sort-icon').forEach(icon => icon.classList.remove('active'));
                document.querySelectorAll('.sort-icon')[columnIndex].classList.add('active');
                
                rows.sort((a, b) => {
                    let aVal, bVal;
                    
                    if (columnIndex === 0) {
                        aVal = a.cells[columnIndex].textContent.trim();
                        bVal = b.cells[columnIndex].textContent.trim();
                        return sortAscending ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
                    } else {
                        aVal = parseInt(a.cells[columnIndex].textContent.replace(/[^0-9]/g, ''));
                        bVal = parseInt(b.cells[columnIndex].textContent.replace(/[^0-9]/g, ''));
                        return sortAscending ? aVal - bVal : bVal - aVal;
                    }
                });
                
                // Clear and re-append in sorted order
                tbody.innerHTML = '';
                rows.forEach(userRow => {
                    tbody.appendChild(userRow);
                    const username = userRow.getAttribute('data-id');
                    // Append repo rows for this user
                    const repoRows = Array.from(table.querySelectorAll(`[data-parent="${username}"]`));
                    repoRows.forEach(repoRow => {
                        tbody.appendChild(repoRow);
                        const repoId = repoRow.getAttribute('data-id');
                        if (repoId) {
                            // Append branch rows for this repo
                            const branchRows = Array.from(table.querySelectorAll(`[data-parent="${repoId}"]`));
                            branchRows.forEach(branchRow => tbody.appendChild(branchRow));
                        }
                    });
                });
            }
        </script>
        """

        return html

    def cleanup_old_reports(self, days_to_keep: int = 90):
        """Remove report folders older than specified days

        Args:
            days_to_keep: Number of days to retain reports (default: 90)
        """
        logger.info(f"Cleaning up reports older than {days_to_keep} days...")

        reports_path = Path(REPORTS_DIR)
        if not reports_path.exists():
            return

        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        removed_count = 0

        # Iterate through all directories in reports/
        for item in reports_path.iterdir():
            if item.is_dir() and item.name.isdigit() and len(item.name) == 8:
                # Parse folder name as YYYYMMDD
                try:
                    folder_date = datetime.strptime(item.name, '%Y%m%d')
                    if folder_date < cutoff_date:
                        logger.info(f"Removing old report folder: {item.name}")
                        shutil.rmtree(item)
                        removed_count += 1
                except ValueError:
                    # Skip folders that don't match date format
                    continue

        if removed_count > 0:
            logger.info(f"Removed {removed_count} old report folder(s)")
        else:
            logger.info("No old reports to clean up")

    def generate_index_page(self):
        """Generate index.html page listing all available reports"""
        logger.info("Generating index page...")

        reports_path = Path(REPORTS_DIR)
        if not reports_path.exists():
            reports_path.mkdir(parents=True, exist_ok=True)

        # Find all report HTML files
        report_files = []
        for item in reports_path.iterdir():
            if item.is_dir() and item.name.isdigit() and len(item.name) == 8:
                # Look for HTML files in this folder
                for html_file in item.glob('*.html'):
                    try:
                        folder_date = datetime.strptime(item.name, '%Y%m%d')
                        report_files.append({
                            'date': folder_date,
                            'folder': item.name,
                            'filename': html_file.name,
                            'path': f"{item.name}/{html_file.name}"
                        })
                    except ValueError:
                        continue

        # Sort by date (most recent first)
        report_files.sort(key=lambda x: x['date'], reverse=True)

        # Generate simple HTML index
        html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GitHub Activity Reports</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            line-height: 1.6;
        }
        h1 {
            color: #333;
            border-bottom: 2px solid #0366d6;
            padding-bottom: 10px;
        }
        ul {
            list-style: none;
            padding: 0;
        }
        li {
            margin: 10px 0;
            padding: 10px;
            background: #f6f8fa;
            border-radius: 6px;
        }
        a {
            color: #0366d6;
            text-decoration: none;
            font-weight: 500;
        }
        a:hover {
            text-decoration: underline;
        }
        .date {
            color: #586069;
            font-size: 0.9em;
        }
        .empty {
            color: #586069;
            font-style: italic;
        }
    </style>
</head>
<body>
    <h1>GitHub Activity Reports</h1>
'''

        if report_files:
            html += '    <ul>\n'
            for report in report_files:
                date_str = report['date'].strftime('%B %d, %Y')
                html += f'        <li><a href="{report["path"]}">{report["filename"]}</a> <span class="date">({date_str})</span></li>\n'
            html += '    </ul>\n'
        else:
            html += '    <p class="empty">No reports available yet.</p>\n'

        html += '''</body>
</html>
'''

        # Write index.html
        index_path = reports_path / 'index.html'
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(html)

        # Create .nojekyll file to prevent Jekyll processing
        nojekyll_path = reports_path / '.nojekyll'
        nojekyll_path.touch()

        logger.info(f"Index page generated: {index_path}")
        logger.info(f"Created .nojekyll file: {nojekyll_path}")

    def generate_all_charts(self, all_data: Dict[str, Dict[str, Dict]],
                            start_date: str, end_date: str) -> Dict[str, str]:
        """Generate HTML chart report

        Args:
            all_data: Dictionary mapping usernames to date-indexed metrics
            start_date: Start date string
            end_date: End date string

        Returns:
            Dictionary with path to generated HTML file
        """
        from src.data_processor import DataProcessor
        from datetime import datetime

        logger.info("Starting chart generation")

        # Load GitHub stats if available
        github_stats = None
        try:
            processor = DataProcessor()
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            github_stats = processor.read_github_stats_data(start_dt, end_dt)

            if github_stats:
                logger.info(
                    f"Loaded GitHub stats for {len(github_stats)} users")
            else:
                logger.info("No GitHub stats data available")
        except Exception as e:
            logger.warning(f"Could not load GitHub stats: {e}")

        # Generate Plotly HTML with both branch-based and GitHub stats
        logger.info("Creating interactive HTML chart...")
        html_path = self.generate_plotly_chart(
            all_data, start_date, end_date, github_stats)

        # Cleanup old reports (keep last 90 days)
        self.cleanup_old_reports(days_to_keep=90)

        # Generate index page
        self.generate_index_page()

        results = {
            'html': html_path
        }

        logger.info("Chart generated successfully:")
        logger.info(f"  Interactive HTML: {html_path}")

        return results
