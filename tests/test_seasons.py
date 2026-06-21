import seasons


def test_slate_seasons_sql_renders_quoted_csv(monkeypatch):
    monkeypatch.setattr(seasons, "SLATE_SEASONS", ("2000-01", "2001-02"))
    assert seasons.slate_seasons_sql() == "'2000-01', '2001-02'"


def test_constants_have_expected_shapes():
    assert isinstance(seasons.SLATE_SEASONS, tuple) and len(seasons.SLATE_SEASONS) >= 1
    assert "-" in seasons.L30_SEASON          # regular-season form 'YYYY-YY'
    assert seasons.PLAYOFFS_SEASON.isdigit()  # playoff year 'YYYY'
