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
        dates, usernames, additions_data, deletions_data, total_loc_data, commits_data = \
            self._prepare_data(all_data)

        logger.info(
            f"Generating Plotly chart for {len(usernames)} users, {len(dates)} dates")

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

        # Update layout
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

        # Save to file
        filename = self._get_filename_base(start_date, end_date) + '.html'
        filepath = os.path.join(REPORTS_DIR, filename)
        fig.write_html(filepath)

        return filepath

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
        fig, axes = plt.subplots(2, 2, figsize=(18, 12))
        fig.suptitle(f'GitHub Activity Report ({start_date} to {end_date})',
                     fontsize=18, fontweight='bold')

        # Prepare x positions for grouped bars
        x = np.arange(len(dates))
        width = 0.8 / len(usernames) if len(usernames) > 0 else 0.8

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
            ax.legend(loc='upper left', framealpha=0.9)
            ax.grid(True, alpha=0.3, linestyle='--')
            ax.set_axisbelow(True)

        # Plot all four metrics
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
