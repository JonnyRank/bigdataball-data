-- SQLite
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
        player_logs
    WHERE
        SEASON_SEGMENT LIKE '%Regular Season%' OR SEASON_SEGMENT LIKE '%In-Season Tournament%'
)
SELECT
    lws.SEASON_KEY AS SEASON,
    dp.PLAYER_NAME AS PLAYER,
    mt.TEAM_ABBREVIATION AS TEAM,
    lws.VENUE,
    COUNT(lws.GAME_ID) AS GP,
    ROUND(AVG(lws.AST), 1) AS APG
FROM
    logs_with_season lws
LEFT JOIN dim_players dp ON lws.PLAYER_ID = dp.PLAYER_ID
LEFT JOIN map_teams mt ON lws.TEAM = mt.RAW_TEAM_NAME
WHERE
    dp.PLAYER_NAME = 'Nikola Jokic'
GROUP BY
    SEASON, VENUE
ORDER BY
    SEASON DESC;