"""
Chart Generator Module
Generates dual output (Plotly HTML + Matplotlib PNG/PDF) for commit metrics
"""
import os
import logging
from datetime import datetime
from typing import Dict, List

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
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
                              start_date: str, end_date: str) -> str:
        """Generate interactive Plotly HTML chart

        Args:
            all_data: Dictionary mapping usernames to date-indexed metrics
            start_date: Start date string
            end_date: End date string

        Returns:
            Path to generated HTML file
        """
        logger.info(
            f"Generating Plotly chart for {len(all_data)} users")

        # Detect all branches for dropdown
        all_branches = self._detect_all_branches(all_data)
        logger.info(f"Detected branches: {all_branches}")

        # Prepare data for all branches and individual branch filters
        branch_filters = ['all'] + all_branches
        traces_by_filter = {}

        for branch_filter in branch_filters:
            filtered_data = self._filter_data_by_branch(
                all_data, branch_filter)
            dates, usernames, additions_data, deletions_data, total_loc_data, commits_data = \
                self._prepare_data(filtered_data)

            traces_by_filter[branch_filter] = {
                'dates': dates,
                'usernames': usernames,
                'additions': additions_data,
                'deletions': deletions_data,
                'total_loc': total_loc_data,
                'commits': commits_data
            }

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

        # Get the "all branches" data for initial display
        initial_data = traces_by_filter['all']
        dates = initial_data['dates']
        usernames = initial_data['usernames']

        # Add traces for each user and each branch filter
        for branch_filter in branch_filters:
            data = traces_by_filter[branch_filter]
            visible = (branch_filter == 'all')  # Only 'all' visible initially

            for idx, username in enumerate(data['usernames']):
                color = self.colors[idx % len(self.colors)]

                # Additions
                fig.add_trace(
                    go.Scatter(
                        name=username,
                        x=data['dates'],
                        y=data['additions'][username],
                        mode='lines+markers',
                        line=dict(color=color, width=2),
                        marker=dict(size=6),
                        legendgroup=username,
                        # Only show legend for first set
                        showlegend=(branch_filter == 'all'),
                        visible=visible,
                        hovertemplate='%{x}<br>Additions: %{y}<extra></extra>'
                    ),
                    row=1, col=1
                )

                # Deletions
                fig.add_trace(
                    go.Scatter(
                        name=username,
                        x=data['dates'],
                        y=data['deletions'][username],
                        mode='lines+markers',
                        line=dict(color=color, width=2),
                        marker=dict(size=6),
                        legendgroup=username,
                        showlegend=False,
                        visible=visible,
                        hovertemplate='%{x}<br>Deletions: %{y}<extra></extra>'
                    ),
                    row=1, col=2
                )

                # Total LOC
                fig.add_trace(
                    go.Scatter(
                        name=username,
                        x=data['dates'],
                        y=data['total_loc'][username],
                        mode='lines+markers',
                        line=dict(color=color, width=2),
                        marker=dict(size=6),
                        legendgroup=username,
                        showlegend=False,
                        visible=visible,
                        hovertemplate='%{x}<br>Total LOC: %{y}<extra></extra>'
                    ),
                    row=2, col=1
                )

                # Commits
                fig.add_trace(
                    go.Scatter(
                        name=username,
                        x=data['dates'],
                        y=data['commits'][username],
                        mode='lines+markers',
                        line=dict(color=color, width=2),
                        marker=dict(size=6),
                        legendgroup=username,
                        showlegend=False,
                        visible=visible,
                        hovertemplate='%{x}<br>Commits: %{y}<extra></extra>'
                    ),
                    row=2, col=2
                )

        # Create dropdown buttons for branch filtering
        num_users = len(usernames)
        total_traces = len(branch_filters) * num_users * 4
        dropdown_buttons = []

        for idx, branch_filter in enumerate(branch_filters):
            # Calculate which traces should be visible for this filter
            # Each filter has 4 traces per user (4 subplots)
            visible_array = [False] * total_traces
            start_idx = idx * num_users * 4
            end_idx = start_idx + num_users * 4
            for i in range(start_idx, end_idx):
                visible_array[i] = True

            label = f"All Branches" if branch_filter == 'all' else f"Branch: {branch_filter}"
            dropdown_buttons.append(
                dict(
                    label=label,
                    method="update",
                    args=[{"visible": visible_array}]
                )
            )

        # Update layout with dropdown menu
        fig.update_layout(
            title_text=f"GitHub Activity Report ({start_date} to {end_date})",
            title_font_size=20,
            showlegend=True,
            height=900,
            updatemenus=[
                dict(
                    buttons=dropdown_buttons,
                    direction="down",
                    pad={"r": 10, "t": 10},
                    showactive=True,
                    x=0.01,
                    xanchor="left",
                    y=1.15,
                    yanchor="top",
                    bgcolor="white",
                    bordercolor="#888",
                    borderwidth=1
                )
            ],
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

        # Combine both figures into a single HTML file
        with open(filepath, 'w') as f:
            f.write('<html><head><meta charset="utf-8" />')
            f.write('<title>GitHub Activity Report</title>')
            f.write(
                '</head><body style="margin: 0; padding: 0; font-family: Arial, sans-serif;">')

            # Main chart
            f.write('<div style="width: 100%;">')
            f.write(fig.to_html(include_plotlyjs='cdn',
                    full_html=False, div_id='main-chart'))
            f.write('</div>')

            # Drill-down table section with header
            f.write(
                '<div style="margin: 20px; padding: 20px; background-color: #f5f5f5; border-radius: 8px;">')
            f.write(
                '<h2 style="margin-top: 0; color: #333;">Detailed Breakdown by Repository and Branch</h2>')
            f.write('<p style="color: #666; margin-bottom: 20px;">Click on contributors to expand and see their repositories. Click on repositories to see branches. Click column headers to sort.</p>')
            f.write(table_html)
            f.write('</div>')

            f.write('</body></html>')

        return filepath

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

    def generate_matplotlib_charts(self, all_data: Dict[str, Dict[str, Dict]],
                                   start_date: str, end_date: str) -> Dict[str, str]:
        """Generate static Matplotlib PNG and PDF charts

        Args:
            all_data: Dictionary mapping usernames to date-indexed metrics
            start_date: Start date string
            end_date: End date string

        Returns:
            Dictionary with paths to generated PNG and PDF files
        """
        dates, usernames, additions_data, deletions_data, total_loc_data, commits_data = \
            self._prepare_data(all_data)

        # Create figure with 2x2 subplots
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle(f'GitHub Activity Report ({start_date} to {end_date})',
                     fontsize=18, fontweight='bold')

        # Plot each metric
        def plot_lines(ax, data_dict, title, ylabel):
            for idx, username in enumerate(usernames):
                color = self.colors[idx % len(self.colors)]
                ax.plot(dates, data_dict[username],
                        marker='o', linewidth=2, markersize=6,
                        label=username, color=color, alpha=0.8)

            ax.set_xlabel('Date', fontsize=11)
            ax.set_ylabel(ylabel, fontsize=11)
            ax.set_title(title, fontsize=13, fontweight='bold')
            ax.tick_params(axis='x', rotation=45)
            ax.legend(loc='upper left', framealpha=0.9, fontsize=9)
            ax.grid(True, alpha=0.3, linestyle='--')
            ax.set_axisbelow(True)

        # Plot all four metrics (2x2 grid)
        plot_lines(axes[0, 0], additions_data,
                   'Daily Additions (Lines Added)', 'Lines')
        plot_lines(axes[0, 1], deletions_data,
                   'Daily Deletions (Lines Removed)', 'Lines')
        plot_lines(axes[1, 0], total_loc_data,
                   'Daily Total LOC Changed', 'Lines')
        plot_lines(axes[1, 1], commits_data,
                   'Daily Commit Count', 'Commits')

        plt.tight_layout()

        # Save as PNG and PDF
        base_filename = self._get_filename_base(start_date, end_date)
        png_path = os.path.join(REPORTS_DIR, base_filename + '.png')
        pdf_path = os.path.join(REPORTS_DIR, base_filename + '.pdf')

        plt.savefig(png_path, dpi=300, bbox_inches='tight')
        plt.savefig(pdf_path, bbox_inches='tight')
        plt.close()

        return {
            'png': png_path,
            'pdf': pdf_path
        }

    def _add_branch_distribution_chart(self, ax, all_data: Dict[str, Dict[str, Dict]]):
        """Add branch distribution donut chart to matplotlib axis

        Args:
            ax: Matplotlib axis
            all_data: Dictionary mapping usernames to date-indexed metrics
        """
        # Aggregate commits by branch across all users and dates
        branch_commits = {}

        for username, date_data in all_data.items():
            for date, metrics in date_data.items():
                branch_breakdown = metrics.get('branch_breakdown', {})
                for repo, repo_branches in branch_breakdown.items():
                    for branch, branch_metrics in repo_branches.items():
                        if branch not in branch_commits:
                            branch_commits[branch] = 0
                        branch_commits[branch] += branch_metrics.get(
                            'commit_count', 0)

        if not branch_commits:
            ax.text(0.5, 0.5, 'No branch data available',
                    ha='center', va='center', fontsize=12, color='gray')
            ax.set_title('Branch Distribution', fontsize=13, fontweight='bold')
            ax.axis('off')
            return

        # Sort branches by commit count
        sorted_branches = sorted(
            branch_commits.items(), key=lambda x: x[1], reverse=True)

        # Take top 8 branches, group rest as "Other"
        if len(sorted_branches) > 8:
            top_branches = sorted_branches[:8]
            other_count = sum(count for _, count in sorted_branches[8:])
            top_branches.append(('Other', other_count))
        else:
            top_branches = sorted_branches

        labels = [branch for branch, _ in top_branches]
        sizes = [count for _, count in top_branches]

        # Create color mapping for branches
        branch_colors_map = {
            'main': '#2ecc71',
            'master': '#27ae60',
            'develop': '#3498db',
            'development': '#2980b9',
            'staging': '#f39c12',
            'production': '#e74c3c',
            'unknown': '#95a5a6'
        }

        colors = [branch_colors_map.get(label, self.colors[i % len(
            self.colors)]) for i, label in enumerate(labels)]

        # Create donut chart
        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=labels,
            colors=colors,
            autopct='%1.1f%%',
            startangle=90,
            pctdistance=0.85,
            wedgeprops=dict(width=0.5, edgecolor='white', linewidth=2)
        )

        # Enhance text
        for text in texts:
            text.set_fontsize(10)
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontsize(9)
            autotext.set_fontweight('bold')

        ax.set_title('Commit Distribution by Branch',
                     fontsize=13, fontweight='bold', pad=20)

    def _add_branch_summary_table(self, ax, all_data: Dict[str, Dict[str, Dict]]):
        """Add branch summary table to matplotlib axis

        Args:
            ax: Matplotlib axis
            all_data: Dictionary mapping usernames to date-indexed metrics
        """
        # Aggregate statistics by branch
        branch_stats = {}

        for username, date_data in all_data.items():
            for date, metrics in date_data.items():
                branch_breakdown = metrics.get('branch_breakdown', {})
                for repo, repo_branches in branch_breakdown.items():
                    for branch, branch_metrics in repo_branches.items():
                        if branch not in branch_stats:
                            branch_stats[branch] = {
                                'commits': 0,
                                'additions': 0,
                                'deletions': 0,
                                'contributors': set()
                            }
                        branch_stats[branch]['commits'] += branch_metrics.get(
                            'commit_count', 0)
                        branch_stats[branch]['additions'] += branch_metrics.get(
                            'additions', 0)
                        branch_stats[branch]['deletions'] += branch_metrics.get(
                            'deletions', 0)
                        branch_stats[branch]['contributors'].add(username)

        if not branch_stats:
            ax.text(0.5, 0.5, 'No branch data available',
                    ha='center', va='center', fontsize=12, color='gray')
            ax.set_title('Top Branches Summary',
                         fontsize=13, fontweight='bold')
            ax.axis('off')
            return

        # Sort by commit count and take top 10
        sorted_branches = sorted(
            branch_stats.items(),
            key=lambda x: x[1]['commits'],
            reverse=True
        )[:10]

        # Prepare table data
        table_data = []
        for branch, stats in sorted_branches:
            table_data.append([
                branch[:20],  # Truncate long branch names
                str(stats['commits']),
                str(len(stats['contributors'])),
                f"+{stats['additions']}",
                f"-{stats['deletions']}"
            ])

        # Create table
        ax.axis('off')
        table = ax.table(
            cellText=table_data,
            colLabels=['Branch', 'Commits', 'Users', 'Additions', 'Deletions'],
            cellLoc='left',
            colLoc='left',
            loc='center',
            colWidths=[0.25, 0.15, 0.15, 0.20, 0.20]
        )

        # Style table
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1, 2)

        # Header styling
        for i in range(5):
            cell = table[(0, i)]
            cell.set_facecolor('#4a90e2')
            cell.set_text_props(weight='bold', color='white')

        # Alternate row colors
        for i in range(1, len(table_data) + 1):
            for j in range(5):
                cell = table[(i, j)]
                if i % 2 == 0:
                    cell.set_facecolor('#f0f0f0')
                else:
                    cell.set_facecolor('white')

        ax.set_title('Top Branches Summary', fontsize=13,
                     fontweight='bold', pad=10)

    def generate_all_charts(self, all_data: Dict[str, Dict[str, Dict]],
                            start_date: str, end_date: str) -> Dict[str, str]:
        """Generate both Plotly and Matplotlib charts

        Args:
            all_data: Dictionary mapping usernames to date-indexed metrics
            start_date: Start date string
            end_date: End date string

        Returns:
            Dictionary with paths to all generated files
        """
        logger.info("Starting chart generation")

        # Generate Plotly HTML
        logger.info("Creating interactive HTML chart...")
        html_path = self.generate_plotly_chart(all_data, start_date, end_date)

        # Generate Matplotlib PNG and PDF
        logger.info("Creating static PNG and PDF charts...")
        static_paths = self.generate_matplotlib_charts(
            all_data, start_date, end_date)

        results = {
            'html': html_path,
            'png': static_paths['png'],
            'pdf': static_paths['pdf']
        }

        logger.info("Charts generated successfully:")
        logger.info(f"  Interactive HTML: {html_path}")
        logger.info(f"  Static PNG:       {static_paths['png']}")
        logger.info(f"  Static PDF:       {static_paths['pdf']}")

        return results
