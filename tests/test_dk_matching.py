import dk_matching


def test_exact_match_is_kept():
    matched, unmatched = dk_matching.match_names(["LeBron James"], ["LeBron James", "Stephen Curry"])
    assert matched == ["LeBron James"]
    assert unmatched == []


def test_mapping_applied_before_fuzzy():
    # mappings.PLAYER_NAME_MAP maps "GG Jackson" -> "Gregory Jackson"
    matched, unmatched = dk_matching.match_names(["GG Jackson"], ["Gregory Jackson"])
    assert matched == ["Gregory Jackson"]
    assert unmatched == []


def test_below_threshold_is_unmatched():
    matched, unmatched = dk_matching.match_names(["Zzqx Nobody"], ["LeBron James"])
    assert matched == []
    assert len(unmatched) == 1
    assert "Zzqx Nobody" in unmatched[0]


def test_empty_db_list_does_not_crash():
    # On a fresh DB / out-of-season view the choice list is empty; must not raise.
    matched, unmatched = dk_matching.match_names(["LeBron James"], [])
    assert matched == []
    assert len(unmatched) == 1
    assert "LeBron James" in unmatched[0]


def test_sql_in_list_escapes_quotes():
    assert dk_matching.to_sql_in_list(["O'Neal", "Curry"]) == "O''Neal', 'Curry"
