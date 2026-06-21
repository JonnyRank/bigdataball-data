# seasons.py
# Season filters for the slate views and exports.
# Update these THREE values at the start of each NBA season; nothing else changes.
SLATE_SEASONS = ("2024-25", "2025-26")  # multi-season span for vw_daily_slate + main CSV
L30_SEASON = "2025-26"                   # current regular season for L30 views/CSVs
PLAYOFFS_SEASON = "2026"                 # current playoff year for vw_daily_slate_playoffs


def slate_seasons_sql():
    """Render SLATE_SEASONS as the body of a SQL IN (...) list, e.g. "'2024-25', '2025-26'"."""
    return ", ".join(f"'{s}'" for s in SLATE_SEASONS)
