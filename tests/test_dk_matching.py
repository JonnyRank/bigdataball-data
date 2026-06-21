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


def test_dedup_same_db_name():
    # Two DK names that both fuzzy-match the same DB name should yield one result.
    matched, unmatched = dk_matching.match_names(
        ["LeBron James", "Lebron James"], ["LeBron James"]
    )
    assert matched == ["LeBron James"]
    assert unmatched == []


def test_threshold_boundary():
    # Score exactly at threshold (90) should match; a completely alien name should not.
    matched_exact, _ = dk_matching.match_names(["LeBron James"], ["LeBron James"])
    assert "LeBron James" in matched_exact

    matched_miss, unmatched_miss = dk_matching.match_names(["Zzqx Xvbq"], ["LeBron James"])
    assert matched_miss == []
    assert len(unmatched_miss) == 1


def test_non_string_and_whitespace_in_dk_names():
    # None is dropped; int is coerced to str and goes unmatched; padded name matches.
    matched, unmatched = dk_matching.match_names(
        [" LeBron James ", 123, None], ["LeBron James"]
    )
    assert matched == ["LeBron James"]
    assert len(unmatched) == 1
    assert "123" in unmatched[0]
