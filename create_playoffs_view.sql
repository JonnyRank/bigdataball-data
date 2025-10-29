-- SQLite
-- This script creates a view for playoff player averages.
-- It groups "Playoffs" and "Play-In" data together.

-- Drop the view if it already exists to ensure we're creating the latest version.
DROP VIEW IF EXISTS vw_player_averages_playoffs;

-- Create the view using a Common Table Expression (CTE) for clarity and correctness
CREATE VIEW vw_player_averages_playoffs AS
WITH logs_with_season AS (
    SELECT
        *,
        -- This CASE statement creates a unified 'yyyy' season key for all relevant segments
        CASE
            -- For 'NBA 2024 Playoffs' or 'NBA 2024 Play-In', this extracts '2024'
            WHEN SEASON_SEGMENT LIKE '%Playoffs%' THEN SUBSTR(SEASON_SEGMENT, 5, 4)
            WHEN SEASON_SEGMENT LIKE '%Play-In%' THEN SUBSTR(SEASON_SEGMENT, 5, 4)
        END AS SEASON_KEY
    FROM
        fantasy_logs
    WHERE
        SEASON_SEGMENT LIKE '%Playoffs%' OR SEASON_SEGMENT LIKE '%Play-In%'
)
SELECT
    lws.SEASON_KEY AS SEASON,
    dp.PLAYER_NAME AS PLAYER,
    mt.TEAM_ABBREVIATION AS TEAM,
    COUNT(lws.GAME_ID) AS GP,
    SUM(CASE WHEN lws.STARTED = 'Y' THEN 1 ELSE 0 END) AS GS,
    ROUND(AVG(lws.DK_SALARY), 0) AS SALPG,
    ROUND(AVG(lws.DK_POINTS), 2) AS FPPG,
    ROUND(AVG(lws.MINUTES), 1) AS MPG,
    ROUND(IFNULL(SUM(lws.DK_POINTS) / SUM(lws.MINUTES), 0), 2) AS FPPM,
    ROUND(IFNULL(AVG(CASE WHEN lws.STARTED = 'Y' THEN lws.DK_POINTS ELSE NULL END), 0), 2) AS GSFPPG,
    ROUND(IFNULL(AVG(CASE WHEN lws.STARTED = 'Y' THEN lws.MINUTES ELSE NULL END), 0), 1) AS GSMPG,
    ROUND(IFNULL(SUM(CASE WHEN lws.STARTED = 'Y' THEN lws.DK_POINTS ELSE 0 END) / SUM(CASE WHEN lws.STARTED = 'Y' THEN lws.MINUTES ELSE NULL END), 0), 2) AS GSFPPM,
    ROUND(AVG(lws.USAGE), 1) AS USG
FROM
    logs_with_season lws
LEFT JOIN dim_players dp ON lws.PLAYER_ID = dp.PLAYER_ID
LEFT JOIN map_teams mt ON lws.TEAM = mt.RAW_TEAM_NAME
GROUP BY
    SEASON, PLAYER, TEAM;
