-- SQLite
select
--fl.SEASON_SEGMENT,
fl.DATE,
fl.PLAYER,
mt.TEAM_ABBREVIATION as TEAM,
fl.OPPONENT,
fl.STARTED,
CAST(round(DK_SALARY, 0) AS INTEGER) as SALARY,
DK_POINTS as DKPTS,
round(fl.MINUTES, 1) as MINS,
pl.PTS,
pl.TREB as REB,
pl.AST,
pl.STL,
pl.BLK,
pl.TOV,
pl.PF,
pl.FG,
pl.FGA,
pl."3P" as "3P",
pl."3PA" as "3PA",
pl.FT,
pl.FTA,
round(fl.USAGE, 1) as USG
from fantasy_logs fl
LEFT JOIN player_logs pl ON fl.PLAYER_ID = pl.PLAYER_ID AND fl.GAME_ID = pl.GAME_ID
LEFT JOIN map_teams mt ON fl.TEAM = mt.RAW_TEAM_NAME
where fl.Player = 'Keyonte George'
--and fl.SEASON_SEGMENT = 'NBA 2025-2026 Regular Season'
--and fl.DATE >= '2025-11-01'
--AND DKPTS >= 15
ORDER by DKPTS DESC;
--order by fl.DATE DESC;