# `nba_fantasy_logs.db` — Consumer Reference

**Audience:** an agent/session building **`nba-dfs-stats-lab`** (a separate SQLite
database ingesting historical NBA DFS projections and lineups) that will read
`nba_fantasy_logs.db` via a **read-only URI `ATTACH`**.

**Source of truth:** this document is derived from the `bigdataball-data` pipeline
source at commit `aa76cd5` (2026-07-25). The database file itself is **not committed**
to any repo (git-ignored, ~36 MB, lives on the maintainer's machine), so every schema
statement here is derived from the code that writes it, not from an inspection of the
live file. **Run the verification queries in §2 before writing any DDL against it.**

**Golden rule:** `nba_fantasy_logs.db` is owned by the `bigdataball-data` pipeline.
`nba-dfs-stats-lab` is a **read-only consumer**. Never write to it, never create
objects in it, never depend on being able to lock it.

---

## 1. What changed recently (read this first)

If your specs or scaffolding for `nba-dfs-stats-lab` were written before late July
2026, these are the changes most likely to have invalidated them. Each is described
in full below.

| # | Change | Plan | Why it breaks older specs |
|---|--------|------|---------------------------|
| 1 | `fantasy_logs.PLAYER_ID` and `fantasy_logs.GAME_ID` migrated **REAL → INTEGER** | 014 | Older code/specs that joined on these as floats, or that cast/`ROUND()`ed them, or that keyed on the string `"12345.0"`, are now wrong. All three log tables now agree on INTEGER IDs. |
| 2 | New table **`player_absences`** (DNP/DND/NWT rows) | 013 | "Missing game" can now be read directly instead of inferred from absent box scores. A player-game is now representable in *two* tables. |
| 3 | **UNIQUE index `idx_<table>_player_date` on `("PLAYER_ID","DATE")`** on all three log tables | 012 | `(PLAYER_ID, DATE)` is now a *guaranteed* unique key on `player_logs`, `fantasy_logs`, and `player_absences`. Older specs that deduped defensively, or that assumed `(PLAYER_ID, GAME_ID)` was the key, can be simplified — and any spec that assumed duplicates might exist is stale. |
| 4 | `player_absences` columns renamed `GAME_DATE`→`DATE`, `PLAYER_NAME`→`PLAYER` | 013 post-merge | If your scaffolding was written against the first version of that table, the column names are wrong. |
| 5 | `map_teams` is now created/populated by `seed_map_teams.py` | 008 | It exists reliably now, with a documented raw-name format ("Golden State", "LA Clippers" — city-only, no nickname). |
| 6 | Season filters centralized in `seasons.py`; source layout moved to `src/bigdataball/` | 007, 009 | If you planned to import anything from the pipeline repo, imports are now `from bigdataball.<mod> import ...` and require `pip install -e .` or `PYTHONPATH=src`. |

**The single most important consequence:** `PLAYER_ID` is an **INTEGER** everywhere —
`fantasy_logs`, `player_logs`, `player_absences`, `dim_players`, `fantasy_averages`.
Join on it directly. `GAME_ID` is INTEGER and **unpadded** (e.g. `22500001`); do not
zero-pad, do not treat it as TEXT.

---

## 2. Verify before you build

You cannot see the live DB from a cloud session, and neither could the session that
wrote this. Run these on the maintainer's machine and reconcile before committing to a
schema in `nba-dfs-stats-lab`.

```sql
-- 0. What actually exists
SELECT type, name FROM sqlite_master WHERE type IN ('table','view','index') ORDER BY type, name;

-- 1. Column names + declared types, per table
PRAGMA table_info(fantasy_logs);
PRAGMA table_info(player_logs);
PRAGMA table_info(player_absences);
PRAGMA table_info(dim_players);
PRAGMA table_info(fantasy_averages);
PRAGMA table_info(map_teams);

-- 2. Actual storage classes of the ID columns (declared type != stored type in SQLite)
SELECT DISTINCT typeof(PLAYER_ID), typeof(GAME_ID) FROM fantasy_logs;
SELECT DISTINCT typeof(PLAYER_ID), typeof(GAME_ID) FROM player_logs;
SELECT DISTINCT typeof(PLAYER_ID), typeof(GAME_ID) FROM player_absences;
-- Expect 'integer' everywhere. Any 'real' means plan 014 has not been applied
-- to this copy of the DB -> run: python -m bigdataball.patch_fantasy_id_types

-- 3. The UNIQUE indexes (plan 012)
PRAGMA index_list(fantasy_logs);
PRAGMA index_list(player_logs);
PRAGMA index_list(player_absences);
-- Expect idx_<table>_player_date with unique=1 on each.
-- Missing on an offseason DB -> run: python -m bigdataball.create_log_indexes

-- 4. Date format + range per table
SELECT MIN(DATE), MAX(DATE), COUNT(*) FROM fantasy_logs;
SELECT MIN(DATE), MAX(DATE), COUNT(*) FROM player_logs;
SELECT MIN(DATE), MAX(DATE), COUNT(*) FROM player_absences;

-- 5. Season coverage (drives what your projections can be joined against)
SELECT SEASON_SEGMENT, COUNT(*) FROM fantasy_logs GROUP BY 1 ORDER BY 1;
SELECT SEASON_TYPE, SEASON, COUNT(*) FROM fantasy_averages GROUP BY 1,2 ORDER BY 2,1;

-- 6. Raw team strings (confirm the map_teams join covers them all)
SELECT DISTINCT TEAM FROM fantasy_logs ORDER BY 1;
SELECT RAW_TEAM_NAME, TEAM_ABBREVIATION FROM map_teams ORDER BY 1;
SELECT DISTINCT f.TEAM FROM fantasy_logs f
LEFT JOIN map_teams m ON f.TEAM = m.RAW_TEAM_NAME
WHERE m.RAW_TEAM_NAME IS NULL;   -- expect zero rows

-- 7. Sanity: is fantasy_logs.PLAYER the raw name or the canonical one?
SELECT COUNT(*) FROM fantasy_logs f
JOIN dim_players d USING (PLAYER_ID)
WHERE f.PLAYER <> d.PLAYER_NAME;   -- non-zero is expected; see §7
```

---

## 3. Where the file lives, and how to attach it

### 3.1 Path resolution

The pipeline resolves its base data dir in `src/bigdataball/paths.py`, in this order:

1. `BIGDATABALL_DATA_DIR` environment variable (override; used by tests and custom runs)
2. `G:\My Drive\Documents\bigdataball` — if the `G:\My Drive` mount exists (the
   maintainer's Windows machine)
3. `<bigdataball-data repo root>/Data` — local fallback

The DB is always `<base>/nba_fantasy_logs.db`.

**Recommendation for `nba-dfs-stats-lab`:** do **not** re-implement this precedence.
Take the path from your own config — a `NBA_FANTASY_LOGS_DB` env var with a sensible
default — and fail loudly with the resolved path in the message if the file is absent.
Reproducing a three-way fallback in a second repo means two places to fix at the next
environment change.

### 3.2 Read-only ATTACH

```sql
ATTACH DATABASE 'file:/absolute/path/to/nba_fantasy_logs.db?mode=ro' AS bdb;
```

From Python:

```python
import sqlite3
from pathlib import Path

conn = sqlite3.connect(lab_db_path, uri=True)   # your own writable DB
src = Path(fantasy_logs_path).resolve().as_posix()
conn.execute("ATTACH DATABASE ? AS bdb", (f"file:{src}?mode=ro",))
```

Pass `uri=True` on the main connection. Whether SQLite honours a `file:` URI inside
`ATTACH` depends on the build (`SQLITE_USE_URI`) *or* on the main connection having
been opened with the URI flag — it happens to work either way on the SQLite 3.45
bundled with current CPython, but the flag is the portable guarantee. **Assert that
`mode=ro` actually took effect** rather than trusting the string: attempt a write
against `bdb` at startup and require it to raise
`sqlite3.OperationalError: attempt to write a readonly database`. A URI that was
silently treated as a literal filename would otherwise give you a writable handle to
the maintainer's production DB.

If you use SQLAlchemy for the main connection, run the `ATTACH` as raw SQL on the
DBAPI connection — and re-issue it on every new connection, since `ATTACH` is
per-connection, not per-database. With a connection pool, wire it to an event hook
(`sqlalchemy.event.listen(engine, "connect", ...)`) so pooled connections don't
silently lack the attachment.

**Caveats that will bite you:**

- **`mode=ro` is not `immutable=1`.** A read-only connection still needs to be able to
  read (and, for WAL, memory-map) the sidecar files. If the pipeline ever leaves the DB
  in WAL mode, opening it `mode=ro` from a directory you can't write to fails with
  "unable to open database file". The pipeline does not explicitly set `journal_mode`
  (SQLAlchemy/`sqlite3` default is `delete`), so this should not arise — but check for
  stray `nba_fantasy_logs.db-wal` / `-shm` files before concluding your ATTACH is
  broken. Do **not** reach for `immutable=1` as a workaround: it tells SQLite the file
  can never change, which is false for a DB rewritten daily, and produces silent
  garbage rather than an error if it is stale.
- **The pipeline rewrites tables under you.** `fantasy_averages` is dropped and
  recreated (`if_exists="replace"`) on every run, and `patch_fantasy_id_types.py` /
  `check_ingest_duplicates.py` rebuild or delete rows. Long-lived read connections
  spanning a pipeline run can see errors or a torn view. Attach, read what you need,
  detach.
- **Don't create views in your DB that reference `bdb.*`.** A view stored in
  `nba-dfs-stats-lab` referencing an attached schema only resolves when that exact
  alias is attached; it breaks for anyone opening your DB standalone. Materialize what
  you need into your own tables instead (see §9).
- **Cross-database writes.** `INSERT INTO main.x SELECT ... FROM bdb.y` is fine and is
  the intended pattern. `ATTACH` in read-only mode makes accidental writes to `bdb`
  an error rather than a corruption.

---

## 4. Object inventory

**Tables**

| Table | Grain | Rows written by |
|-------|-------|-----------------|
| `fantasy_logs` | one row per player per game (DFS feed, includes DK salary/points) | `daily_fantasy_log_upload.py` (inline loop) |
| `player_logs` | one row per player per game (box-score feed) | `daily_player_upload.py` |
| `player_absences` | one row per player per **missed** game | `absence_ingestion.py` (via `daily_player_upload.py`, or `backfill_player_absences.py`) |
| `dim_players` | one row per player | learned by all three ingest paths |
| `map_teams` | one row per raw team string | `seed_map_teams.py` |
| `fantasy_averages` | one row per (season type, player, season, team) | `create_summary_tables.py`, `if_exists="replace"` |

**Views** (all `DROP` + `CREATE` on each run)

| View | Built by | Contents |
|------|----------|----------|
| `vw_player_averages_regular_season` | `create_summary_tables.py` | `fantasy_averages WHERE SEASON_TYPE='Regular'` |
| `vw_player_averages_playoffs` | `create_summary_tables.py` | `fantasy_averages WHERE SEASON_TYPE='Playoffs'` |
| `vw_daily_slate` | `export_slate_averages_vw.py` | **today's DK slate only** |
| `vw_daily_slate_l30` | `export_slate_averages_vw.py` | **today's DK slate only**, current season, with `L30FPPM` |
| `vw_daily_slate_playoffs` | `export_playoffs_slate_averages_vw.py` | **today's DK slate only**, playoffs |

> **The three `vw_daily_slate*` views are ephemeral and slate-scoped.** Their `WHERE
> PLAYER IN (...)` list is regenerated from whatever `~/Downloads/DKEntries.csv`
> happened to contain on the last pipeline run, with player names resolved by fuzzy
> match. They are a UI surface for Excel, **not** an analysis source. Do not build
> `nba-dfs-stats-lab` on them. Use `fantasy_averages` (or the two
> `vw_player_averages_*` views) and apply your own slate filter.

**Indexes**

| Index | Table | Definition |
|-------|-------|------------|
| `idx_fantasy_logs_player_date` | `fantasy_logs` | UNIQUE (`"PLAYER_ID"`, `"DATE"`) |
| `idx_player_logs_player_date` | `player_logs` | UNIQUE (`"PLAYER_ID"`, `"DATE"`) |
| `idx_player_absences_player_date` | `player_absences` | UNIQUE (`"PLAYER_ID"`, `"DATE"`) |

Plus the implicit index on `dim_players.PLAYER_ID` (`INTEGER PRIMARY KEY` — it is a
rowid alias, so there is no separate index object). `map_teams` and `fantasy_averages`
have **no** indexes and **no** declared primary keys.

---

## 5. Table reference

### 5.1 `fantasy_logs` — DFS feed, one row per player-game

Created implicitly by `pandas.to_sql(..., if_exists="append")`, so most columns carry
whatever affinity pandas inferred (`TEXT`/`REAL`/`BIGINT`); only `PLAYER_ID` and
`GAME_ID` have an explicitly declared type.

Source: the BigDataBall DFS `.xlsx`, read with `header=1`, first data row discarded.
Headers are sanitized (`\n`→`_`, space→`_`, strip non-alphanumerics, UPPERCASE) and
then a rename map is applied.

**Columns you can rely on** (each is either explicitly renamed by the loader or read by
name downstream — i.e. its presence is enforced by code):

| Column | Type | Notes |
|--------|------|-------|
| `PLAYER_ID` | INTEGER | **Plan 014.** Cast on ingest; rows with a missing ID are dropped and counted; fractional IDs raise. |
| `GAME_ID` | INTEGER | **Plan 014.** Same treatment. Unpadded. |
| `PLAYER` | TEXT | Per-file name with `PLAYER_NAME_MAP` applied at ingest. **Not authoritative** — see §7. |
| `DATE` | TEXT | `'YYYY-MM-DD'`, normalized via `pd.to_datetime(...).strftime("%Y-%m-%d")`. |
| `SEASON_SEGMENT` | TEXT | From `BIGDATABALL_DATASET`, e.g. `"2024-25 NBA Regular Season"`. The only season marker in the log tables. |
| `TEAM` | TEXT | Raw BigDataBall team string (`"Golden State"`, `"LA Clippers"`), from `OWN_TEAM`. Join to `map_teams` for an abbreviation. |
| `OPPONENT` | TEXT | From `OPPONENT_TEAM`, same raw format. |
| `VENUE` | TEXT | From `VENUE_RHN` — `R`/`H` (and `N` for neutral). |
| `STARTED` | TEXT | From `STARTER_YN` — `'Y'`/`'N'`. Compared as a **string**, not a boolean. |
| `MINUTES` | REAL | Passthrough (the DFS feed header sanitizes straight to `MINUTES`). |
| `USAGE` | REAL | From `USAGE_RATE`, a percentage. |
| `DAYS_REST` | numeric | From `DAYS_REST__3SEASON_DEBUT_0_BACKTOBACK`: `3` = season debut, `0` = back-to-back. |
| `DK_POSITION` | TEXT | From `DRAFTKINGS` — DK's eligible position(s). |
| `DK_SALARY` | numeric | From `FOR_DRAFTKINGS_CLASSIC_CONTESTS` — **DK Classic salary**. |
| `DK_POINTS` | REAL | From `DRAFTKINGS1` — DK fantasy points **actually scored**. |

**Explicitly dropped at ingest** (do not expect them): `FANDUEL`, `YAHOO`,
`FOR_FANDUEL_FULL_ROSTER_CONTESTS`, `FOR_YAHOO_FULL_SLATE_CONTESTS`, `FANDUEL1`,
`YAHOO1`. Only DraftKings survives.

**Everything else in the feed passes through unrenamed** — box-score counting stats
(`PTS`, `FG`, `FGA`, `3P`, `3PA`, `FT`, `FTA`, `OR`/`DR`/`TOT` or their variants,
`A`, `PF`, `ST`, `TO`, `BL`), `POSITION`, and any column BigDataBall adds later.
Because these are passthrough, their exact names depend on the current feed headers —
**enumerate them with `PRAGMA table_info(fantasy_logs)` rather than trusting this
list.** Note the DFS-feed sanitizer replaces spaces but **not hyphens**, so a
hyphenated feed header would land as e.g. `GAMEID`, not `GAME_ID`; the observed live
table has `GAME_ID`, confirming the DFS feed uses spaces.

**Uniqueness:** UNIQUE (`PLAYER_ID`, `DATE`). One NBA game per player per day.

### 5.2 `player_logs` — box-score feed, one row per player-game

Same shape and grain as `fantasy_logs`, from a different feed (first sheet of the
player `.xlsx`, header on row 0). Its sanitizer **does** convert hyphens to
underscores. Rename map:

| Raw (sanitized) | Stored |
|---|---|
| `BIGDATABALL_DATASET` | `SEASON_SEGMENT` |
| `PLAYER__FULL_NAME` | `PLAYER` |
| `OWN__TEAM` | `TEAM` |
| `OPPONENT__TEAM` | `OPPONENT` |
| `VENUE_RHN` | `VENUE` |
| `STARTER_YN` | `STARTED` |
| `MIN` | `MINUTES` |
| `OR` / `DR` / `TOT` | `OREB` / `DREB` / `TREB` |
| `A` / `ST` / `TO` / `BL` | `AST` / `STL` / `TOV` / `BLK` |
| `USAGE__RATE_` | `USAGE` |
| unchanged | `GAME_ID`, `PLAYER_ID`, `POSITION`, `FG`, `FGA`, `3P`, `3PA`, `FT`, `FTA`, `PF`, `PTS`, `DAYS_REST` |

`DATE` is normalized to `'YYYY-MM-DD'` the same way. `PLAYER_ID`/`GAME_ID` are
INTEGER because the player feed delivers clean integer IDs (no explicit cast is
applied here — unlike `fantasy_logs`; see §8, gotcha 6).

**No DraftKings columns.** Salary and DK points exist **only** in `fantasy_logs`.

**Uniqueness:** UNIQUE (`PLAYER_ID`, `DATE`).

**`player_logs` vs `fantasy_logs`:** they overlap heavily (both are per player-game
with box-score stats) but are ingested independently from different files and may not
cover identical date ranges. `fantasy_logs` is the one the whole averages pipeline is
built on. **Prefer `fantasy_logs` for anything DFS.** Use `player_logs` when you need a
stat the DFS feed doesn't carry, or to cross-check.

### 5.3 `player_absences` — one row per player per missed game

New in plan 013. Parsed from the **second sheet** of the player feed, named
`DNP-DND-NWT`. Column names below are post-plan-013-rename (`patch_absence_column_names.py`
migrated the live table).

| Column | Type | Notes |
|--------|------|-------|
| `DATE` | TEXT | `'YYYY-MM-DD'`. Renamed from the feed's `GAME DATE`. |
| `GAME_ID` | INTEGER | Unpadded, matches `player_logs.GAME_ID`. |
| `TEAM` | TEXT | Raw team string. |
| `OPPONENT` | TEXT | Raw team string. |
| `PLAYER_ID` | INTEGER | |
| `PLAYER` | TEXT | Renamed from `PLAYER NAME`; `PLAYER_NAME_MAP` applied. |
| `STATUS` | TEXT | `DNP` (did not play) / `DND` (did not dress) / `NWT` (not with team). |
| `REASON` | TEXT | Raw feed string, stored unchanged. |
| `ABSENCE_TYPE` | TEXT | **Derived.** `'DNP-CD'` when `UPPER(TRIM(REASON)) = "COACH'S DECISION"`, else `'INJURY/ILLNESS/OTHER'`. |

Observed distributions in the 2025-26 feed (6,076 rows, from the plan-013 profiling —
indicative, not current): `STATUS` — DNP 5,010 / DND 989 / NWT 77. `REASON` —
COACH'S DECISION 4,903; INJURY/ILLNESS 1,059; NOT WITH TEAM 36; LEAGUE SUSPENSION 34;
REST 29; PERSONAL 10; TURN TO COMPETITION RECONDITIONING 4; TEAM SUSPENSION 1.

**Conflict policy — box score wins at ingest.** An absence row is **skipped** if
`player_logs` already has a box score for the same `(PLAYER_ID, DATE)`. (The source
feed genuinely contains a handful of rows listing a player as DNP who also has real
minutes.) Consequence: `player_absences` and `player_logs` should be disjoint on
`(PLAYER_ID, DATE)` — but only for rows ingested *after* the box score existed. If a
file's absence sheet was ingested before the corresponding box scores landed, an
overlap can survive. **Verify, and treat `player_logs` as authoritative on conflict:**

```sql
SELECT COUNT(*) FROM player_absences a
JOIN player_logs p ON a.PLAYER_ID = p.PLAYER_ID AND a.DATE = p.DATE;  -- expect 0
```

**No season attribution.** The sheet is cumulative for the whole season and spans
Regular Season / IST / Play-In / Playoffs with no season-type column. If you need
season context for an absence, derive it by joining `GAME_ID` or `DATE` to
`fantasy_logs`/`player_logs` and reading `SEASON_SEGMENT` from a teammate's row on the
same game.

**The absence sheet is cumulative and was historically discarded** — rows exist only
for files ingested since plan 013 landed, plus whatever
`backfill_player_absences.py` was run against in the archive. Check `MIN(DATE)` before
assuming full history.

### 5.4 `dim_players`

```sql
CREATE TABLE dim_players (
    "PLAYER_ID" INTEGER PRIMARY KEY,
    "PLAYER_NAME" TEXT
);
```

The **canonical player name** table, and your best join target for name-based data.
Populated on first sight of a `PLAYER_ID` by any of the three ingest paths, with
`mappings.PLAYER_NAME_MAP` applied. See §7 for the naming convention and its traps.

### 5.5 `map_teams`

```sql
CREATE TABLE map_teams (RAW_TEAM_NAME TEXT, TEAM_ABBREVIATION TEXT);
```

No PK, no index, 30 rows. `RAW_TEAM_NAME` is the raw string as it appears in
`fantasy_logs.TEAM`; `TEAM_ABBREVIATION` is the three-letter form (`GSW`, `NOP`,
`NYK`, `SAS`, `PHX`, `BKN`, `CHA`, `UTA`, `WAS`, …).

Confirmed BigDataBall raw format: **city-only or two-word city, no nickname, using
"LA" not "Los Angeles"** — `Atlanta`, `Golden State`, `LA Clippers`, `LA Lakers`,
`New Orleans`, `New York`, `Oklahoma City`, `San Antonio`, etc.

> A raw team string with no `map_teams` row yields `TEAM_ABBREVIATION = NULL` in
> `create_summary_tables.py`, and pandas' `groupby` **drops NULL group keys** — so
> those players are silently missing from `fantasy_averages`. `seed_map_teams.py`
> exits non-zero if any raw name is unmapped, but only when it is run. Query 6 in §2
> is the check.

### 5.6 `fantasy_averages` — the aggregate table

Rebuilt from scratch on every pipeline run (`if_exists="replace"`), from `fantasy_logs`
joined to `dim_players` (canonical name) and `map_teams` (abbreviation).

**Grain: one row per `(SEASON_TYPE, PLAYER_ID, PLAYER, SEASON, TEAM)`.** A player
traded mid-season has **multiple rows for the same season** — one per team. Aggregating
across them requires re-weighting by `GP`; you cannot average the averages. This is the
most common way to get subtly wrong numbers out of this table.

| Column | Type | Definition |
|--------|------|-----------|
| `SEASON_TYPE` | TEXT | `'Regular'` or `'Playoffs'` (see below) |
| `PLAYER_ID` | INTEGER | |
| `PLAYER` | TEXT | Canonical name from `dim_players` |
| `SEASON` | TEXT | `'2024-25'` for Regular, `'2026'` for Playoffs |
| `TEAM` | TEXT | Three-letter abbreviation (**not** the raw name) |
| `GP` | INTEGER | Games played = row count |
| `GS` | INTEGER | Games started = count of `STARTED = 'Y'` |
| `SALPG` | INTEGER | Mean `DK_SALARY`, rounded to 0dp |
| `FPPG` | REAL | Mean `DK_POINTS` |
| `STDV_FPPG` | REAL | Sample stdev of `DK_POINTS` |
| `MPG` | REAL | Mean `MINUTES` |
| `STDV_MPG` | REAL | Sample stdev of `MINUTES` |
| `FPPM` | REAL | `SUM(DK_POINTS) / SUM(MINUTES)` — **not** the mean of per-game FPPM |
| `STDV_FPPM` | REAL | Sample stdev of the **per-game** `DK_POINTS/MINUTES` |
| `USG` | REAL | Mean `USAGE` |
| `GSFPPG`, `STDV_GSFPPG`, `GSMPG`, `STDV_GSMPG`, `GSFPPM`, `STDV_GSFPPM` | REAL | Same metrics restricted to games where `STARTED = 'Y'` |
| `L30FPPM` | REAL | `SUM(DK_POINTS)/SUM(MINUTES)` over the last 30 days — **see the warning below** |
| `DK_POINTS_sum`, `MINUTES_sum`, `GS_DK_POINTS_sum`, `GS_MINUTES_sum`, `L30_DK_POINTS_sum`, `L30_MINUTES_sum` | REAL | Intermediate aggregation columns the rename map never renamed. They persist in the table. **These are useful to you** — the `_sum` columns are exactly what you need to re-weight a traded player's season correctly. |

**`SEASON_TYPE` classification** (from `SEASON_SEGMENT`):

- `'Regular'` ⇐ `SEASON_SEGMENT` contains `"Regular Season"` **or** `"In-Season Tournament"`
- `'Playoffs'` ⇐ contains `"Playoffs"` **or** `"Play-In"`
- anything else ⇒ row is **dropped** from `fantasy_averages` entirely

So IST games count as regular season, and Play-In games count as playoffs. `SEASON` is
the first 4-digit year found in the segment string, rendered `YYYY-YY` for Regular and
`YYYY` for Playoffs.

> **`L30FPPM` is not reproducible and not historical.** The "last 30 days" window is
> computed against `pd.Timestamp.now()` **at build time**, so the value depends on when
> the pipeline last ran, and it silently becomes `0` in the offseason (30 days with no
> games ⇒ 0/0 ⇒ filled with 0). Never treat it as a stored historical feature. If
> `nba-dfs-stats-lab` needs a trailing-30-day metric, compute it yourself from
> `fantasy_logs` relative to the **slate date**, not the build date.

> **`fillna(0)` hides "undefined".** After rounding, all NaNs become `0` — a
> single-game sample's stdev, a zero-minute player's FPPM, and a genuine zero are
> indistinguishable. Guard with `GP > 1` (for stdevs) and `MINUTES_sum > 0` (for
> rates) rather than filtering on the value.

---

## 6. Keys and the join model

```
dim_players (PLAYER_ID PK, PLAYER_NAME)
     ▲ PLAYER_ID          ▲ PLAYER_ID           ▲ PLAYER_ID
     │                     │                     │
fantasy_logs          player_logs          player_absences
(PLAYER_ID, DATE) U   (PLAYER_ID, DATE) U  (PLAYER_ID, DATE) U
     │ TEAM ──► map_teams.RAW_TEAM_NAME ──► TEAM_ABBREVIATION
     │
     └─ aggregated ─► fantasy_averages (SEASON_TYPE, PLAYER_ID, SEASON, TEAM)
                            │
                            └─ vw_player_averages_regular_season / _playoffs
                                    │
                                    └─ vw_daily_slate* (slate-scoped, ephemeral)
```

- **Player-game grain:** `(PLAYER_ID, DATE)` — unique and indexed on all three log
  tables. Use this, not `(PLAYER_ID, GAME_ID)`.
- **`GAME_ID`** identifies the *game*, so two players on the same team share it. It is
  present and INTEGER in all three log tables, but is **not** part of any uniqueness
  constraint. It is the right key for "who else played in this game".
- **Player identity:** `PLAYER_ID`. Stable, integer, and the only join key you should
  use between tables inside this DB.
- **Team:** raw string in the log tables, abbreviation in `fantasy_averages`. `map_teams`
  is the bridge. There is no team dimension table beyond it and no team ID.
- **Season:** `SEASON_SEGMENT` (free text) in the log tables; `SEASON_TYPE` + `SEASON`
  (parsed) only in `fantasy_averages`. If you need season on a log row, parse it the
  same way `create_summary_tables.py` does (§5.6) — or replicate that derivation once
  in your own repo and reuse it.

---

## 7. Player names — read this before designing any name-based join

Your projections and lineup history almost certainly key on **DraftKings display
names**, not `PLAYER_ID`. This is the highest-risk part of the integration.

1. **`dim_players.PLAYER_NAME` is the canonical name, and the convention is
   DraftKings'.** `mappings.PLAYER_NAME_MAP` maps feed/DK variants → the DK-convention
   target ("GG Jackson" → "Gregory Jackson", "P.J. Washington" → "PJ Washington",
   "A.J. Green" → "AJ Green", …). It is applied at every ingest point.
2. **`fantasy_logs.PLAYER` / `player_logs.PLAYER` are per-file snapshots, not
   canonical.** They had `PLAYER_NAME_MAP` applied *as of the day that row was
   ingested*, so a mapping added later is not reflected in older rows.
   `create_summary_tables.py` deliberately **drops** `fantasy_logs.PLAYER` and re-joins
   `dim_players.PLAYER_NAME`. **Do the same: join names from `dim_players`, never from
   the log tables.**
3. **`run_db_patch.py` retroactively rewrites names** in `dim_players`, `fantasy_logs`,
   `player_logs`, and `fantasy_averages` whenever a new mapping is added — but it is a
   manual, one-off script. So names can change between your ingest runs. **Store
   `PLAYER_ID` in `nba-dfs-stats-lab`, and treat names as a display attribute you
   re-resolve at query time.** Do not use a name as a foreign key.
4. **`PLAYER_NAME_MAP` lives in the pipeline repo, not in the DB.** If
   `nba-dfs-stats-lab` needs it, either vendor a copy (and accept drift) or read it via
   `from bigdataball.mappings import PLAYER_NAME_MAP` after `pip install -e` on the
   pipeline repo. A stale vendored copy is a silent-mismatch generator; prefer the
   import, or at minimum add a test that diffs the two.
5. **The pipeline's own DK→DB matching is fuzzy** (`thefuzz.process.extractOne`,
   accept at **score ≥ 90**, after an exact `PLAYER_NAME_MAP` pass). Unmatched names
   are appended to `todo_mappings.txt` and emailed. If you reuse this approach for
   historical projections, be aware a ≥90 threshold does make wrong matches on similar
   names (Jr./Sr., brothers, common surnames) — **record the matched-to `PLAYER_ID`,
   the score, and the original string** in your DB so a bad match is auditable and
   fixable rather than baked in.

**Recommended resolution order for a historical projection name:**
exact match on `dim_players.PLAYER_NAME` → `PLAYER_NAME_MAP` then exact → fuzzy with a
recorded score → unresolved queue for manual mapping. Never silently drop an
unresolved name.

---

## 8. Gotchas that will cost you a day

1. **`vw_daily_slate*` are not analysis views.** They reflect one day's DKEntries.csv.
   (§4)
2. **A traded player has multiple `fantasy_averages` rows per season.** Re-weight by
   `GP`, or use the `_sum` columns. (§5.6)
3. **`L30FPPM` depends on the pipeline's run date, not the slate date.** (§5.6)
4. **`fillna(0)` erases the difference between zero and undefined.** (§5.6)
5. **`STARTED` is the string `'Y'`/`'N'`,** not 0/1 or a boolean. Same for `VENUE`
   (`'R'`/`'H'`/`'N'`).
6. **`player_logs` does not have `fantasy_logs`' plan-014 ID hardening.**
   `fantasy_logs` explicitly casts incoming IDs to int and declares `Integer()` on
   insert; `player_logs` relies on pandas inferring int64 from a clean feed. It is
   believed correct today, and the pipeline repo records it as a known,
   investigate-only asymmetry — but it means `player_logs.PLAYER_ID` has no *declared*
   integer type. Confirm with query 2 in §2 and consider `CAST(... AS INTEGER)` on that
   side of any cross-table join if the check surprises you.
7. **Everything derived is recomputed, not incremental.** `fantasy_averages` and all
   views are rebuilt from the full log tables every run. Row counts and even
   `rowid`s change. **Never store a `rowid` or a row's position as a reference.**
8. **Duplicates are prevented, not impossible.** The UNIQUE indexes are created by
   `ensure_unique_index()` at ingest and backfilled by `create_log_indexes.py`. A DB
   copy that predates plan 012 and never had a run can lack them. Query 3 in §2.
9. **Missing IDs are dropped, silently-ish.** `fantasy_logs` ingest drops rows with a
   null `PLAYER_ID`/`GAME_ID` and reports the count in the success email only — a run
   that both drops rows and fails a later stage reports only the failure. So the log
   tables can be missing player-games with no visible trace in the DB.
10. **`SEASON_SEGMENT` strings are the season source of truth and are free text.**
    A BigDataBall format change (e.g. dropping "NBA") silently reclassifies rows or
    drops them from `fantasy_averages`. If your counts disagree with the pipeline's,
    check query 5 in §2 first.

---

## 9. Recommended integration pattern for `nba-dfs-stats-lab`

1. **Own your copy of what you need.** ATTACH read-only, `INSERT ... SELECT` into your
   own tables, DETACH. Snapshot with an ingest timestamp and the source DB's `mtime`.
   That gives you reproducible analysis even though `fantasy_averages` is rebuilt daily.
2. **Key everything on `PLAYER_ID` + `DATE`.** Resolve projection/lineup player names to
   `PLAYER_ID` once, at ingest, storing the resolution method and score. Everything
   downstream joins on IDs.
3. **Prefer `fantasy_logs` over `fantasy_averages` as your source.** The averages table
   is a presentation artifact for Excel, with rounding, `fillna(0)`, a build-date-relative
   L30 window, and per-team season splits. For a stats lab you want the per-game rows and
   your own aggregation — especially so you can compute "as of slate date" features
   without lookahead. Pull `fantasy_averages` only if you specifically want to reproduce
   the numbers the maintainer's Excel workbook shows.
4. **Guard against lookahead.** `fantasy_logs` contains the *outcome* (`DK_POINTS`) of
   every game. When joining a historical projection to actuals, be explicit about which
   columns are features (known pre-lock) and which are labels (known post-game).
   `DK_SALARY` and `DK_POSITION` are pre-lock; everything else in the row is post-game.
5. **Absences are a first-class feature now.** `player_absences` with `ABSENCE_TYPE`
   lets you model "who was out" for a slate — previously only inferable from a missing
   box score, which conflates "injured" with "feed not yet ingested". Note the
   `MIN(DATE)` coverage caveat in §5.3.
6. **Record the source schema version.** Store the `sqlite_master` DDL hash (or at least
   the column list of each table you read) with each snapshot. This document will go
   stale; a recorded schema fingerprint turns "our numbers changed" into a diff.

---

## 10. Where to look in the pipeline repo

Everything lives under `src/bigdataball/` in `JonnyRank/bigdataball-data`.

| Question | File |
|----------|------|
| Where's the DB? | `paths.py` |
| What writes `fantasy_logs`? | `daily_fantasy_log_upload.py` (inline loop in `main()`) |
| What writes `player_logs`? | `daily_player_upload.py` |
| What writes `player_absences`? | `absence_ingestion.py` (+ `backfill_player_absences.py`) |
| What builds `fantasy_averages` and the averages views? | `create_summary_tables.py` |
| What builds the slate views/CSVs? | `export_slate_averages_vw.py`, `export_playoffs_slate_averages_vw.py`, `export_slate_averages_csv.py`, `dk_matching.py` |
| Canonical player names | `mappings.py` |
| Team abbreviations / `map_teams` | `seed_map_teams.py` |
| Season constants | `seasons.py` |
| The UNIQUE indexes | `create_log_indexes.py`, `check_ingest_duplicates.py` |
| The ID-type migration | `patch_fantasy_id_types.py` |
| Architecture / conventions / known concerns | `docs/codebase/*.md`, `CLAUDE.md` |
| Change history and rationale | `plans/README.md` and `plans/0NN-*.md` (012, 013, 014 are the relevant ones) |
