-- SQLite
-- This script creates a view that calculates season-long player averages.
-- It joins the logs, player names, and team mappings to provide a clean, aggregated report.

-- Drop the view if it already exists to ensure we're creating the latest version.
DROP VIEW IF EXISTS vw_player_averages;

-- Create the view
CREATE VIEW vw_player_averages AS
SELECT
    dp.PLAYER_NAME,
    mt.TEAM_ABBREVIATION AS TEAM,
    fl.SEASON_SEGMENT,
    COUNT(fl.GAME_ID) AS GP, -- Total games played
    -- Renamed fields
    AVG(fl.MINUTES) AS MPG,
    AVG(fl.USAGE) AS AVG_USG,
    AVG(fl.DK_POINTS) AS FPPG,
    AVG(fl.DK_SALARY) AS AVG_SAL,
    -- New calculated fields
    SUM(CASE WHEN fl.STARTED = 'Y' THEN 1 ELSE 0 END) AS GS, -- Games Started
    IFNULL(AVG(CASE WHEN fl.STARTED = 'Y' THEN fl.MINUTES ELSE NULL END), 0) AS AVG_MINS_GS, -- Average minutes in games started
    IFNULL(SUM(fl.DK_POINTS) / SUM(fl.MINUTES), 0) AS FPPM, -- Fantasy Points Per Minute (overall)
    IFNULL(SUM(CASE WHEN fl.STARTED = 'Y' THEN fl.DK_POINTS ELSE 0 END) / SUM(CASE WHEN fl.STARTED = 'Y' THEN fl.MINUTES ELSE NULL END), 0) AS FPPM_GS -- FPPM in games started
FROM
    fantasy_logs fl
LEFT JOIN
    dim_players dp ON fl.PLAYER_ID = dp."PLAYER ID"
LEFT JOIN
    map_teams mt ON fl.TEAM = mt.RAW_TEAM_NAME
GROUP BY
    dp.PLAYER_NAME, mt.TEAM_ABBREVIATION, fl.SEASON_SEGMENT;