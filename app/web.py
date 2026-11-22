from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.contract import HOME, STAGES
from app.errors import InputError
from app.manifest import sha256
from app.pipeline import calculate
from app.samples import SAMPLE_NAMES, load_sample
from app.settings import ROOT, RULE_VERSION, TITLE
from app.stage_api import apply_scope

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(ROOT / "app/templates"))
templates.env.autoescape = True


@router.get("/")
@router.get("/work/{stage}")
def workbench(request: Request, stage: str = HOME, sample: str = "clean", scope: str | None = None,
              run: str | None = None):
    titles = {name: caption for name, caption, _, _ in STAGES}
    if stage not in titles:
        raise InputError("UNKNOWN_STAGE", "找不到该业务页面", 404)
    data = load_sample(sample)
    apply_scope(data, scope)
    result = calculate(data)
    volume = request.app.state.archive.latest_volume(run) if run else None
    return templates.TemplateResponse(request=request, name="workbench.html", context={
        "project": TITLE, "titles": titles, "stage": stage, "sample": sample,
        "samples": SAMPLE_NAMES, "result": result, "current": result[stage],
        "rule_version": RULE_VERSION, "input_ref": sha256(data)[:10],
        "scope": scope or "", "run_id": run, "volume": volume,
    })
