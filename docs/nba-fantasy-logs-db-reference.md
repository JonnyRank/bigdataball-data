# `nba_fantasy_logs.db` — Consumer Reference

**Audience:** an agent/session building **`nba-dfs-stats-lab`** (a separate SQLite
database ingesting historical NBA DFS projections and lineups) that will read
`nba_fantasy_logs.db` via a **read-only URI `ATTACH`**.

**Scope:** `nba-dfs-stats-lab` reads the **five foundational tables only** —
`fantasy_logs`, `player_logs`, `player_absences`, `dim_players`, `map_teams`. The
calculated table (`fantasy_averages`) and all five views are deliberately out of
scope; aggregates are computed in the lab from the per-game rows. §4 says why, and
§5.6 carries forward the derivation rules that decision hands you.

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

**The single most important consequence:** `PLAYER_ID` holds **integer values** in all
four tables that carry it — `fantasy_logs`, `player_logs`, `player_absences`,
`dim_players`. Join on it directly. `GAME_ID` is integer-valued and **unpadded**
(e.g. `22500001`); do not zero-pad, do not treat it as TEXT.

Note the distinction between *stored values* and *declared column types*: only
`fantasy_logs` (plan 014) and `dim_players` (explicit DDL) declare `INTEGER`.
`player_logs` and `player_absences` were created implicitly by pandas, so their ID
columns carry whatever affinity pandas inferred (`BIGINT`) — the values are integers
because the feeds deliver clean integer IDs, not because anything enforces it. In
SQLite this rarely matters, since affinity governs coercion rather than the stored
class, but it does mean `PRAGMA table_info` and `typeof()` will disagree in wording.
Check with `typeof()` (query 2 in §2), not the declared type.

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
PRAGMA table_info(map_teams);

-- 2. Actual storage classes of the ID columns (declared type != stored type in SQLite)
SELECT DISTINCT typeof(PLAYER_ID), typeof(GAME_ID) FROM fantasy_logs;
SELECT DISTINCT typeof(PLAYER_ID), typeof(GAME_ID) FROM player_logs;
SELECT DISTINCT typeof(PLAYER_ID), typeof(GAME_ID) FROM player_absences;
-- Expect 'integer' everywhere.
--   fantasy_logs reporting 'real'  -> plan 014 has not been applied to this copy
--                                     of the DB; fix with:
--                                     python -m bigdataball.patch_fantasy_id_types
--   player_logs / player_absences reporting 'real' -> NOT fixable by that script
--                                     (it rewrites fantasy_logs only). This would be
--                                     a new, unexplained condition -- investigate the
--                                     source feed before building on those tables,
--                                     and CAST(... AS INTEGER) on that side of any
--                                     cross-table join in the meantime. See the
--                                     player_logs ID-hardening note in §8.

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

-- 5. Season coverage. These are the raw strings you will parse yourself (§5.6),
--    so check them against the classification rules rather than assuming.
SELECT SEASON_SEGMENT, COUNT(*) FROM fantasy_logs GROUP BY 1 ORDER BY 1;
SELECT SEASON_SEGMENT, COUNT(*) FROM player_logs  GROUP BY 1 ORDER BY 1;

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

## 3. Connecting

The DB lives at `<base>/nba_fantasy_logs.db`, where the pipeline resolves `<base>` as
`BIGDATABALL_DATA_DIR` env override → `G:\My Drive\Documents\bigdataball` if that
mount exists → `<bigdataball-data repo root>/Data`. Take the path from your own config
rather than re-implementing that precedence.

**The connection mechanics are already handled by `nba_dfs_stats_lab.connection`**
(`get_connection` / `read_only_uri` / `attach_ops`) — `uri=True` on the main
connection, Windows drive-letter and space handling in the URI, absolute-path
enforcement, and a validated attach alias. Nothing in this document needs to change
that. What follows is only the part that module does *not* cover.

