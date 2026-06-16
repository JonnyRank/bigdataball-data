# Plan 008: Add a script that creates and seeds the `map_teams` table so a fresh DB can run the summary pipeline

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5576703..HEAD -- create_summary_tables.py`
> This plan adds a new script and does not modify existing ones, but it must match how
> `create_summary_tables.py` reads `map_teams`. Confirm the column names below against
> the live `create_summary_tables.py` before proceeding.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: 005 (so the new script uses `paths.resolve_base_data_path()`). If 005
  is not yet done, use the same inline path block the other scripts currently use.
- **Category**: dx
- **Planned at**: commit `5576703`, 2026-06-16

## Why this matters

`create_summary_tables.py` joins fantasy logs to a `map_teams` table to translate raw
team names into abbreviations, but **no script in the repo creates or populates
`map_teams`** — `CLAUDE.md` calls this out: "it must already exist in the DB before the
summary pipeline runs." On a fresh database the summary stage aborts (the table is in its
`required_tables` check). This plan adds a `seed_map_teams.py` script that creates the
table and populates it, so the pipeline is runnable end-to-end from an empty DB.

**Important caveat — read before starting:** the join uses the *raw* team strings exactly
as they appear in the ingested data (`fantasy_logs.TEAM`, sourced from BigDataBall's
`OWN TEAM` column). The exact spelling/format of those strings (e.g. `"Boston"` vs
`"Boston Celtics"` vs `"Celtics"`) is **not knowable from this repo** — the source `.xlsx`
files and the DB are git-ignored. Therefore the script must *derive* the raw names from
the actual data when a populated DB is available, and fall back to a documented
best-effort mapping otherwise. Do not hardcode raw names blindly.

## Current state

`create_summary_tables.py` reads the table like this:

- `MAP_TEAMS_TABLE_NAME = "map_teams"` (line ~25)
- It is in `required_tables` (lines ~42-48): the summary aborts if missing.
- The join (lines ~80-87):
```python
        df = pd.merge(
            df,
            map_teams_df[["RAW_TEAM_NAME", "TEAM_ABBREVIATION"]],
            left_on="TEAM",
            right_on="RAW_TEAM_NAME",
            how="left",
        )
```

So `map_teams` must have columns **`RAW_TEAM_NAME`** and **`TEAM_ABBREVIATION`**, and
`RAW_TEAM_NAME` must match the distinct values of `TEAM` in `fantasy_logs`. (A `LEFT`
join means unmatched teams get `NULL` abbreviations and later rows are dropped/zeroed —
so a wrong or missing raw name silently loses that team's data.)

The 30 NBA teams and their standard abbreviations (the `TEAM_ABBREVIATION` values) are
stable; only the `RAW_TEAM_NAME` keys are uncertain.

## Commands you will need

| Purpose      | Command                                                            | Expected on success |
|--------------|--------------------------------------------------------------------|---------------------|
| Syntax check | `python3 -m py_compile seed_map_teams.py`                          | exit 0              |
| Run seed     | `python3 seed_map_teams.py`                                        | prints rows written, exit 0 |
| Inspect      | `python3 -c "import sqlite3,os,paths; ..."` (see Step 4)           | lists table rows    |

## Scope

**In scope**:
- `seed_map_teams.py` (create)
- `tests/test_seed_map_teams.py` (create)
- `CLAUDE.md` — update the one note that says `map_teams` "is not created by any script"
  to point at `seed_map_teams.py` (small, factual doc fix).

**Out of scope** (do NOT touch):
- `create_summary_tables.py` — do not change its schema expectations; conform to them.
- The ingestion/upload scripts and the join logic.
- Do not invent raw team strings and commit them as authoritative without the
  data-derivation path described below.

## Git workflow

- Branch: current branch unless instructed otherwise.
- One commit; message e.g. `Add seed_map_teams script to create and populate map_teams`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Define the abbreviation lookup

Create, inside `seed_map_teams.py`, a dict from a **normalized** team name to its standard
abbreviation, covering the formats BigDataBall is most likely to emit (full city and full
"City Nickname"). Normalize by lower-casing and collapsing whitespace when looking up, so
`"Boston"`, `"boston"`, and `"Boston Celtics"` can all resolve.

> **Abbreviation convention — confirm before committing.** The values below use the
> short forms `GS` / `NY` / `NO` / `SA` for Golden State / Knicks / Pelicans / Spurs. The
> common *industry-standard* forms are `GSW` / `NYK` / `NOP` / `SAS`. Which convention the
> existing pipeline uses is **unknown from this repo** (the DB is git-ignored and no other
> script commits abbreviations). Before committing, check any existing `TEAM` /
> abbreviation usage in real data and adjust these values to match the convention already
> in use. If you cannot determine it, STOP and ask the maintainer rather than guessing.

```python
# NBA abbreviations keyed by several plausible raw-name forms.
# Keys are matched case-insensitively after whitespace normalization.
# NOTE: confirm the abbreviation convention (GS vs GSW, NY vs NYK, NO vs NOP, SA vs SAS,
# PHX vs PHO) against the real data before committing — see the caveat above.
TEAM_ABBREVIATIONS = {
    "atlanta": "ATL", "atlanta hawks": "ATL",
    "boston": "BOS", "boston celtics": "BOS",
    "brooklyn": "BKN", "brooklyn nets": "BKN",
    "charlotte": "CHA", "charlotte hornets": "CHA",
    "chicago": "CHI", "chicago bulls": "CHI",
    "cleveland": "CLE", "cleveland cavaliers": "CLE",
    "dallas": "DAL", "dallas mavericks": "DAL",
    "denver": "DEN", "denver nuggets": "DEN",
    "detroit": "DET", "detroit pistons": "DET",
    "golden state": "GS", "golden state warriors": "GS",
    "houston": "HOU", "houston rockets": "HOU",
    "indiana": "IND", "indiana pacers": "IND",
    "la clippers": "LAC", "los angeles clippers": "LAC", "clippers": "LAC",
    "la lakers": "LAL", "los angeles lakers": "LAL", "lakers": "LAL",
    "memphis": "MEM", "memphis grizzlies": "MEM",
    "miami": "MIA", "miami heat": "MIA",
    "milwaukee": "MIL", "milwaukee bucks": "MIL",
    "minnesota": "MIN", "minnesota timberwolves": "MIN",
    "new orleans": "NO", "new orleans pelicans": "NO",
    "new york": "NY", "new york knicks": "NY",
    "oklahoma city": "OKC", "oklahoma city thunder": "OKC",
    "orlando": "ORL", "orlando magic": "ORL",
    "philadelphia": "PHI", "philadelphia 76ers": "PHI",
    "phoenix": "PHX", "phoenix suns": "PHX",
    "portland": "POR", "portland trail blazers": "POR",
    "sacramento": "SAC", "sacramento kings": "SAC",
    "san antonio": "SA", "san antonio spurs": "SA",
    "toronto": "TOR", "toronto raptors": "TOR",
    "utah": "UTA", "utah jazz": "UTA",
    "washington": "WAS", "washington wizards": "WAS",
}


