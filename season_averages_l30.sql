-- SQLite
-- This query calculates player averages strictly for the past 30 days.
-- It filters the logs first, so all resulting metrics (GP, FPPG, FPPM)
-- reflect the L30 window.

WITH SeasonLogs AS (
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
        (fl.SEASON_SEGMENT LIKE 'NBA 2025-2026%' OR fl.SEASON_SEGMENT LIKE 'NBA 2025 In-%')
        AND fl.DATE >= date('now', '-30 days') -- RESTRICT TO LAST 30 DAYS
),
LatestTeam AS (
    SELECT
        PLAYER_ID,
        TEAM_ABBREVIATION
    FROM
        SeasonLogs
    WHERE
        rn = 1
)
SELECT
    'L30 Days' AS SEASON,
    sl.PLAYER_NAME AS PLAYER,
    lt.TEAM_ABBREVIATION AS TEAM,
    COUNT(sl.GAME_ID) AS GP,
    SUM(CASE WHEN sl.STARTED = 'Y' THEN 1 ELSE 0 END) AS GS,
    ROUND(AVG(sl.MINUTES), 1) AS MPG,
    ROUND(AVG(CASE WHEN sl.STARTED = 'Y' THEN sl.MINUTES END), 1) AS GSMPG,
    ROUND(AVG(sl.DK_POINTS), 2) AS FPPG,
    ROUND(AVG(CASE WHEN sl.STARTED = 'Y' THEN sl.DK_POINTS END), 2) AS GSFPPG,
    ROUND(IFNULL(SUM(sl.DK_POINTS) / NULLIF(SUM(sl.MINUTES), 0), 0), 2) AS FPPM,
    ROUND(IFNULL(SUM(CASE WHEN sl.STARTED = 'Y' THEN sl.DK_POINTS END) / NULLIF(SUM(CASE WHEN sl.STARTED = 'Y' THEN sl.MINUTES END), 0), 0), 2) AS GSFPPM
FROM
    SeasonLogs sl
JOIN
    LatestTeam lt ON sl.PLAYER_ID = lt.PLAYER_ID
    where sl.Player_Name = 'Victor Wembanyama'
GROUP BY
    sl.PLAYER_ID,
    sl.PLAYER_NAME,
    lt.TEAM_ABBREVIATION
ORDER BY
    lt.TEAM_ABBREVIATION asc,
    FPPG DESC;