**Verify the read-only attach actually took effect.** `attach_ops`' docstring states
"Any write to `ops.*` raises OperationalError" — that is a claim about SQLite's
behavior, not something the code checks. If a `file:` URI were ever treated as a
literal filename, you would get a silently *writable* handle to the maintainer's
production DB. Probe it once at startup, inside a savepoint rolled back
unconditionally, so the check cannot leave a mark in the very case it detects:

```python
def assert_attached_readonly(conn, alias="ops"):
    conn.execute("SAVEPOINT ro_probe")
    try:
        conn.execute(f"CREATE TABLE {alias}.__ro_probe__(x)")
    except sqlite3.OperationalError:
        return                                   # expected: readonly database
    finally:
        conn.execute("ROLLBACK TO ro_probe")     # unconditional
        conn.execute("RELEASE ro_probe")
    raise RuntimeError(
        f"{alias} attached WRITABLE - the mode=ro URI did not take effect. Refusing "
        "to continue: this handle can modify the source database."
    )
```

Verified on SQLite 3.45.1: the read-only case raises `attempt to write a readonly
database`, and the writable case leaves `sqlite_master` unchanged after the rollback.

**Operational caveats:**

- **The pipeline rewrites tables under you.** `fantasy_averages` is dropped and
  recreated (`if_exists="replace"`) on every run, and `patch_fantasy_id_types.py` /
  `check_ingest_duplicates.py` rebuild or delete rows. A connection holding `ops`
  attached across a pipeline run can see errors or a torn view. Keep read
  connections short-lived: attach, read, close.
- **`mode=ro` is not `immutable=1`.** If the source DB is ever left in WAL mode, a
  read-only open needs to reach its `-wal`/`-shm` sidecars and fails with "unable to
  open database file" if it can't. The pipeline never sets `journal_mode` (so it stays
  `delete`), but check for stray `nba_fantasy_logs.db-wal` files before blaming your
  URI. Do **not** reach for `immutable=1`: it asserts the file never changes, which is
  false for a DB rewritten daily, and yields silent garbage rather than an error.
  (Note your analytics DB sets `journal_mode = WAL` — that's yours, and unrelated.)
- **Don't create views in your DB that reference `ops.*`.** They only resolve while
  that alias is attached, so the DB breaks for anyone opening it standalone.
  Materialize into your own tables instead (see §9).
- `INSERT INTO main.x SELECT ... FROM ops.y` is the intended pattern.

---

## 4. What is in scope

**The five tables `nba-dfs-stats-lab` reads.** These are the foundational, ingested
tables — everything else in the file is derived from them.

| Table | Grain | Written by |
|-------|-------|------------|
| `fantasy_logs` | one row per player per game (DFS feed, includes DK salary/points) | `daily_fantasy_log_upload.py` (inline loop) |
| `player_logs` | one row per player per game (box-score feed) | `daily_player_upload.py` |
| `player_absences` | one row per player per **missed** game | `absence_ingestion.py` (via `daily_player_upload.py`, or `backfill_player_absences.py`) |
| `dim_players` | one row per player | learned by all three ingest paths |
| `map_teams` | one row per raw team string | `seed_map_teams.py` |

**Indexes**

| Index | Table | Definition |
|-------|-------|------------|
| `idx_fantasy_logs_player_date` | `fantasy_logs` | UNIQUE (`"PLAYER_ID"`, `"DATE"`) |
| `idx_player_logs_player_date` | `player_logs` | UNIQUE (`"PLAYER_ID"`, `"DATE"`) |
| `idx_player_absences_player_date` | `player_absences` | UNIQUE (`"PLAYER_ID"`, `"DATE"`) |

Plus the implicit index on `dim_players.PLAYER_ID` (`INTEGER PRIMARY KEY` — a rowid
alias, so no separate index object). `map_teams` has **no** index and **no** PK.

### Out of scope — the derived objects, and why to leave them alone

The DB also contains one calculated table, `fantasy_averages` (built by
`create_summary_tables.py`), and five views on top of it:
`vw_player_averages_regular_season`, `vw_player_averages_playoffs`, `vw_daily_slate`,
`vw_daily_slate_l30`, `vw_daily_slate_playoffs`. **Do not query any of them.** You will
see them in `sqlite_master`, and two of them look like exactly what a stats lab wants.
They are not:

- **They are presentation artifacts for Excel.** `fantasy_averages` is rounded,
  `fillna(0)`'d (so a single-game stdev, a zero-minute rate, and a real zero are
  indistinguishable), and split per team — a traded player has multiple rows for one
  season, so naively averaging them is wrong.