def normalize(name):
    return " ".join(str(name).split()).lower()
```

> The abbreviation **values** above are standard, but the exact strings BigDataBall uses
> (and thus which keys actually match) must be confirmed against real data in Step 2.

### Step 2: Derive `RAW_TEAM_NAME` values from the data when available

The script's `main()` connects to the DB at `paths.resolve_base_data_path()/nba_fantasy_logs.db`
(or the inline path block if plan 005 isn't done) and:

1. If `fantasy_logs` exists, read `SELECT DISTINCT TEAM FROM fantasy_logs` (and, if
   present, `player_logs`) to get the **actual** raw team strings. These become the
   `RAW_TEAM_NAME` values — guaranteeing the join matches.
2. For each raw value, look up `TEAM_ABBREVIATIONS[normalize(raw)]`. If found, pair them.
   If **not** found, still insert the row with `TEAM_ABBREVIATION = NULL` and print the
   unmatched raw name prominently so a human can extend the dict.
3. If `fantasy_logs` does **not** exist yet (truly empty DB), fall back to seeding the
   30 canonical rows using the **full "City Nickname"** keys as `RAW_TEAM_NAME` (best
   guess), and print a clear warning that these may not match the eventual ingested data
   and should be re-seeded after the first ingestion.

Create or replace the table each run. The writer **refuses to overwrite a `map_teams`
table that already has rows** unless an explicit override is set — this prevents a
re-run from silently destroying hand-curated mappings in a real DB. The temp-DB tests
and an empty/first-time DB are unaffected (no existing rows).

```python
import os
import sqlite3


def _map_teams_row_count(conn):
    try:
        return conn.execute("SELECT COUNT(*) FROM map_teams").fetchone()[0]
    except sqlite3.OperationalError:
        return 0  # table doesn't exist yet


def write_map_teams(conn, rows, force=None):
    """rows: list of (raw_team_name, team_abbreviation_or_None).

    Refuses to overwrite a populated map_teams unless `force` is truthy (defaults to the
    BIGDATABALL_SEED_FORCE env var). Raises RuntimeError otherwise.
    """
    if force is None:
        force = bool(os.environ.get("BIGDATABALL_SEED_FORCE"))
    if _map_teams_row_count(conn) > 0 and not force:
        raise RuntimeError(
            "map_teams already has rows; refusing to overwrite. "
            "Re-run with BIGDATABALL_SEED_FORCE=1 to replace it."
        )
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS map_teams")
    cur.execute(
        "CREATE TABLE map_teams (RAW_TEAM_NAME TEXT, TEAM_ABBREVIATION TEXT)"
    )
    cur.executemany(
        "INSERT INTO map_teams (RAW_TEAM_NAME, TEAM_ABBREVIATION) VALUES (?, ?)",
        rows,
    )
    conn.commit()
