from app.store import Archive


def test_signoff_reuses_original_batch(client):
    record = client.post("/api/runs", json={"sample": "dirty"}).json()
    first = client.post(f"/api/runs/{record['id']}/signoff", json={}).json()
    again = client.post(f"/api/runs/{record['id']}/signoff", json={}).json()
    assert first["reused"] is False and again["reused"] is True
    assert first["id"] == again["id"]
    history = client.get(f"/api/runs/{record['id']}/signoff/history").json()["volumes"]
    assert len(history) == 1
    assert first["scope"] == ["V3", "V3-B"] and first["status"] == "supplement"


def test_changed_scope_adds_one_revision(client):
    record = client.post("/api/runs", json={"sample": "dirty"}).json()
    first = client.post(f"/api/runs/{record['id']}/signoff", json={}).json()
    second = client.post(f"/api/runs/{record['id']}/signoff", json={"scope": ["V3"]}).json()
    assert second["revision"] == first["revision"] + 1
    assert second["parent"] == first["id"]
    assert second["scope"] == ["V3"]


def test_restore_keeps_old_basis_and_input(client):
    record = client.post("/api/runs", json={"sample": "dirty"}).json()
    full = client.post(f"/api/runs/{record['id']}/signoff", json={}).json()
    client.post(f"/api/runs/{record['id']}/signoff", json={"scope": ["V3"]})
    restored = client.post(f"/api/runs/{record['id']}/signoff/{full['id']}/restore").json()
    assert restored["restored_from"] == full["id"]
    assert restored["scope"] == full["scope"] and restored["status"] == full["status"]
    assert restored["items"] == full["items"]
    assert client.get(f"/api/runs/{record['id']}/signoff/{full['id']}").json()["id"] == full["id"]
    assert client.get(f"/api/runs/{record['id']}").json()["input"] == record["input"]


def test_missing_revision_and_scope_errors(client):
    record = client.post("/api/runs", json={"sample": "clean"}).json()
    assert client.get(f"/api/runs/{record['id']}/signoff/unknown").status_code == 404
    assert client.post(f"/api/runs/{record['id']}/signoff", json={"scope": []}).json()["code"] == "BAD_SCOPE"
    assert client.post(f"/api/runs/{record['id']}/signoff", json={"scope": ["V9"]}).json()["code"] == "BAD_SCOPE"


def test_supplement_mailings_never_sendable(client):
    record = client.post("/api/runs", json={"sample": "dirty"}).json()
    volume = client.post(f"/api/runs/{record['id']}/signoff", json={"scope": ["V3"]}).json()
    assert volume["status"] == "supplement"
    mailings = client.get(f"/api/runs/{record['id']}/signoff/{volume['id']}/mailings").json()
    assert mailings["sendable"] is False
    # 签核未完成的意见所在收件人一律暂缓，即便地址有效。
    unsignable = {draft["id"] for draft in mailings["drafts"]
                  if any(item["signoff"] != "complete" for item in draft["items"])}
    assert unsignable == {"P001"}
    assert all(draft["state"] == "held" for draft in mailings["drafts"] if draft["id"] in unsignable)
    # 签核完成的记录可以进入可寄送结果。
    assert {draft["id"] for draft in mailings["drafts"] if draft["state"] == "ready"} == {"P002", "P003", "P004"}


def test_ready_volume_exports_sendable(client):
    record = client.post("/api/runs", json={"sample": "clean"}).json()
    volume = client.post(f"/api/runs/{record['id']}/signoff", json={}).json()
    mailings = client.get(f"/api/runs/{record['id']}/signoff/{volume['id']}/mailings").json()
    assert mailings["signoff"] == "ready" and mailings["sendable"] is True
    assert mailings["ready"] == 5 and mailings["held"] == 0


def test_volume_export_keeps_original_lines(client):
    record = client.post("/api/runs", json={"sample": "dirty"}).json()
    volume = client.post(f"/api/runs/{record['id']}/signoff", json={}).json()
    attachment = client.get(f"/api/runs/{record['id']}/signoff/{volume['id']}/export")
    assert attachment.headers["content-disposition"].startswith("attachment;")
    exported = attachment.json()
    assert exported["input_sha256"] == record["manifest"]["input_sha256"]
    item = next(row for row in exported["items"] if row["topic"] == "慢行入口")
    decision_lines = {source["line"] for cell in item["basis"] for source in cell["sources"]}
    assert all(source["table"] == "decisions" for cell in item["basis"] for source in cell["sources"])
    assert {1, 2, 10} <= decision_lines
    # 原始段落依据仍按原行号保留在卷内。
    passage_lines = {source["line"] for source in item["sources"]}
    assert {1, 2, 9, 10, 13, 17} <= passage_lines
    history = client.get(f"/api/runs/{record['id']}/signoff/history/export")
    assert history.status_code == 200 and history.json()["volumes"][0]["id"] == volume["id"]


def test_concurrent_same_batch_commits_once(client):
    from concurrent.futures import ThreadPoolExecutor

    record = client.post("/api/runs", json={"sample": "clean"}).json()

    def sign(_):
        return client.post(f"/api/runs/{record['id']}/signoff", json={}).json()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(sign, range(8)))
    assert len({volume["id"] for volume in results}) == 1
    assert sum(not volume["reused"] for volume in results) == 1
    assert len(client.get(f"/api/runs/{record['id']}/signoff/history").json()["volumes"]) == 1


def test_rerun_same_batch_keeps_volume(tmp_path):
    from pathlib import Path
    from fastapi.testclient import TestClient

    from app.main import create_app

    path = Path(tmp_path) / "archive.sqlite3"
    archive = Archive(path)
    with TestClient(create_app(path)) as client:
        record = client.post("/api/runs", json={"sample": "clean"}).json()
        volume = client.post(f"/api/runs/{record['id']}/signoff", json={}).json()
        client.post(f"/api/runs/{record['id']}/rerun")
        again = client.post(f"/api/runs/{record['id']}/signoff", json={}).json()
        assert again["id"] == volume["id"] and again["reused"] is True
    assert len(archive.volumes(record["id"])) == 1
