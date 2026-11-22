from collections import defaultdict

from app.errors import InputError
from app.evidence import issue, key
from app.reasons import REASONS


def available_tips(previous):
    """按发布先后列出全部并行末版，最后一支为最新发布。"""
    tips = set(previous["versions"]["tips"])
    ordered = [row for row in previous["versions"]["versions"] if row["version"] in tips]
    return [row["version"] for row in sorted(ordered, key=lambda row: row["published_at"])]


def chosen_scope(data, tips):
    """读取本次采用的分支范围；未指定时默认收齐全部末版。"""
    raw = data.get("config", {}).get("signoff")
    requested = raw.get("scope") if isinstance(raw, dict) else raw
    if requested is None:
        return list(tips), False
    if not isinstance(requested, list) or not requested:
        raise InputError("BAD_SCOPE", "签核采用范围不能为空")
    picked = []
    for value in requested:
        try:
            name = key(value)
        except (KeyError, ValueError):
            raise InputError("BAD_SCOPE", "签核采用范围含无效分支")
        if name not in tips:
            raise InputError("BAD_SCOPE", f"分支 {name} 不是可用末版")
        if name not in picked:
            picked.append(name)
    return [tip for tip in tips if tip in picked], True


def unique(sources):
    seen, ordered = set(), []
    for source in sources:
        if not source:
            continue
        marker = (source.get("table"), source.get("line"))
        if marker not in seen:
            seen.add(marker)
            ordered.append(source)
    return ordered


def missing_code(leaf):
    if leaf is None:
        return "ANCHOR_UNRESOLVED"
    if leaf.get("state") == "deleted":
        return "ANCHOR_DELETED"
    if leaf.get("state") in ("invalid", "absent"):
        return "ANCHOR_UNRESOLVED"
    return "DECISION_MISSING"


def examine(opinion, anchors, scope_set):
    """按采用范围核对单份意见，返回结论、依据、缺失与冲突。"""
    scoped = [cell for cell in opinion["decisions"] if cell["tip"] in scope_set]
    omitted = [cell for cell in opinion["decisions"] if cell["tip"] not in scope_set]
    by_anchor = defaultdict(list)
    for cell in scoped:
        by_anchor[cell["anchor"]].append(cell)

    missing, conflicts = [], []
    for anchor in opinion["anchors"]:
        group = by_anchor.get(anchor, [])
        results = sorted({cell["result"] for cell in group if cell["result"]})
        if len(results) > 1:
            conflicts.append({"anchor": anchor, "results": results, "cells": group,
                              "sources": unique(source for cell in group for source in cell["sources"])})
        for cell in group:
            if cell["result"] is not None:
                continue
            leaf = next((row for row in anchors.get(anchor, {}).get("leaves", [])
                         if row["version"] == cell["tip"]), None)
            code = missing_code(leaf)
            sources = [*(cell.get("sources") or []), *( [leaf["source"]] if leaf and leaf.get("source") else [] )]
            missing.append({"anchor": anchor, "tip": cell["tip"], "code": code,
                            "reason": REASONS[code], "sources": unique(sources)})

    broad = sorted({cell["result"] for cell in scoped if cell["result"]})
    if len(broad) > 1 and not conflicts:
        conflicts.append({"anchor": None, "kind": "matrix", "results": broad, "cells": scoped,
                          "sources": unique(source for cell in scoped for source in cell["sources"])})

    if conflicts:
        status, conclusion = "conflict", None
    elif missing:
        status, conclusion = "missing", None
    elif broad:
        status, conclusion = "complete", broad[0]
    else:
        status, conclusion = "missing", None

    # 未纳入采用范围的分支仍可能在用；其结论若不在本次采用结论之内，作为冲突依据列出。
    omitted_basis = []
    for cell in omitted:
        divergent = cell["result"] is not None and (not broad or cell["result"] not in broad)
        omitted_basis.append({**cell, "divergent": divergent})
        if divergent:
            conflicts.append({"anchor": cell["anchor"], "kind": "omitted", "tip": cell["tip"],
                              "results": [*( [conclusion] if conclusion else broad ), cell["result"]],
                              "cells": [cell], "sources": unique(cell["sources"])})
    if any(row["divergent"] for row in omitted_basis):
        status, conclusion = "conflict", None

    active = [leaf for anchor in opinion["anchors"] for leaf in anchors.get(anchor, {}).get("leaves", [])
              if leaf["version"] in scope_set and leaf.get("state") == "active"]
    primary = min((leaf["origin"]["line"] for leaf in active), default=opinion["primary_line"])

    return {
        "id": opinion["id"], "speaker_id": opinion["speaker_id"], "speaker": opinion["speaker"],
        "topic": opinion["topic"], "position": opinion["position"], "anchors": opinion["anchors"],
        "primary_line": primary, "sources": opinion["sources"], "state": opinion["state"],
        "conclusion": conclusion, "status": status,
        "basis": [cell for cell in scoped if cell["result"] is not None],
        "missing": missing, "conflicts": conflicts, "omitted_basis": omitted_basis,
    }