```

`main()` prints: how many rows written, how many had a matched abbreviation, and the list
of any unmatched raw names.

### Step 3: Implement `main()`

`os` and `sqlite3` are imported at the top of the file (see the `write_map_teams`
snippet above); only the `import paths` stays inside `main()` as an intentional graceful
fallback for when plan 005 isn't done yet.

```python
def main():
    try:
        import paths
        base = paths.resolve_base_data_path()
    except Exception:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Data")
    db_path = os.path.join(base, "nba_fantasy_logs.db")

    conn = sqlite3.connect(db_path)
    raw_names = _distinct_team_names(conn)  # reads fantasy_logs/player_logs if present

    if raw_names:
        rows = [(name, TEAM_ABBREVIATIONS.get(normalize(name))) for name in raw_names]
    else:
        print("WARNING: no fantasy_logs/player_logs found; seeding canonical guesses.")
        rows = _canonical_rows()  # uses 'City Nickname' keys; may need re-seeding

    write_map_teams(conn, rows)
    unmatched = [r for r, abbr in rows if abbr is None]
    print(f"Wrote {len(rows)} rows to map_teams ({len(rows) - len(unmatched)} matched).")
    if unmatched:
        print("UNMATCHED raw team names (add them to TEAM_ABBREVIATIONS):")
        for r in unmatched:
            print(f"  - {r!r}")
    conn.close()


if __name__ == "__main__":
    main()
```

Provide the two helpers used by `main()`:

```python
def _distinct_team_names(conn):
    """Distinct raw TEAM values from fantasy_logs (then player_logs). [] if neither exists."""
    names = []
    for table in ("fantasy_logs", "player_logs"):
        try:
            rows = conn.execute(f"SELECT DISTINCT TEAM FROM {table}").fetchall()
        except sqlite3.OperationalError:
            continue  # table or column not present yet
        names.extend(r[0] for r in rows if r[0] is not None)
        if names:
            break  # prefer fantasy_logs; fall through to player_logs only if empty
    # de-duplicate while preserving order
    seen = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def _canonical_rows():
    """Best-effort 30-row seed for an empty DB, keyed on 'City Nickname' raw names.

    These keys are GUESSES (see the abbreviation caveat) and should be re-seeded from
    real data after the first ingestion. Uses every 'two-word+' key in TEAM_ABBREVIATIONS
    (the full 'city nickname' forms), title-cased back into a plausible raw name.
    """
    rows = []
    for key, abbr in TEAM_ABBREVIATIONS.items():
        if " " in key and key not in ("la clippers", "la lakers"):
            rows.append((key.title(), abbr))
    # Ensure exactly the 30 teams (dedupe by abbreviation, keep first).
    seen = set()
    unique = []
    for raw, abbr in rows:
        if abbr not in seen:
            seen.add(abbr)
            unique.append((raw, abbr))
    return unique
```

> `_canonical_rows()` is a fallback only; the data-derived path in Step 2 is preferred.
> If the title-cased keys don't yield exactly 30 unique abbreviations, adjust the filter
> so all 30 teams appear — but remember these raw names are guesses to be re-seeded later.

**Verify**: `python3 -m py_compile seed_map_teams.py` → exit 0.

### Step 4: Run against a temp DB and confirm the schema

```
python3 - <<'PY'
import os, sqlite3, tempfile
os.environ["BIGDATABALL_DATA_DIR"] = tempfile.mkdtemp()
db = os.path.join(os.environ["BIGDATABALL_DATA_DIR"], "nba_fantasy_logs.db")
sqlite3.connect(db).close()  # empty DB, no fantasy_logs
import seed_map_teams
seed_map_teams.main()
c = sqlite3.connect(db).cursor()
cols = [r[1] for r in c.execute("PRAGMA table_info(map_teams)")]
n = c.execute("SELECT COUNT(*) FROM map_teams").fetchone()[0]
print("columns:", cols, "rows:", n)
assert cols == ["RAW_TEAM_NAME", "TEAM_ABBREVIATION"], cols
assert n >= 30, n
PY
```

**Verify**: prints `columns: ['RAW_TEAM_NAME', 'TEAM_ABBREVIATION'] rows: 30` (or more)
and exits 0. (This requires plan 005's `paths.py` and `BIGDATABALL_DATA_DIR`; if 005 is
not done, the script's inline fallback still works but ignores the env var — in that case
point `db` at `<repo>/Data/nba_fantasy_logs.db` instead and clean it up afterward.)

### Step 5: Unit test the lookup + writer

Create `tests/test_seed_map_teams.py`:
```python
import sqlite3

