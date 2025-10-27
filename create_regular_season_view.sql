-- SQLite
-- This script creates a view for regular season player averages.
-- It groups "Regular Season" and "In-Season Tournament" data together.

-- Drop the view if it already exists to ensure we're creating the latest version.
DROP VIEW IF EXISTS vw_player_averages_regular_season;

-- Create the view using a Common Table Expression (CTE) for clarity and correctness
CREATE VIEW vw_player_averages_regular_season AS
WITH logs_with_season AS (
    SELECT
        *,
        -- This CASE statement creates a unified 'yyyy-yy' season key for all relevant segments
        CASE
            -- For 'NBA 2023-2024 Regular Season', creates '2023-24'
            WHEN SEASON_SEGMENT LIKE '%Regular Season%' THEN SUBSTR(SEASON_SEGMENT, 5, 4) || '-' || SUBSTR(SEASON_SEGMENT, 12, 2)
            -- For 'NBA 2023 In-Season Tournament', also creates '2023-24'
            WHEN SEASON_SEGMENT LIKE '%In-Season Tournament%' THEN SUBSTR(SEASON_SEGMENT, 5, 4) || '-' || SUBSTR(CAST(SUBSTR(SEASON_SEGMENT, 5, 4) AS INTEGER) + 1, 3, 2)
        END AS SEASON_KEY
    FROM
        fantasy_logs
    WHERE
        SEASON_SEGMENT LIKE '%Regular Season%' OR SEASON_SEGMENT LIKE '%In-Season Tournament%'
)
SELECT
    lws.SEASON_KEY AS SEASON,
    dp.PLAYER_NAME AS PLAYER,
    mt.TEAM_ABBREVIATION AS TEAM,
    COUNT(lws.GAME_ID) AS GP,
    SUM(CASE WHEN lws.STARTED = 'Y' THEN 1 ELSE 0 END) AS GS,
    AVG(lws.DK_SALARY) AS SALPG,
    AVG(lws.DK_POINTS) AS FPPG,
    AVG(lws.MINUTES) AS MPG,
    IFNULL(SUM(lws.DK_POINTS) / SUM(lws.MINUTES), 0) AS FPPM,
    IFNULL(AVG(CASE WHEN lws.STARTED = 'Y' THEN lws.DK_POINTS ELSE NULL END), 0) AS GSFPPG,
    IFNULL(AVG(CASE WHEN lws.STARTED = 'Y' THEN lws.MINUTES ELSE NULL END), 0) AS GSMPG,
    IFNULL(SUM(CASE WHEN lws.STARTED = 'Y' THEN lws.DK_POINTS ELSE 0 END) / SUM(CASE WHEN lws.STARTED = 'Y' THEN lws.MINUTES ELSE NULL END), 0) AS GSFPPM,
    AVG(lws.USAGE) AS USG
FROM
    logs_with_season lws
LEFT JOIN dim_players dp ON lws.PLAYER_ID = dp.PLAYER_ID
LEFT JOIN map_teams mt ON lws.TEAM = mt.RAW_TEAM_NAME
GROUP BY
    SEASON, PLAYER, TEAM;
