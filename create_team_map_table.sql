-- SQLite
-- Create table to convert full team name to abbreviation
CREATE TABLE map_teams (
    RAW_TEAM_NAME TEXT PRIMARY KEY,
    TEAM_ABBREVIATION TEXT NOT NULL
);

/* Run this for all 30 teams */
INSERT INTO map_teams (RAW_TEAM_NAME, TEAM_ABBREVIATION)
VALUES
    ('Atlanta', 'ATL'),
    ('Boston', 'BOS'),
    ('Brooklyn', 'BKN'),
    ('Charlotte', 'CHA'),
    ('Chicago', 'CHI'),
    ('Cleveland', 'CLE'),
    ('Dallas', 'DAL'),
    ('Denver', 'DEN'),
    ('Detroit', 'DET'),
    ('Golden State', 'GSW'),
    ('Houston', 'HOU'),
    ('Indiana', 'IND'),
    ('LA Clippers', 'LAC'),
    ('LA Lakers', 'LAL'),
    ('Memphis', 'MEM'),
    ('Miami', 'MIA'),
    ('Milwaukee', 'MIL'),
    ('Minnesota', 'MIN'),
    ('New Orleans', 'NOP'),
    ('New York', 'NYK'),
    ('Oklahoma City', 'OKC'),
    ('Orlando', 'ORL'),
    ('Philadelphia', 'PHI'),
    ('Phoenix', 'PHX'),
    ('Portland', 'POR'),
    ('Sacramento', 'SAC'),
    ('San Antonio', 'SAS'),
    ('Toronto', 'TOR'),
    ('Utah', 'UTA'),
    ('Washington', 'WAS');