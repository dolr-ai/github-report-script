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
3. Posts a ranked **leaderboard** to a Google Chat space (production or test channel).

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
│   ├── leaderboard_generator.py# Rank contributors; daily/weekly logic
│   └── google_chat_poster.py   # Format & post messages to Google Chat
├── tests/                      # pytest test suite
├── cache/commits/              # Raw daily commit+issue JSON (gitignored runtime data)
├── ansible/                    # Ansible playbook for .env generation
│   ├── vars/main.yml           # Plaintext vars referencing vault secrets
│   ├── vars/vault.yml          # Ansible-vault-encrypted secrets (never commit plaintext)
│   └── templates/env.j2        # .env template
├── documentation/              # All supplementary markdown docs
│   ├── ARCHITECTURE.md         # Sequence diagrams and data-flow details
│   ├── CI_SETUP.md             # GitHub Actions setup guide
│   ├── ISSUES_TRACKING_IMPLEMENTATION.md
│   └── LEADERBOARD_SETUP.md
├── AGENTS.md                   # ← this file
├── README.md
└── requirements.txt
```

---

## 3. Architecture & Data Flow

```
GitHub GraphQL API ──► github_fetcher.py ─► cache/commits/YYYY-MM-DD.json
  (repo discovery)      (two-step)                      │
  (branch history)                                cache_manager.py
                                                          │
                                             leaderboard_generator.py
                                                          │
                                             google_chat_poster.py ─► Google Chat
```

All commit data is fetched via pure GraphQL (no REST search API). Issue data is also pure GraphQL.

---

## 4. Key Design Decisions

### 4.1 Commit Discovery: Two-Step Pure-GraphQL Approach

**Decision:** Commit discovery uses a two-step pure-GraphQL strategy that reads git history directly, with no dependency on GitHub's search index.

**Step 1 — `_discover_active_repos()`:** A single GraphQL call fetches all org repos ordered by `pushedAt DESC`, stopping as soon as repos become older than the look-behind window (start − 1 day). Returns a list of `"owner/repo"` strings. **Any repo whose `pushedAt` ≥ lookback is included — including repos pushed after the window end (e.g. today).** A repo pushed today for a yesterday window still has yesterday's commits in its branch history; `history(since:, until:)` in Step 2 enforces the actual date boundary. Using `pushedAt` as an upper-bound filter was a bug that caused commits to be silently dropped whenever a new push happened after midnight.

**Step 2 — `_fetch_commits_via_graphql()`:** For each active repo, fetches all branches (`refs(refPrefix: "refs/heads/", orderBy: TAG_COMMIT_DATE DESC)`) and for each branch, uses `history(since:, until:)` — a real git filter backed by the repo's commit graph, not GitHub's search index. `additions` and `deletions` are inline on each `Commit` node, so **no follow-up REST calls are needed**. Repos are batched 5-per-GraphQL-query via aliases to minimise round-trips.

**Why not REST `GET /search/commits`:** GitHub's search API has eventual-consistency indexing. A commit pushed to a feature branch was confirmed invisible for 17+ hours after push (affecting gravityvi's `746cc8bbb5` in `yral-billing/feat/setup-pooling-and-wal-mode-for-db`). The `history()` query found the same commit immediately.

**Why not GraphQL `search(type: COMMIT)`:** GitHub's public GraphQL API does not support `COMMIT` as a `SearchType`. The valid enum values are `ISSUE`, `ISSUE_ADVANCED`, `REPOSITORY`, `USER`, and `DISCUSSION`.

**Why not Events API:** Hard-caps at 300 events per user. High-volume contributors disappear entirely when their push volume exceeds the cap.

**Why not `contributionsCollection`:** Only counts contributions that landed on the default branch. Misses feature-branch-only pushes.

**`branches` field:** Now populated with actual branch name(s) where the commit was found. A commit present on multiple branches is stored once with all branch names listed.

**Rate limit cost:** ~3 GraphQL points per daily run (1 for repo discovery, ~2 for branch scans across 7 active repos), down from ~25–45 REST calls previously.

**Author filtering:** Client-side only — all commits in the date window are fetched and filtered by `author.user.login ∈ user_ids`. No per-user query is issued.

### 4.2 Commit Deduplication

Commits are deduplicated **by SHA within a single fetch run** (`commits_by_sha` dict). The same SHA on multiple branches is stored once with a `branches: [...]` list. Do not add cross-date or cross-run deduplication — the cache is the source of truth per day.

### 4.3 Leaderboard Ranking

Contributors are ranked by a **weighted normalized score**:

```
score = w_issues × norm(issues_closed)
      + w_commits × norm(commit_count)
      + w_additions × norm(total_additions)
      + w_deletions × norm(total_deletions)
