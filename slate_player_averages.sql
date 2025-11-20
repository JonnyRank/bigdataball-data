-- SQLite
select SEASON, PLAYER, TEAM, GP, GS, MPG, GSMPG, FPPG, GSFPPG, FPPM, GSFPPM, STDV_FPPG as STDV
from vw_player_averages_regular_season
where SEASON in ('2024-25', '2025-26')
and (TEAM in ('LAC', 'ORL', 'ATL', 'SAS', 'SAC', 'MEM', 'PHI', 'MIL')
or PLAYER in ('John Collins', 'Bogdan Bogdanovic', 'Cole Anthony', 'Precious Achiuwa', 'De''Aaron Fox',
'Luke Kornet', 'Kelly Olynyk'))
order by TEAM, PLAYER, SEASON desc;
