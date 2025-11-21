-- SQLite
select SEASON, PLAYER, TEAM, GP, GS, MPG, GSMPG, FPPG, GSFPPG, FPPM, GSFPPM, STDV_FPPG as STDV
from vw_player_averages_regular_season
where SEASON in ('2024-25', '2025-26')
and (TEAM in ('IND', 'CLE', 'BKN', 'BOS', 'WAS', 'TOR', 'MIA', 'CHI', 
'NOP', 'DAL', 'MIN', 'PHX', 'DEN', 'HOU')
or PLAYER in ('Anfernee Simons', 'Josh Minott', 'Luka Garza', 'De''Andre Hunter', 'D''Angelo Russell', 
'Cameron Johnson', 'Kevin Durant', 'Jay Huff', 'Jeremiah Robinson-Earl', 'Norman Powell', 'Simone Fontecchio', 
'Dillon Brooks', 'Jordan Goodwin', 'Mark Williams', 'Sandro Mamukelashvili', 'CJ McCollum', 'Khris Middleton', 
'Cam Whitmore'))
order by TEAM, PLAYER, SEASON desc;
