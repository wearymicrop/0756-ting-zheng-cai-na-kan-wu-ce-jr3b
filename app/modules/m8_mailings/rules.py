import re
from collections import defaultdict

from app.evidence import issue

ADDRESS = re.compile(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+")


def corrections_for(opinion, anchors, scope_set):
    corrections = []
    for name in opinion["anchors"]:
        record = anchors[name]
        original = next((row for row in record["history"] if row["op"] == "upsert" and row["state"] == "active"), None)
        if original is None:
            continue
        for leaf in record["leaves"]:
            if leaf["version"] not in scope_set:
                continue
            if leaf["page"] != original["page"] or record["status"] != "stable":
                corrections.append({"anchor": name, "original_page": original["page"], "current_page": leaf["page"],
                                    "version": leaf["version"], "state": leaf["state"],
                                    "sources": [original["sources"][0], *([leaf["source"]] if "source" in leaf else [])]})
    return corrections


def run(_data, previous):
    people = previous["speakers"]["people"]
    anchors = {row["anchor"]: row for row in previous["revisions"]["anchors"]}
    signoff = previous["signoff"]
    scope_set = set(signoff["scope"])
    grouped, issues = defaultdict(list), []
    for opinion in signoff["items"]:
        corrections = corrections_for(opinion, anchors, scope_set) if opinion["status"] == "complete" else []
        grouped[opinion["speaker_id"]].append({"opinion_id": opinion["id"], "topic": opinion["topic"],
                                               "verdict": opinion["conclusion"],
                                               "signoff": opinion["status"],
                                               "corrections": corrections})
    drafts = []
    for identifier, items in sorted(grouped.items()):
        person = people[identifier]
        address = person["contact"]
        valid = bool(address and ADDRESS.fullmatch(address))
        if not valid:
            issues.append(issue("CONTACT_MISSING", person["source"]))
        signed = all(item["signoff"] == "complete" for item in items)
        state = "ready" if valid and signed else "held"
        drafts.append({"id": identifier, "speaker": person["name"], "address": address, "state": state,
                       "items": items, "source": person["source"]})
    total = len(drafts)
    ready = sum(row["state"] == "ready" for row in drafts)
    return {"drafts": drafts, "ready": ready, "held": total - ready,
            "corrections": sum(len(item["corrections"]) for row in drafts for item in row["items"]),
            "scope": signoff["scope"], "signoff_status": signoff["status"], "issues": issues}
