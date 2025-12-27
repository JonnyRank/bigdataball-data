-- SQLite
-- This query calculates player averages for the last X games played.
-- Unlike the date-based query, this ensures every player has the same sample size of games
-- (unless they haven't played X games yet this season).

WITH Params AS (
    SELECT 6 AS X -- <--- CHANGE THIS NUMBER to filter for last X games (e.g., 5, 10, 15)
),
SeasonLogs AS (
    SELECT
        fl.*,
        dp.PLAYER_NAME,
        mt.TEAM_ABBREVIATION,
        -- Rank games by date descending for each player (1 = most recent game)
        ROW_NUMBER() OVER(PARTITION BY fl.PLAYER_ID ORDER BY fl.DATE DESC) as game_rank
    FROM
        fantasy_logs fl
    LEFT JOIN
        dim_players dp ON fl.PLAYER_ID = dp.PLAYER_ID
    LEFT JOIN
        map_teams mt ON fl.TEAM = mt.RAW_TEAM_NAME
    WHERE
        (fl.SEASON_SEGMENT LIKE 'NBA 2025-2026%' OR fl.SEASON_SEGMENT LIKE 'NBA 2025 In-%')
),
LatestTeam AS (
    SELECT
        PLAYER_ID,
        TEAM_ABBREVIATION
    FROM
        SeasonLogs
    WHERE
        game_rank = 1
)
SELECT
    '2025-26' AS SEASON,
    sl.PLAYER_NAME AS PLAYER,
    lt.TEAM_ABBREVIATION AS TEAM,
    -- Season Averages
    COUNT(sl.GAME_ID) AS GP,
    SUM(CASE WHEN sl.STARTED = 'Y' THEN 1 ELSE 0 END) AS GS,
    ROUND(AVG(sl.MINUTES), 1) AS MPG,
    ROUND(AVG(CASE WHEN sl.STARTED = 'Y' THEN sl.MINUTES END), 1) AS GSMPG,
    ROUND(AVG(sl.DK_POINTS), 2) AS FPPG,
    ROUND(AVG(CASE WHEN sl.STARTED = 'Y' THEN sl.DK_POINTS END), 2) AS GSFPPG,
    ROUND(IFNULL(SUM(sl.DK_POINTS) / NULLIF(SUM(sl.MINUTES), 0), 0), 2) AS FPPM,
    ROUND(IFNULL(SUM(CASE WHEN sl.STARTED = 'Y' THEN sl.DK_POINTS END) / NULLIF(SUM(CASE WHEN sl.STARTED = 'Y' THEN sl.MINUTES END), 0), 0), 2) AS GSFPPM,
    -- Last X Games Averages (Controlled by Params CTE)
    COUNT(CASE WHEN sl.game_rank <= p.X THEN sl.GAME_ID END) AS LX_GP,
    ROUND(AVG(CASE WHEN sl.game_rank <= p.X THEN sl.MINUTES END), 1) AS LX_MPG,
    ROUND(AVG(CASE WHEN sl.game_rank <= p.X THEN sl.DK_POINTS END), 2) AS LX_FPPG,
    ROUND(IFNULL(SUM(CASE WHEN sl.game_rank <= p.X THEN sl.DK_POINTS END) / NULLIF(SUM(CASE WHEN sl.game_rank <= p.X THEN sl.MINUTES END), 0), 0), 2) AS LX_FPPM
FROM
    SeasonLogs sl
JOIN
    LatestTeam lt ON sl.PLAYER_ID = lt.PLAYER_ID
CROSS JOIN
    Params p
WHERE
    1=1
    AND sl.PLAYER_NAME = 'Jordan Walsh' -- <--- Filter by Player Name
GROUP BY
    sl.PLAYER_ID,
    sl.PLAYER_NAME,
    p.X,
    lt.TEAM_ABBREVIATION
ORDER BY
    lt.TEAM_ABBREVIATION ASC,
    FPPG DESC;