- **One column is time-dependent.** `L30FPPM` is computed against
  `pd.Timestamp.now()` at *build* time, not slate date. It changes meaning depending on
  when the pipeline last ran and silently goes to `0` in the offseason.
- **The three `vw_daily_slate*` views are ephemeral.** Their `WHERE PLAYER IN (...)`
  list is regenerated each run from whatever `~/Downloads/DKEntries.csv` contained that
  day, fuzzy-matched. They describe one slate, not history.
- **All of it is dropped and recreated every run** (`if_exists="replace"`, `DROP VIEW`
  / `CREATE VIEW`), so nothing in them is a stable reference.

Computing your own aggregates from the five foundational tables is both more correct
and more flexible — it is the only way to get "as of slate date" features without
lookahead. §5.6 carries forward the derivation rules you inherit by doing so.

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
integer-valued because the player feed delivers clean integer IDs — no explicit cast
is applied here, unlike `fantasy_logs` (see the ID-hardening note in §8).

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
-- Usually 0, but a nonzero count is legitimate for historical rows (see above).
-- It is a data-quality signal to inspect, not a failure: when a (PLAYER_ID, DATE)
-- appears in both tables, treat the player_logs box score as authoritative and
-- ignore the absence row.
SELECT COUNT(*) FROM player_absences a
JOIN player_logs p ON a.PLAYER_ID = p.PLAYER_ID AND a.DATE = p.DATE;
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

> A raw team string with no `map_teams` row maps to NULL. In the pipeline that
> silently drops those players from its aggregates (pandas `groupby` discards NULL
> keys); in your code it will do whatever your join does, which is why §5.6 recommends
> failing loudly instead. `seed_map_teams.py` exits non-zero on an unmapped name, but
> only when it is run. Query 6 in §2 is the check.

### 5.6 Derivations you now own

By reading only the foundational tables you also take on the three derivations
`create_summary_tables.py` used to perform. Replicate them once in
`nba-dfs-stats-lab` and reuse; they are the difference between your numbers matching
the pipeline's and quietly diverging.

**1. Season type and season key — from `SEASON_SEGMENT`.** This is the only season
marker in the log tables, and it is free text (e.g. `"2024-25 NBA Regular Season"`).
The pipeline's classification:

- `'Regular'` ⇐ `SEASON_SEGMENT` contains `"Regular Season"` **or** `"In-Season Tournament"`
- `'Playoffs'` ⇐ contains `"Playoffs"` **or** `"Play-In"`
- anything else ⇒ the row is **dropped** from the pipeline's aggregates entirely

So **IST games count as regular season and Play-In games count as playoffs.** The
season key is the first 4-digit year found in the string, rendered `YYYY-YY` for
regular season (`"2024-25"`) and `YYYY` for playoffs (`"2026"`). Decide deliberately
whether to keep the "anything else is dropped" behavior — silently dropping is a
reasonable pipeline default but a bad one for a stats lab, where an unrecognized
segment string should surface loudly. Run query 5 in §2 to see the live values.

**2. Team abbreviation — via `map_teams`.** The log tables hold the raw string
(`"Golden State"`); join `TEAM = map_teams.RAW_TEAM_NAME` for `TEAM_ABBREVIATION`
(`"GSW"`). A raw name with no mapping row yields NULL, and pandas' `groupby` silently
drops NULL keys — which is how a whole team can vanish from an aggregate without an
error. Use an inner join and assert the row count, or `LEFT JOIN` and fail on NULL.

