-- SQLite
-- This query calculates and compares player stats for the Atlanta Hawks ('ATL')
-- on or after '2025-10-31'. It provides two sets of metrics for each player,
-- and calculates the difference in performance between the two scenarios.
-- 1. Averages for games on dates when 'Kristaps Porzingis' also played.
-- 2. Averages for games on dates when 'Kristaps Porzingis' did NOT play.

WITH KpPlayerId AS (
    -- Robustly find the Player ID for Kristaps Porzingis from the dimension table.
    -- This avoids issues with name variations in the raw logs.
    SELECT PLAYER_ID
    FROM dim_players
    WHERE PLAYER_NAME = 'LeBron James'
),
KpGameDates AS (
    -- Using the ID from the CTE above, get a distinct list of dates Kristaps Porzingis played.
    SELECT DISTINCT DATE
    FROM fantasy_logs
    WHERE PLAYER_ID = (SELECT PLAYER_ID FROM KpPlayerId)
      AND DATE >= '2025-10-21'
),
PlayerStats AS (
    -- Second, calculate the aggregated stats for each player in both scenarios.
    SELECT
        fl.PLAYER,
        mt.TEAM_ABBREVIATION as TEAM,

        -- Games Played in each scenario
        COUNT(CASE WHEN fl.DATE IN KpGameDates THEN fl.GAME_ID END) as GP_w_KP,
        COUNT(CASE WHEN fl.DATE NOT IN KpGameDates THEN fl.GAME_ID END) as GP_no_KP,

        -- Averages for games ON dates Kristaps Porzingis played
        ROUND(SUM(CASE WHEN fl.DATE IN KpGameDates THEN fl.DK_POINTS ELSE 0 END) / NULLIF(COUNT(CASE WHEN fl.DATE IN KpGameDates THEN fl.GAME_ID END), 0), 2) as DKPPG_w_KP,
        ROUND(SUM(CASE WHEN fl.DATE IN KpGameDates THEN fl.MINUTES ELSE 0 END) / NULLIF(COUNT(CASE WHEN fl.DATE IN KpGameDates THEN fl.GAME_ID END), 0), 1) as MPG_w_KP,
        ROUND(SUM(CASE WHEN fl.DATE IN KpGameDates THEN fl.DK_POINTS ELSE 0 END) / NULLIF(SUM(CASE WHEN fl.DATE IN KpGameDates THEN fl.MINUTES END), 0), 2) as FPPM_w_KP,

        -- Averages for games ON dates Kristaps Porzingis did NOT play
        ROUND(SUM(CASE WHEN fl.DATE NOT IN KpGameDates THEN fl.DK_POINTS ELSE 0 END) / NULLIF(COUNT(CASE WHEN fl.DATE NOT IN KpGameDates THEN fl.GAME_ID END), 0), 2) as DKPPG_no_KP,
        ROUND(SUM(CASE WHEN fl.DATE NOT IN KpGameDates THEN fl.MINUTES ELSE 0 END) / NULLIF(COUNT(CASE WHEN fl.DATE NOT IN KpGameDates THEN fl.GAME_ID END), 0), 1) as MPG_no_KP,
        ROUND(SUM(CASE WHEN fl.DATE NOT IN KpGameDates THEN fl.DK_POINTS ELSE 0 END) / NULLIF(SUM(CASE WHEN fl.DATE NOT IN KpGameDates THEN fl.MINUTES END), 0), 2) as FPPM_no_KP

    FROM fantasy_logs fl
    LEFT JOIN map_teams mt ON fl.TEAM = mt.RAW_TEAM_NAME
    WHERE fl.DATE >= '2025-10-21'
      AND mt.TEAM_ABBREVIATION = 'LAL'
      AND fl.PLAYER_ID != (SELECT PLAYER_ID FROM KpPlayerId) -- Exclude Kristaps Porzingis by ID
    GROUP BY
        fl.PLAYER,
        mt.TEAM_ABBREVIATION
    HAVING
        -- Only include players who average at least 5 DKPPG in BOTH scenarios
        DKPPG_w_KP >= 5 AND DKPPG_no_KP >= 5
)
SELECT
    PLAYER,
    TEAM,
    GP_w_KP,
    DKPPG_w_KP,
    GP_no_KP,
    --DKPPG_no_KP,
    FPPM_w_KP,
    FPPM_no_KP,
    -- Calculate the difference in DKPPG. A positive number means the player scores more WITH Porzingis.
    --ROUND(DKPPG_w_KP - DKPPG_no_KP, 2) AS DKPPG_DIFF,
    -- Calculate the difference in FPPM. A positive number means the player is more efficient WITH Porzingis.
    ROUND(FPPM_w_KP - FPPM_no_KP, 2) AS FPPM_DIFF
FROM PlayerStats
ORDER BY
    DKPPG_no_KP DESC;