import pytest

import seed_map_teams


def test_normalize_collapses_and_lowercases():
    assert seed_map_teams.normalize("  Golden   State ") == "golden state"


def test_known_team_resolves_to_abbreviation():
    assert seed_map_teams.TEAM_ABBREVIATIONS[seed_map_teams.normalize("Boston Celtics")] == "BOS"


def test_write_map_teams_schema(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    seed_map_teams.write_map_teams(conn, [("Boston", "BOS"), ("Mystery Team", None)])
    cols = [r[1] for r in conn.execute("PRAGMA table_info(map_teams)")]
    assert cols == ["RAW_TEAM_NAME", "TEAM_ABBREVIATION"]
    rows = conn.execute("SELECT RAW_TEAM_NAME, TEAM_ABBREVIATION FROM map_teams ORDER BY RAW_TEAM_NAME").fetchall()
    assert rows == [("Boston", "BOS"), ("Mystery Team", None)]
    conn.close()


def test_write_map_teams_refuses_to_overwrite_without_force(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    seed_map_teams.write_map_teams(conn, [("Boston", "BOS")])  # first write: empty -> ok
    with pytest.raises(RuntimeError):
        seed_map_teams.write_map_teams(conn, [("Denver", "DEN")])  # populated -> refused
    # force=True overwrites
    seed_map_teams.write_map_teams(conn, [("Denver", "DEN")], force=True)
    rows = conn.execute("SELECT RAW_TEAM_NAME FROM map_teams").fetchall()
    assert rows == [("Denver",)]
    conn.close()
```

**Verify**: `python3 -m pytest -q tests/test_seed_map_teams.py` → passes.

### Step 6: Update the `CLAUDE.md` note

Find the sentence in `CLAUDE.md` stating `map_teams` "is referenced by
`create_summary_tables.py` but is not created by any script" and update it to note that
`seed_map_teams.py` now creates and seeds it (and that it should be re-run after the first
ingestion so `RAW_TEAM_NAME` matches the real data). Keep the edit to that one note.

**Verify**: `grep -n "seed_map_teams" CLAUDE.md` → at least one match.

### Step 7: Full suite

**Verify**: `python3 -m pytest -q` → all tests pass.

## Test plan

- `tests/test_seed_map_teams.py` covers name normalization, a known-team lookup, and the
  table schema/contents written by `write_map_teams` (including a `NULL` abbreviation for
  an unmatched team).
- Manual verification in Step 4 confirms an empty-DB run produces the correct schema and
  ≥30 rows.
- Verification: `python3 -m pytest -q` → all pass.

## Done criteria

ALL must hold:

- [ ] `seed_map_teams.py` exists and `python3 seed_map_teams.py` creates a `map_teams`
      table with columns `RAW_TEAM_NAME`, `TEAM_ABBREVIATION`.
- [ ] Run against a populated DB, every distinct `fantasy_logs.TEAM` value appears as a
      `RAW_TEAM_NAME` (so the join can't silently drop a team); unmatched names are
      printed for manual completion.
- [ ] `python3 -m pytest -q` exits 0; `tests/test_seed_map_teams.py` passes.
- [ ] `CLAUDE.md` no longer claims nothing creates `map_teams`.
- [ ] `git status` shows only in-scope files changed/created.
- [ ] `plans/README.md` status row for 008 updated.

## STOP conditions

Stop and report back (do not improvise) if:

- A populated DB's distinct `TEAM` values don't resolve through `TEAM_ABBREVIATIONS` for
  several teams — report the unmatched raw strings; the dict needs the real formats added,
  which is a data question for the maintainer, not a guess to commit.
- `create_summary_tables.py`'s expected column names differ from `RAW_TEAM_NAME` /
  `TEAM_ABBREVIATION` (drift) — report; do not change the summary script to match.
- The script would overwrite a `map_teams` table that already contains hand-curated rows
  in a real DB — it uses `DROP TABLE IF EXISTS`; if a populated production DB is present,
  confirm with the operator before running against it (the test/temp runs are safe).

## Maintenance notes

- This script is **re-runnable** and should be re-run after the first real ingestion so
  `RAW_TEAM_NAME` is derived from actual data rather than the canonical guesses.
- A reviewer should scrutinize the `TEAM_ABBREVIATIONS` dict for the team formats the
  data actually uses, and whether `GS`/`NO`/`NY`/`SA`/`PHX` abbreviations match the
  conventions already present elsewhere in the pipeline.
- Follow-up (deferred): consider calling `seed_map_teams.main()` from the orchestrator's
  startup only when `map_teams` is absent, so a fresh DB self-heals. Out of scope here to
  keep the change additive and review-light.
