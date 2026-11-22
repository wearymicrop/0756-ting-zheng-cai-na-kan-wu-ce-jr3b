from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.pipeline import calculate
from app.settings import PROJECT

router = APIRouter(prefix="/api/runs/{run_id}/signoff", tags=["采纳签核卷"])


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: list[str] | None = None


def with_scope(data, scope):
    """把本次采用的分支范围写入批次设置；原始输入仍保留在归档中。"""
    if scope is None:
        return data
    return {**data, "config": {**data["config"], "signoff": {"scope": list(scope)}}}


def compose(record, scope):
    """按采用范围重算，形成可交或待补的签核卷并附寄送草案。"""
    result = calculate(with_scope(record["input"], scope))
    signoff = result["signoff"]
    return {
        "docket": signoff["docket"], "scope": signoff["scope"],
        "scope_explicit": signoff["scope_explicit"], "available_tips": signoff["available_tips"],
        "omitted_tips": signoff["omitted_tips"], "omitted": signoff["omitted"],
        "status": signoff["status"], "label": signoff["label"], "counts": signoff["counts"],
        "items": signoff["items"], "totals": signoff["totals"], "residual": signoff["residual"],
        "issues": signoff["issues"], "mailings": result["mailings"],
        "input_sha256": record["manifest"]["input_sha256"],
        "rule_version": record["manifest"]["rule_version"],
    }


@router.get("")
def latest_volume(run_id: str, request: Request):
    request.app.state.archive.get(run_id)
    return {"run_id": run_id, "volume": request.app.state.archive.latest_volume(run_id)}


@router.get("/history")
def history(run_id: str, request: Request):
    request.app.state.archive.get(run_id)
    return {"run_id": run_id, "volumes": request.app.state.archive.volumes(run_id)}


@router.post("")
def sign_volume(run_id: str, body: Scope, request: Request):
    store = request.app.state.archive
    record = store.get(run_id)
    scope = body.scope if body.scope is not None else record["result"]["signoff"]["available_tips"]
    payload = compose(record, scope)
    return store.record_volume(run_id, payload["scope"], payload["status"], payload)


@router.get("/history/export")
def export_history(run_id: str, request: Request):
    store = request.app.state.archive
    store.get(run_id)
    return JSONResponse({"run_id": run_id, "volumes": store.volumes(run_id)}, headers={
        "Content-Disposition": f'attachment; filename="{PROJECT}-signoff-history-{run_id[:12]}.json"'
    })


@router.get("/{volume_id}")
def get_volume(run_id: str, volume_id: str, request: Request):
    request.app.state.archive.get(run_id)
    return request.app.state.archive.volume(run_id, volume_id)


@router.post("/{volume_id}/restore")
def restore_volume(run_id: str, volume_id: str, request: Request):
    return request.app.state.archive.restore_volume(run_id, volume_id)


@router.get("/{volume_id}/export")
def export_volume(run_id: str, volume_id: str, request: Request):
    volume = request.app.state.archive.volume(run_id, volume_id)
    return JSONResponse(volume, headers={
        "Content-Disposition": f'attachment; filename="{PROJECT}-signoff-{volume_id}.json"'
    })


@router.get("/{volume_id}/mailings")
def volume_mailings(run_id: str, volume_id: str, request: Request):
    """逐条核对签核状态：未签完的意见只能暂缓，不计入可寄送结果。"""
    volume = request.app.state.archive.volume(run_id, volume_id)
    mailings = volume.get("mailings") or {}
    drafts = mailings.get("drafts", [])
    signed = {item["opinion_id"]: item["signoff"] for draft in drafts for item in draft["items"]}
    for draft in drafts:
        if not all(item["signoff"] == "complete" for item in draft["items"]):
            draft["state"] = "held"
    ready = sum(draft["state"] == "ready" for draft in drafts)
    return {"volume": volume["id"], "signoff": volume["status"], "scope": volume["scope"],
            "sendable": volume["status"] == "ready", "ready": ready, "held": len(drafts) - ready,
            "drafts": drafts, "signed": signed, "issues": mailings.get("issues", [])}
