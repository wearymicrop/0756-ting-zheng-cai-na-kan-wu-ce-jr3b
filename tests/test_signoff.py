from app.pipeline import calculate


def test_clean_volume_is_ready(clean):
    """干净样例单支末版：每份意见都有适用依据，可交。"""
    signoff = clean["signoff"]
    assert signoff["status"] == "ready" and signoff["label"] == "可交"
    assert signoff["scope"] == ["V3"] and signoff["omitted_tips"] == []
    assert signoff["counts"] == {"opinions": 6, "complete": 6, "conflict": 0, "missing": 0, "residual": 0}


def test_clean_conclusions_use_latest_decision(clean):
    item = next(row for row in clean["signoff"]["items"] if row["topic"] == "排水沟")
    assert item["status"] == "complete" and item["conclusion"] == "accepted"
    assert [(cell["anchor"], cell["tip"], cell["decision_version"]) for cell in item["basis"]] == [("A-05", "V3", "V2")]


def test_full_scope_keeps_both_branches(dirty):
    """并行末版收齐后，冲突与缺失依据都可见。"""
    signoff = dirty["signoff"]
    assert signoff["scope"] == ["V3", "V3-B"] and signoff["status"] == "supplement"
    item = next(row for row in signoff["items"] if row["topic"] == "慢行入口")
    assert item["status"] == "conflict"
    assert {cell["result"] for cell in item["basis"]} == {"accepted", "rejected"}
    assert any(conflict["anchor"] == "A-01" for conflict in item["conflicts"])


def test_deleted_branch_is_missing_basis(dirty):
    item = next(row for row in dirty["signoff"]["items"] if row["topic"] == "绿带")
    assert item["status"] == "missing" and item["conclusion"] is None
    assert [(gap["anchor"], gap["tip"], gap["code"]) for gap in item["missing"]] == [("A-08", "V3-B", "ANCHOR_DELETED")]


def test_latest_only_lists_omitted_conflict(dirty_data):
    """只取最新一支时，另一支仍在用的相反结论必须列为冲突依据。"""
    dirty_data["config"]["signoff"] = {"scope": ["V3"]}
    signoff = calculate(dirty_data)["signoff"]
    assert signoff["omitted_tips"] == ["V3-B"]
    item = next(row for row in signoff["items"] if row["topic"] == "慢行入口")
    assert item["status"] == "conflict"
    omitted = [conflict for conflict in item["conflicts"] if conflict["kind"] == "omitted"]
    assert omitted and omitted[0]["tip"] == "V3-B" and omitted[0]["results"] == ["accepted", "rejected"]
    assert signoff["status"] == "supplement"
    assert any(row["tip"] == "V3-B" and row["divergent"] for row in signoff["omitted"])


def test_scope_cannot_name_non_tip(dirty_data):
    from app.errors import InputError

    dirty_data["config"]["signoff"] = {"scope": ["V2"]}
    try:
        calculate(dirty_data)
    except InputError as error:
        assert error.code == "BAD_SCOPE"
    else:
        raise AssertionError("非末版不应作为采用范围")


def test_supplement_holds_sendable_records(dirty):
    assert dirty["signoff"]["status"] == "supplement"
    assert dirty["mailings"]["ready"] == 2
    ready = {draft["id"] for draft in dirty["mailings"]["drafts"] if draft["state"] == "ready"}
    assert ready == {"P003", "P004"}


def test_clean_mailings_reference_scope(clean):
    assert clean["mailings"]["scope"] == ["V3"]
    assert clean["mailings"]["ready"] == 5