```

Each metric is **min-max normalized** to [0, 1] across all contributors for the period:
```
norm(x_i) = (x_i − min(x)) / (max(x) − min(x))
```
If all contributors share the same value for a metric (`max == min`), that metric contributes 0 to everyone's score for that period — it provides no differentiating signal.

Default weights (configured in `config.py → LEADERBOARD_WEIGHTS`):
| Metric | Weight |
|---|---|
| `issues_closed` | 3 |
| `commits` | 3 |
| `additions` | 2 |
| `deletions` | 2 |

Max possible score = sum of all weights (10 with defaults).

Ties (equal scores) share the same rank emoji position. This is implemented in `leaderboard_generator.py → compute_weighted_scores()` and `get_all_contributors_by_impact()`.

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

All GraphQL calls retry up to 10 times with smart wait: the exact reset timestamp is read from `/rate_limit` and used as the sleep duration (+ 2 s buffer). Exponential backoff is used only if the rate-limit check itself fails.

`_check_rate_limit_and_wait(min_remaining, resource_type)` accepts `resource_type='graphql'` or `'core'`. Since commit discovery is now pure GraphQL, only the `graphql` bucket is used during normal operation.

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
| `LEADERBOARD_WEIGHTS` | `Dict[str, int]` | Weights for weighted scoring: keys `issues_closed`, `commits`, `additions`, `deletions` |

When adding a new config variable:
1. Add it to `config.py` with a docstring.
2. If it is a secret, load it via `os.getenv(...)` and add the key to `ansible/templates/env.j2`, `ansible/vars/main.yml.example`, and `ansible/vars/vault.yml.example`.
3. Update `validate_config()` if the variable is required at startup.

---

## 6. Execution Modes & CLI

### Modes (`ExecutionMode` enum)

| Mode | Description |
|------|-------------|
| `FETCH` | Fetch + cache raw data only |
| `REFRESH` | Force re-fetch for date range, overwrite cache |
| `STATUS` | Show cache status and rate limits |
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
- `_discover_active_repos(start_datetime, end_datetime) → List[str]` — one GraphQL call; fetches org repos ordered by `pushedAt DESC`; returns `["owner/repo", ...]` for repos pushed in window (with 1-day look-behind buffer). Stops early once repos are older than the buffer.
- `_fetch_commits_via_graphql(repo_names, start_datetime, end_datetime, user_ids) → List[Dict]` — batched GraphQL queries (5 repos per query via aliases). For each repo, fetches all branches (`refs`) ordered by most-recently committed first, then uses `history(since:, until:)` per branch to retrieve commits. `additions`/`deletions` are inline — no REST follow-up. Deduplicates by SHA; same commit on multiple branches accumulates branch names. Filters bots and non-tracked authors client-side.
- `_fetch_commits_for_date(date_str, start_datetime, end_datetime, user_ids)` — calls `_discover_active_repos` then `_fetch_commits_via_graphql`, then calls `_fetch_closed_issues_for_user` for each user.
- `_check_rate_limit_and_wait(min_remaining, resource_type)` — accepts `resource_type` param (`'graphql'` or `'core'`); during normal commit fetching only `graphql` is used.
- `_fetch_closed_issues_for_user()` — GraphQL; filters by assignee + closed date + org.

### `cache_manager.py`

- Reads/writes `cache/commits/YYYY-MM-DD.json`.
- Schema: `{date, commits: [{sha, author, repository, timestamp, message, stats, branches}], issues: [{...}], issue_count}`.
- `validate_cache_structure()` checks for the `branches` field; returns False (triggering re-fetch) if missing.

### `leaderboard_generator.py`

- `get_yesterday_ist()` / `get_last_7_days_ist()` — always uses IST.
- `should_post_weekly()` — True if today (IST) is Monday.
- `generate_daily_leaderboard()` / `generate_weekly_leaderboard()` — return `(contributors_by_impact, date_string)`.
- `aggregate_metrics(date_strings)` — returns per-user dict with keys `issues_closed`, `commit_count`, `total_loc`, `total_additions`, `total_deletions`.
- `compute_weighted_scores(user_metrics)` — min-max normalizes each metric across the cohort, applies weights from `LEADERBOARD_WEIGHTS`, returns `{username: float_score}`.
- `get_all_contributors_by_impact(user_metrics)` — calls `compute_weighted_scores`, attaches `score` key to each metrics dict, sorts descending by score.
- `get_commits_breakdown()` / `get_issues_breakdown()` — detail data for the second message.
- Reads directly from raw cache via `CacheManager.read_cache()` — does not use any intermediate processed output.

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
- **Mode:** `FETCH_AND_LEADERBOARD` (fetches data and posts to production Google Chat in one run)
- **Secret:** `ANSIBLE_VAULT_PASSWORD` — used to decrypt vault and generate `.env` at runtime.
- Only `cache/` is committed back to the repo after each run; there are no generated HTML reports or GitHub Pages deployment.

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
