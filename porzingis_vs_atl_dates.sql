-- SQLite
-- This query calculates and compares player stats for the Atlanta Hawks ('ATL')
-- on or after '2025-10-31'. It provides two sets of metrics for each player,
-- and calculates the difference in performance between the two scenarios.
-- 1. Averages for games on dates when Bam Adebayo OR Tyler Herro played.
-- 2. Averages for games on dates when BOTH Bam Adebayo AND Tyler Herro were OUT.

WITH TargetPlayerIds AS (
    -- Robustly find the Player IDs for Bam and Tyler from the dimension table.
    -- This avoids issues with name variations in the raw logs.
    SELECT PLAYER_ID
    FROM dim_players
    WHERE PLAYER_NAME IN ('Stephen Curry', 'Jimmy Butler')
),
TargetGameDates AS (
    -- Get a distinct list of dates where AT LEAST ONE of the target players played.
    SELECT DISTINCT DATE
    FROM fantasy_logs
    WHERE PLAYER_ID IN (SELECT PLAYER_ID FROM TargetPlayerIds)
      AND DATE >= '2025-10-21'
),
PlayerStats AS (
    -- Second, calculate the aggregated stats for each player in both scenarios.
    SELECT
        fl.PLAYER,
        mt.TEAM_ABBREVIATION as TEAM,

        -- Games Played in each scenario
        COUNT(CASE WHEN fl.DATE IN TargetGameDates THEN fl.GAME_ID END) as GP_W_Booker,
        COUNT(CASE WHEN fl.DATE NOT IN TargetGameDates THEN fl.GAME_ID END) as GP_WO_Booker,

        -- Averages for games ON dates where at least one played
        ROUND(SUM(CASE WHEN fl.DATE IN TargetGameDates THEN fl.DK_POINTS ELSE 0 END) / NULLIF(COUNT(CASE WHEN fl.DATE IN TargetGameDates THEN fl.GAME_ID END), 0), 2) as DKPPG_With_Any,
        ROUND(SUM(CASE WHEN fl.DATE IN TargetGameDates THEN fl.MINUTES ELSE 0 END) / NULLIF(COUNT(CASE WHEN fl.DATE IN TargetGameDates THEN fl.GAME_ID END), 0), 1) as MPG_With_Any,
        ROUND(SUM(CASE WHEN fl.DATE IN TargetGameDates THEN fl.DK_POINTS ELSE 0 END) / NULLIF(SUM(CASE WHEN fl.DATE IN TargetGameDates THEN fl.MINUTES END), 0), 2) as FPPM_W_Booker,

        -- Averages for games ON dates where BOTH were OUT
        ROUND(SUM(CASE WHEN fl.DATE NOT IN TargetGameDates THEN fl.DK_POINTS ELSE 0 END) / NULLIF(COUNT(CASE WHEN fl.DATE NOT IN TargetGameDates THEN fl.GAME_ID END), 0), 2) as DKPPG_Both_Out,
        ROUND(SUM(CASE WHEN fl.DATE NOT IN TargetGameDates THEN fl.MINUTES ELSE 0 END) / NULLIF(COUNT(CASE WHEN fl.DATE NOT IN TargetGameDates THEN fl.GAME_ID END), 0), 1) as MPG_Both_Out,
        ROUND(SUM(CASE WHEN fl.DATE NOT IN TargetGameDates THEN fl.DK_POINTS ELSE 0 END) / NULLIF(SUM(CASE WHEN fl.DATE NOT IN TargetGameDates THEN fl.MINUTES END), 0), 2) as FPPM_WO_Booker

    FROM fantasy_logs fl
    LEFT JOIN map_teams mt ON fl.TEAM = mt.RAW_TEAM_NAME
    WHERE fl.DATE >= '2025-10-21'
      AND mt.TEAM_ABBREVIATION = 'GSW'
      AND fl.PLAYER_ID NOT IN (SELECT PLAYER_ID FROM TargetPlayerIds) -- Exclude the stars themselves
    GROUP BY
        fl.PLAYER,
        mt.TEAM_ABBREVIATION
    HAVING
        -- Only include players who played at least once when both were out
        GP_WO_Booker > 0
        and DKPPG_Both_Out > 10
)
SELECT
    PLAYER,
    TEAM,
    GP_W_Booker,
    --DKPPG_With_Any,
    GP_WO_Booker,
    --DKPPG_Both_Out,
    FPPM_W_Booker,
    FPPM_WO_Booker,
    -- Calculate the difference in FPPM. Positive number means they are better when stars are OUT.
    ROUND(FPPM_WO_Booker - FPPM_W_Booker, 2) AS FPPM_DIFF
FROM PlayerStats
ORDER BY
    FPPM_DIFF DESC;