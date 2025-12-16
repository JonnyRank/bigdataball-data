-- SQLite
-- This query calculates player season averages for the '2025-2026' season,
-- ensuring one record per player, reflecting their most recent team.
-- It includes standard season-long metrics and a special 'L30FPPM' metric
-- for recent performance, plus starter-specific stats and volatility (STDV).

WITH SeasonLogs AS (
    -- First, select all game logs for the target season and rank them by date for each player
    -- to identify their most recent team.
    SELECT
        fl.*,
        dp.PLAYER_NAME,
        mt.TEAM_ABBREVIATION,
        ROW_NUMBER() OVER(PARTITION BY fl.PLAYER_ID ORDER BY fl.DATE DESC) as rn
    FROM
        fantasy_logs fl
    LEFT JOIN
        dim_players dp ON fl.PLAYER_ID = dp.PLAYER_ID
    LEFT JOIN
        map_teams mt ON fl.TEAM = mt.RAW_TEAM_NAME
    WHERE
        fl.SEASON_SEGMENT LIKE 'NBA 2025-2026%'
),
LatestTeam AS (
    -- Second, create a map of each player to their most recent team abbreviation.
    SELECT
        PLAYER_ID,
        TEAM_ABBREVIATION
    FROM
        SeasonLogs
    WHERE
        rn = 1
)
-- Finally, aggregate the stats for each player across the entire season.
SELECT
    '2025-26' AS SEASON,
    sl.PLAYER_NAME AS PLAYER,
    lt.TEAM_ABBREVIATION AS TEAM,
    COUNT(sl.GAME_ID) AS GP,
    SUM(CASE WHEN sl.STARTED = 'Y' THEN 1 ELSE 0 END) AS GS,
    ROUND(AVG(sl.MINUTES), 1) AS MPG,
    ROUND(AVG(CASE WHEN sl.STARTED = 'Y' THEN sl.MINUTES END), 1) AS GSMPG,
    ROUND(AVG(sl.DK_POINTS), 2) AS FPPG,
    ROUND(AVG(CASE WHEN sl.STARTED = 'Y' THEN sl.DK_POINTS END), 2) AS GSFPPG,
    ROUND(IFNULL(SUM(sl.DK_POINTS) / NULLIF(SUM(sl.MINUTES), 0), 0), 2) AS FPPM,
    ROUND(IFNULL(SUM(CASE WHEN sl.STARTED = 'Y' THEN sl.DK_POINTS END) / NULLIF(SUM(CASE WHEN sl.STARTED = 'Y' THEN sl.MINUTES END), 0), 0), 2) AS GSFPPM,
    -- Last 30 Days Fantasy Points Per Minute (L30FPPM)
    ROUND(IFNULL(SUM(CASE WHEN sl.DATE >= date('now', '-15 days') THEN sl.DK_POINTS ELSE 0 END) / NULLIF(SUM(CASE WHEN sl.DATE >= date('now', '-15 days') THEN sl.MINUTES END), 0), 0), 2) AS L30FPPM
FROM
    SeasonLogs sl
JOIN
    LatestTeam lt ON sl.PLAYER_ID = lt.PLAYER_ID
    where sl.Player_Name = 'Jordan Walsh'
GROUP BY
    sl.PLAYER_ID,
    sl.PLAYER_NAME,
    lt.TEAM_ABBREVIATION
ORDER BY
    lt.TEAM_ABBREVIATION asc,
    FPPG DESC;