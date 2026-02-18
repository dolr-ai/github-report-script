# AGENTS.md — Codebase Guide for AI Agents

This file is the canonical reference for any AI agent (GitHub Copilot, Claude, etc.) making changes to this repository. **Update this file whenever a broad architectural decision, new module, new CLI flag, new configuration variable, or significant behavioural change is introduced.**

---

## Table of Contents

1. [Purpose of This Repo](#1-purpose-of-this-repo)
2. [Repository Layout](#2-repository-layout)
3. [Architecture & Data Flow](#3-architecture--data-flow)
4. [Key Design Decisions](#4-key-design-decisions)
5. [Configuration System](#5-configuration-system)
6. [Execution Modes & CLI](#6-execution-modes--cli)
7. [Module Responsibilities](#7-module-responsibilities)
8. [Credentials & Secrets](#8-credentials--secrets)
9. [Testing Conventions](#9-testing-conventions)
10. [CI/CD](#10-cicd)
11. [Changelog of Broad Changes](#11-changelog-of-broad-changes)

---

## 1. Purpose of This Repo

Nightly script that:

1. Fetches commit and issue activity across **all branches** of all repos in the `dolr-ai` GitHub org for a configured set of contributors.
2. Caches raw data locally as JSON (`cache/commits/YYYY-MM-DD.json`).
3. Processes it into per-user daily summaries (`output/{username}/YYYY-MM-DD.json`).
4. Generates interactive HTML and static PNG/PDF charts (`docs/`).
5. Posts a ranked **leaderboard** to a Google Chat space (production or test channel).

The leaderboard ranks contributors by: **issues closed → commits → lines of code (descending)**.

---

## 2. Repository Layout

```
/
├── src/                        # All application code
│   ├── config.py               # Single source of truth for all settings
│   ├── main.py                 # Entry point; CLI arg parsing; mode dispatch
│   ├── github_fetcher.py       # GitHub API calls (GraphQL + REST Events API)
│   ├── cache_manager.py        # Read/write JSON cache files
│   ├── data_processor.py       # Aggregate raw cache → per-user output
│   ├── chart_generator.py      # Plotly HTML + Matplotlib PNG/PDF reports
│   ├── leaderboard_generator.py# Rank contributors; daily/weekly logic
│   └── google_chat_poster.py   # Format & post messages to Google Chat
├── tests/                      # pytest test suite
├── cache/commits/              # Raw daily commit+issue JSON (gitignored runtime data)
├── output/{username}/          # Processed per-user daily summaries
├── docs/                       # Generated HTML reports (served via GitHub Pages)
├── ansible/                    # Ansible playbook for .env generation
│   ├── vars/main.yml           # Plaintext vars referencing vault secrets
│   ├── vars/vault.yml          # Ansible-vault-encrypted secrets (never commit plaintext)
│   └── templates/env.j2        # .env template
├── documentation/              # All supplementary markdown docs
│   ├── ARCHITECTURE.md         # Sequence diagrams and data-flow details
│   ├── CI_SETUP.md             # GitHub Actions setup guide
│   ├── IMPLEMENTATION_SUMMARY.md  # Branch visualisation feature notes
│   ├── ISSUES_TRACKING_IMPLEMENTATION.md
│   └── LEADERBOARD_SETUP.md
├── AGENTS.md                   # ← this file
├── README.md
└── requirements.txt
```

---

## 3. Architecture & Data Flow

```
GitHub GraphQL API  ──┐
GitHub Events API   ──┤─► github_fetcher.py ─► cache/commits/YYYY-MM-DD.json
                      │                             │
                      │                     cache_manager.py
                      │                             │
                      └────────────────────► data_processor.py ─► output/{user}/YYYY-MM-DD.json
                                                                        │
                                                               chart_generator.py ─► docs/
                                                                        │
                                                           leaderboard_generator.py
                                                                        │
                                                           google_chat_poster.py ─► Google Chat
```

---

## 4. Key Design Decisions

### 4.1 Commit Discovery: Two-Source Repo Detection

**Problem solved (Feb 2026):** GitHub's `contributionsCollection` GraphQL API only counts commits that land on the *default branch*. Commits on unmerged feature branches (open PRs) were silently missed.

**Solution in `github_fetcher.py`:**

`_get_user_active_repos()` now merges two sources:

| Source | API | What it catches |
|--------|-----|-----------------|
| `contributionsCollection` | GraphQL | Merged/default-branch commits |
| `_get_user_active_repos_from_events()` | REST `/users/{login}/events` | `PushEvent`s on *any* branch |

The union of both sets is used as the repo list to search. Events are paginated up to 10 pages (300 events) and are stopped early once event timestamps fall before the query window.

**Implication:** Any future change to repo-discovery logic must preserve both sources.

### 4.2 Commit Deduplication

Commits are deduplicated **by SHA within a single fetch run** (`commits_by_sha` dict). The same SHA on multiple branches is stored once with a `branches: [...]` list. Do not add cross-date or cross-run deduplication — the cache is the source of truth per day.

### 4.3 Leaderboard Ranking

Three-level sort (all descending): `(issues_closed, commit_count, total_loc)`. Ties share the same rank emoji position. This is implemented in `leaderboard_generator.py → get_all_contributors_by_impact()`.

### 4.4 Timezone

All date boundary calculations (yesterday, last 7 days, etc.) use **IST (`Asia/Kolkata`)**, not UTC. This is intentional — the team is India-based. The `IST_TIMEZONE` constant is defined in `config.py` and must be used everywhere date arithmetic is done for leaderboard/reporting purposes.

### 4.5 Cache Invalidation

Cache files for a date are only overwritten in two cases:
- `force_refresh=True` (REFRESH mode or `--days` flag)
- The cache file is structurally outdated (missing `branches` field — checked in `cache_manager.py → validate_cache_structure()`)

Do **not** silently overwrite cache unless one of these conditions is true.

### 4.6 Google Chat: Two Channels

There are two configured Google Chat channels:

| Channel | Config vars | When used |
|---------|-------------|-----------|
| Production | `GOOGLE_CHAT_WEBHOOK_BASE_URL`, `GOOGLE_CHAT_KEY`, `GOOGLE_CHAT_TOKEN` | Default (no flags) |
| Test | `GOOGLE_CHAT_TEST_WEBHOOK_BASE_URL`, `GOOGLE_CHAT_TEST_KEY`, `GOOGLE_CHAT_TEST_TOKEN` | `--test-channel` flag |

The test channel space ID is stored in `config.py`. Keys/tokens come from `.env` via `GOOGLE_CHAT_TEST_KEY` / `GOOGLE_CHAT_TEST_TOKEN`.

`GoogleChatPoster(dry_run=True)` prints messages to stdout and never hits the network — safe for local previews. `GoogleChatPoster(test_channel=True)` routes to the test webhook. Both flags can be combined.

### 4.7 Bot Filtering

Bots are filtered by matching `author.name` or `author.email` against `KNOWN_BOTS` in `config.py`. The list is the fallback; GitHub's own user-type field is the primary check where available.

### 4.8 Rate Limit Handling

All GraphQL and REST calls retry up to 10 times with smart wait: the exact reset timestamp is read from `/rate_limit` and used as the sleep duration (+ 2 s buffer). Exponential backoff is used only if the rate-limit check itself fails.

---

## 5. Configuration System

**All configuration lives in `src/config.py`.** There are no other config files. Environment variables (loaded from `.env` via `python-dotenv`) are used only for secrets.

### Variables an agent is likely to need

| Variable | Type | Description |
|----------|------|-------------|
| `MODE` | `ExecutionMode` enum | Default execution mode |
| `DATE_RANGE_MODE` | `DateRangeMode` enum | How the date window is determined |
| `DAYS_BACK` | `int` | Number of days for `LAST_N_DAYS` mode |
| `USER_IDS` | `List[str]` | GitHub usernames to track |
| `GITHUB_ORG` | `str` | Organisation (default: `dolr-ai`) |
| `THREAD_COUNT` | `int` | Concurrent API threads (keep ≤ 4 to avoid rate limits) |
| `GOOGLE_CHAT_WEBHOOK_BASE_URL` | `str` | Production channel space URL (hardcoded) |
| `GOOGLE_CHAT_TEST_WEBHOOK_BASE_URL` | `str` | Test channel space URL (hardcoded) |
| `IST_TIMEZONE` | `pytz.timezone` | Use this for all date arithmetic |

When adding a new config variable:
1. Add it to `config.py` with a docstring.
2. If it is a secret, load it via `os.getenv(...)` and add the key to `ansible/templates/env.j2`, `ansible/vars/main.yml.example`, and `ansible/vars/vault.yml.example`.
3. Update `validate_config()` if the variable is required at startup.

---

## 6. Execution Modes & CLI

### Modes (`ExecutionMode` enum)

| Mode | Description |
|------|-------------|
| `FETCH` | Fetch + cache + process only |
| `REFRESH` | Force re-fetch for date range, overwrite cache |
| `CHART` | Generate charts from existing processed data |
| `STATUS` | Show cache status and rate limits |
| `FETCH_AND_CHART` | FETCH then CHART |
| `LEADERBOARD` | Generate + post leaderboard to Google Chat |
| `FETCH_AND_LEADERBOARD` | FETCH then LEADERBOARD |

### CLI flags (parsed in `main.py → parse_args()`)

| Flag | Description |
|------|-------------|
| `--mode <mode>` | Override `MODE` from config |
| `--days <n>` | Override `DAYS_BACK` |
| `--dry-run` | Print leaderboard messages to stdout instead of sending |
| `--test-channel` | Post to the test Google Chat channel |

`--dry-run` and `--test-channel` are only meaningful for `leaderboard` and `fetch_and_leaderboard` modes.

---

## 7. Module Responsibilities

### `github_fetcher.py`

- Single public method: `fetch_commits(start_date, end_date, user_ids, force_refresh)` — returns raw dict and writes cache.
- `_get_user_active_repos()` — merges contributionsCollection + Events API.
- `_get_user_active_repos_from_events()` — REST Events API, paginates up to 10 pages, stops early when past the time window.
- `_fetch_commits_for_date()` — inner loop: repo → branch → commit; deduplicates by SHA.
- `_fetch_closed_issues_for_user()` — GraphQL; filters by assignee + closed date + org.

### `cache_manager.py`

- Reads/writes `cache/commits/YYYY-MM-DD.json`.
- Schema: `{date, commits: [{sha, author, repository, timestamp, message, stats, branches}], issues: [{...}], issue_count}`.
- `validate_cache_structure()` checks for the `branches` field; returns False (triggering re-fetch) if missing.

### `data_processor.py`

- Reads cache, writes `output/{username}/YYYY-MM-DD.json`.
- Output schema includes `branch_breakdown: {repo: {branch: {additions, deletions, total_loc, commit_count}}}`.
- No deduplication at this stage — cache is already deduplicated.

### `leaderboard_generator.py`

- `get_yesterday_ist()` / `get_last_7_days_ist()` — always uses IST.
- `should_post_weekly()` — True if today (IST) is Monday.
- `generate_daily_leaderboard()` / `generate_weekly_leaderboard()` — return `(contributors_by_impact, date_string)`.
- `get_commits_breakdown()` / `get_issues_breakdown()` — detail data for the second message.

### `google_chat_poster.py`

- `GoogleChatPoster(dry_run, test_channel)` — constructor selects channel and mode.
- `post_leaderboard(...)` — formats + posts summary message.
- `post_commits_breakdown(...)` — formats + posts detailed message (issues first, then commits).
- Two messages are always posted: summary + breakdown.

---

## 8. Credentials & Secrets

Secrets are managed via **Ansible Vault** (`ansible/vars/vault.yml`). The playbook `ansible/setup_env.yml` decrypts the vault and writes `.env` to the project root.

`.env` keys in use:

```
GITHUB_TOKEN
GOOGLE_CHAT_KEY
GOOGLE_CHAT_TOKEN
GOOGLE_CHAT_TEST_KEY
GOOGLE_CHAT_TEST_TOKEN
```

**Never hardcode secret values in source files.** The `WEBHOOK_BASE_URL` values (which contain public space IDs) are hardcoded in `config.py` — that is intentional and acceptable.

---

## 9. Testing Conventions

- Tests live in `tests/`. Run with `pytest`.
- Markers: `@pytest.mark.unit` (mock-only, fast) and `@pytest.mark.integration` (real API, skipped if no token).
- Unit tests mock `_graphql_request` and `requests.get` directly.
- `conftest.py` provides fixtures: `temp_cache_dir`, `github_client`, `dolr_ai_org`, `sample_date_range`.
- When adding a new module method, add corresponding unit tests in the matching `tests/test_*.py` file.
- When adding a new source of repo/commit discovery, add tests covering: happy path, empty result, error handling, deduplication.

Run unit tests only (fast, no API calls):
```bash
pytest -m unit
```

---

## 10. CI/CD

- **Workflow:** `.github/workflows/nightly-report.yml`
- **Schedule:** 12:00 AM IST daily (06:30 UTC cron)
- **Mode:** `FETCH_AND_LEADERBOARD` (fetches data and posts to production Google Chat)
- **Secret:** `ANSIBLE_VAULT_PASSWORD` — used to decrypt vault and generate `.env` at runtime.
- Reports are published to GitHub Pages from the `docs/` directory.
- Weekly releases are created every Sunday with aggregated reports.

See `documentation/CI_SETUP.md` for full setup instructions.

---

## 11. Instructions for AI Agents

**If you are an AI agent making changes to this repository, you are required to update this file as part of your work.**

This file is the shared memory between all agents that will ever work on this repo. When you make a broad change — a new module, a new CLI flag, a new config variable, a changed behaviour, a fixed architectural flaw — future agents will read this file first. If your change is not reflected here, the next agent will not know about it and may work against your decisions.

### What to update and when

After completing any of the following, edit the relevant section(s) of this file **in the same session**:

| Type of change | What to update in this file |
|---|---|
| New module added | Add entry to §2 layout and §7 module responsibilities |
| New CLI flag | Update §6 CLI flags table |
| New config variable | Update §5 variables table; note if it is a secret |
| Architectural decision or tradeoff | Add a subsection in §4 |
| Changed behaviour in an existing module | Update §7 for that module |
| New secret / credential | Update §8 |
| New test convention | Update §9 |
| CI/CD change | Update §10 |

### What not to do

- Do **not** create a separate markdown file to document your change. Put it here instead.
- Do **not** leave this file in a state that describes a previous version of the codebase.
- Do **not** add a running changelog or timestamped entries. Keep each section a clean, up-to-date description of the **current** state. If something is no longer true, remove or replace it.

The goal is that any agent starting a new session can read this file and have an accurate model of the codebase without reading source files first.
