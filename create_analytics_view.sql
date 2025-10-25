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
    COUNT(fl.GAME_ID) AS GAMES_PLAYED,
    AVG(fl.MINUTES) AS AVG_MINUTES,
    AVG(fl.USAGE) AS AVG_USAGE,
    AVG(fl.DK_POINTS) AS AVG_DK_POINTS,
    AVG(fl.DK_SALARY) AS AVG_DK_SALARY
FROM
    fantasy_logs fl
LEFT JOIN
    dim_players dp ON fl.PLAYER_ID = dp."PLAYER ID"
LEFT JOIN
    map_teams mt ON fl.TEAM = mt.RAW_TEAM_NAME
GROUP BY
    dp.PLAYER_NAME, mt.TEAM_ABBREVIATION, fl.SEASON_SEGMENT;