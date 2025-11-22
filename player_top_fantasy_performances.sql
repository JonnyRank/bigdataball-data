-- SQLite
select
PLAYER,
DATE,
TEAM,
STARTED,
CAST(round(DK_SALARY, 0) AS INTEGER) as SALARY,
DK_POINTS as FPTS,
round(MINUTES, 1) as MINS,
round((DK_POINTS / MINUTES), 2) as FPPM,
round(USAGE, 1) as USG
from fantasy_logs
where Player = 'Simone Fontecchio'
ORDER by DK_POINTS desc