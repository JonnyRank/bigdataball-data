-- SQLite
select SEASON, PLAYER, TEAM, GP, GS, MPG, GSMPG, FPPG, GSFPPG, FPPM, GSFPPM, STDV_FPPG as STDV
from vw_player_averages_regular_season
where SEASON in ('2024-25', '2025-26')
and (TEAM in ('ATL', 'NOP', 'WAS', 'CHI', 'DET', 'MIL', 'MEM', 'DAL')
or PLAYER in ('Kristaps Porzingis', 'D''Angelo Russell', 'Duncan Robinson', 'Cole Anthony', 
'CJ McCollum', 'Cam Whitmore'))
order by TEAM, PLAYER, SEASON desc;