**3. Canonical player name — via `dim_players`.** Never take the name from a log row.
See §7.

**If you ever want parity with the maintainer's Excel numbers**, two conventions
matter: the pipeline computes `FPPM` as `SUM(DK_POINTS) / SUM(MINUTES)` (not the mean
of per-game ratios), and games started as `COUNT(STARTED = 'Y')`. Its stdevs are pandas
defaults, i.e. **sample** (ddof=1), which is also SQLite's non-default — plain SQLite
has no `STDDEV`, so you will be computing it yourself anyway.

---

## 6. Keys and the join model

```text
dim_players (PLAYER_ID PK, PLAYER_NAME)   ← canonical name
     ▲ PLAYER_ID          ▲ PLAYER_ID           ▲ PLAYER_ID
     │                     │                     │
fantasy_logs          player_logs          player_absences
(PLAYER_ID, DATE) U   (PLAYER_ID, DATE) U  (PLAYER_ID, DATE) U
     │
     └─ TEAM ──► map_teams.RAW_TEAM_NAME ──► TEAM_ABBREVIATION
```

- **Player-game grain:** `(PLAYER_ID, DATE)` — unique and indexed on all three log
  tables. Use this, not `(PLAYER_ID, GAME_ID)`.
- **`GAME_ID`** identifies the *game*, so teammates share it. Present and
  integer-valued in all three log tables, but **not** part of any uniqueness
  constraint. It is the right key for "who else played in this game".
- **Player identity:** `PLAYER_ID`. Stable, integer, and the only join key you should
  use between tables inside this DB.
- **Team:** raw string in the log tables; `map_teams` is the only bridge to an
  abbreviation. There is no team dimension table and no team ID.
- **Season:** `SEASON_SEGMENT` free text only — parse it yourself (§5.6).

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
   ingested*, so a mapping added later is not reflected in older rows. The pipeline's
   own aggregation deliberately **drops** the log-table `PLAYER` and re-joins
   `dim_players.PLAYER_NAME`. **Do the same: join names from `dim_players`, never from
   the log tables.**
3. **`run_db_patch.py` retroactively rewrites names** in `dim_players`, `fantasy_logs`,
   and `player_logs` whenever a new mapping is added — but it is a manual, one-off
   script. So names can change between your ingest runs. **Store `PLAYER_ID`, and treat
   names as a display attribute you re-resolve at query time.** Never use a name as a
   foreign key.
4. **`PLAYER_NAME_MAP` lives in the pipeline repo, not in the DB.** If you need it,
   either vendor a copy (and accept drift) or import it via
   `from bigdataball.mappings import PLAYER_NAME_MAP` after `pip install -e` on the
   pipeline repo. A stale vendored copy is a silent-mismatch generator; prefer the
   import, or at minimum add a test that diffs the two.
5. **The pipeline's own DK→DB matching is fuzzy** (`thefuzz.process.extractOne`,
   accept at **score ≥ 90**, after an exact `PLAYER_NAME_MAP` pass). If you reuse that
   approach for historical projections, note that a ≥90 threshold does make wrong
   matches on similar names (Jr./Sr., brothers, common surnames) — **record the matched
   `PLAYER_ID`, the score, and the original string** so a bad match is auditable rather
   than baked in.

**Recommended resolution order for a historical projection name:** exact match on
`dim_players.PLAYER_NAME` → apply `PLAYER_NAME_MAP` then exact → fuzzy with a recorded
score → unresolved queue for manual mapping. Never silently drop an unresolved name.

---

## 8. Gotchas that will cost you a day

1. **`STARTED` is the string `'Y'`/`'N'`,** not 0/1 or a boolean. Same for `VENUE`
   (`'R'`/`'H'`/`'N'`).
2. **`player_logs` does not have `fantasy_logs`' plan-014 ID hardening.**
   `fantasy_logs` explicitly casts incoming IDs to int and declares `Integer()` on
   insert; `player_logs` relies on pandas inferring int64 from a clean feed. Believed
   correct today, and the pipeline repo records it as a known, investigate-only
   asymmetry — but it means `player_logs.PLAYER_ID` has no *declared* integer type.
   Confirm with query 2 in §2 and consider `CAST(... AS INTEGER)` on that side of a
   cross-table join if the check surprises you.
