-- SQLite
select SEASON, PLAYER, TEAM, GP, GS, MPG, GSMPG, FPPG, GSFPPG, FPPM, GSFPPM, STDV_FPPG as STDV
from vw_player_averages_regular_season
where (SEASON = '2024-25' and GP > 20) or SEASON = '2025-26'
and (TEAM in ('CHA', 'ATL', 'BKN', 'TOR', 'ORL', 'LAC', 'CLE', 'POR', 'OKC', 
'LAL', 'UTA', 'SAS', 'PHX')
or PLAYER in ('Anfernee Simons', 'Luka Garza', 'Collin Sexton', 'De''Andre Hunter', 'Larry Nance Jr.', 
'John Collins', 'Bogdan Bogdanovic', 'Chris Paul', 'Brook Lopez', 'Deandre Ayton', 'Desmond Bane', 
'Dillon Brooks', 'Mark Williams', 'Jordan Goodwin', 'Nick Richards', 'De''Aaron Fox', 'Luke Kornet', 
'Kelly Olynyk', 'Sandro Mamukelashvili', 'Jusuf Nurkic', 'Kevin Love'))
order by TEAM, PLAYER, SEASON desc;
