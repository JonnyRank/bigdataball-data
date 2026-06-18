import os

import pytest


def test_unmatched_uses_regular_season_not_playoffs(fantasy_upload, monkeypatch):
    """Regression: the email warning and todo_mappings worklist must reflect the
    regular-season slate only, not playoffs results."""
    mod = fantasy_upload
    sent = {}

    # Stub heavy stages not already handled by the fantasy_upload fixture.
    monkeypatch.setattr(mod.daily_player_upload, "main", lambda: (0, 0))
    monkeypatch.setattr(mod.create_summary_tables, "run_summary_pipeline", lambda: None)
    monkeypatch.setattr(
        mod.export_slate_averages_csv, "run_slate_averages_smart_export", lambda: None
    )
    monkeypatch.setattr(
        mod.export_slate_averages_vw,
        "run_slate_averages_pipeline",
        lambda: ["RegOnly Player (Best match: X, Score: 50)"],
    )
    monkeypatch.setattr(
        mod.export_playoffs_slate_averages_vw,
        "run_playoffs_slate_averages_pipeline",
        lambda: ["PlayoffOnly Player (Best match: Y, Score: 50)"],
    )

    def fake_send(subject, body):
        sent["subject"] = subject
        sent["body"] = body

    monkeypatch.setattr(mod.email_notifier, "send_email_alert", fake_send)

    mod.main()

    # Success branch must have fired (no pipeline errors).
    assert "subject" in sent, "email was never sent — check for pipeline errors above"
    assert "ERRORS" not in sent["subject"], f"pipeline hit error branch: {sent['subject']}"

    # Email body must contain the regular-season player, not the playoffs one.
    assert "RegOnly Player" in sent["body"]
    assert "PlayoffOnly Player" not in sent["body"]

    # todo_mappings.txt must contain the regular-season name, not the playoffs one.
    todo_path = os.path.join(mod.BASE_DATA_PATH, "todo_mappings.txt")
    assert os.path.exists(todo_path)
    with open(todo_path, encoding="utf-8") as f:
        todo = f.read()
    assert "RegOnly Player" in todo
    assert "PlayoffOnly Player" not in todo