3. **`rowid` is not stable.** `fantasy_logs` is dropped and rebuilt wholesale by
   `patch_fantasy_id_types.py`, and `check_ingest_duplicates.py --remove` deletes rows.
   **Never store a `rowid` or a row's ordinal position as a reference** — key on
   `(PLAYER_ID, DATE)`.
4. **Duplicates are prevented, not impossible.** The UNIQUE indexes are created by
   `ensure_unique_index()` at ingest and backfilled by `create_log_indexes.py`. A DB
   copy predating plan 012 that has never had a run can lack them. Query 3 in §2.
5. **Missing IDs are dropped, silently-ish.** `fantasy_logs` ingest drops rows with a
   null `PLAYER_ID`/`GAME_ID` and reports the count in the success email only — a run
   that both drops rows and fails a later stage reports only the failure. The log
   tables can therefore be missing player-games with no trace in the DB.
6. **`SEASON_SEGMENT` is free text and is your only season source.** A BigDataBall
   format change (e.g. dropping "NBA") would silently reclassify rows under the §5.6
   rules. Assert on the distinct values (query 5 in §2) rather than trusting a
   substring match forever.
7. **`fantasy_logs` and `player_logs` are ingested independently** from different
   feeds and may not cover identical date ranges. Don't assume a player-game in one is
   present in the other; check before making either the spine of a join.

---

## 9. Recommended integration pattern

1. **Own your copy.** ATTACH read-only, `INSERT ... SELECT` into your own tables,
   close. Snapshot with an ingest timestamp and the source DB's `mtime` so your
   analysis is reproducible even though the source is rewritten daily.
2. **Key everything on `PLAYER_ID` + `DATE`.** Resolve projection/lineup names to
   `PLAYER_ID` once, at ingest, storing the resolution method and score. Everything
   downstream joins on IDs.
3. **Guard against lookahead.** `fantasy_logs` contains the *outcome* (`DK_POINTS`) of
   every game. When joining a historical projection to actuals, be explicit about which
   columns are features (known pre-lock) and which are labels (known post-game).
   `DK_SALARY` and `DK_POSITION` are pre-lock; everything else in the row is post-game.
4. **Absences are a first-class feature.** `player_absences` with `ABSENCE_TYPE` lets
   you model "who was out" for a slate — previously only inferable from a missing box
   score, which conflates "injured" with "feed not yet ingested". Note the `MIN(DATE)`
   coverage caveat in §5.3.
5. **Record the source schema version.** Store the `sqlite_master` DDL hash (or at
   least the column list of each table you read) with each snapshot. This document will
   go stale; a recorded fingerprint turns "our numbers changed" into a diff.

---

## 10. Where to look in the pipeline repo

Everything lives under `src/bigdataball/` in `JonnyRank/bigdataball-data`.

| Question | File |
|----------|------|
| Where's the DB? | `paths.py` |
| What writes `fantasy_logs`? | `daily_fantasy_log_upload.py` (inline loop in `main()`) |
| What writes `player_logs`? | `daily_player_upload.py` |
| What writes `player_absences`? | `absence_ingestion.py` (+ `backfill_player_absences.py`) |
| Canonical player names | `mappings.py` |
| Team abbreviations / `map_teams` | `seed_map_teams.py` |
| The UNIQUE indexes | `create_log_indexes.py`, `check_ingest_duplicates.py` |
| The ID-type migration | `patch_fantasy_id_types.py` |
| The derived objects you're *not* reading (§4) | `create_summary_tables.py`, `export_*.py`, `seasons.py` |
| Architecture / conventions / known concerns | `docs/codebase/*.md`, `CLAUDE.md` |
| Change history and rationale | `plans/README.md` and `plans/0NN-*.md` (012, 013, 014 are the relevant ones) |
