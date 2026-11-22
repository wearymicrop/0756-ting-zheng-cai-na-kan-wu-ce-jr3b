from fastapi import APIRouter
from app.samples import load_sample


def apply_scope(data, scope):
    if scope:
        data["config"]["signoff"] = {"scope": [value.strip() for value in scope.split(",") if value.strip()]}


def stage_router(name, caption):
    router = APIRouter(prefix=f"/api/{name}", tags=[caption])

    @router.get("/{sample}", name=name)
    def inspect(sample: str, scope: str | None = None):
        from app.pipeline import calculate

        data = load_sample(sample)
        apply_scope(data, scope)
        return calculate(data, until=name)[name]

    return router