def run(data, previous):
    tips = available_tips(previous)
    scope, explicit = chosen_scope(data, tips)
    scope_set = set(scope)
    anchors = {row["anchor"]: row for row in previous["revisions"]["anchors"]}
    issues = []
    items = []

    for opinion in previous["adoption"]["items"]:
        item = examine(opinion, anchors, scope_set)
        items.append(item)
        for conflict in item["conflicts"]:
            issues.append(issue("SIGNOFF_CONFLICT", *conflict["sources"]))
        for gap in item["missing"]:
            issues.append(issue(gap["code"], *gap["sources"]))

    omitted_tips = [tip for tip in tips if tip not in scope_set]
    omitted = []
    for tip in omitted_tips:
        divergent = [item for item in items for cell in item["omitted_basis"]
                     if cell["tip"] == tip and cell["divergent"]]
        sources = unique(source for item in divergent for cell in item["omitted_basis"]
                         if cell["tip"] == tip and cell["divergent"] for source in cell["sources"])
        omitted.append({"tip": tip, "divergent": [item["id"] for item in divergent], "sources": sources})
        if sources:
            issues.append(issue("SCOPE_OMITTED", *sources))

    aliases, attributed = {}, set()
    for item in items:
        for source in item["sources"]:
            attributed.add(source["line"])
            if item["status"] != "complete":
                aliases[source["line"]] = "disputed"
            elif source["line"] == item["primary_line"]:
                aliases[source["line"]] = "effective"
            else:
                aliases[source["line"]] = "repetition"

    coverage, residual = [], []
    for line, raw in enumerate(data["passages"], 1):
        source = {"table": "passages", "line": line, "raw": raw}
        category = aliases.get(line, "disputed")
        coverage.append({"line": line, "category": category, "source": source})
        if line not in attributed:
            residual.append({"line": line, "category": "disputed", "source": source})

    if residual:
        issues.append(issue("SIGNOFF_DISPUTED", *(row["source"] for row in residual)))

    counts = defaultdict(int)
    for item in items:
        counts[item["status"]] += 1
    total = {"input": len(data["passages"]), "effective": 0, "repetition": 0, "disputed": 0}
    for row in coverage:
        total[row["category"]] += 1
    total["difference"] = total["input"] - (total["effective"] + total["repetition"] + total["disputed"])

    # 意见缺依据、结论冲突或原始行尚未归属时，整卷停在待补。
    ready = not counts["conflict"] and not counts["missing"] and not residual
    return {
        "docket": previous["versions"]["docket"], "available_tips": tips, "scope": scope,
        "scope_explicit": explicit, "latest_tip": tips[-1] if tips else None,
        "omitted_tips": omitted_tips, "omitted": omitted,
        "status": "ready" if ready else "supplement", "label": "可交" if ready else "待补",
        "counts": {"opinions": len(items), "complete": counts["complete"],
                   "conflict": counts["conflict"], "missing": counts["missing"],
                   "residual": len(residual)},
        "items": items, "coverage": coverage, "totals": total, "residual": residual,
        "issues": issues,
    }
