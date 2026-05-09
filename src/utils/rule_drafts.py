import json
from pathlib import Path


def get_rule_drafts_path():
    return Path(__file__).resolve().parents[2] / "data" / "rules" / "rule_drafts.json"


def load_rule_drafts(path=None):
    draft_path = Path(path) if path is not None else get_rule_drafts_path()
    if not draft_path.exists():
        return []

    try:
        return json.loads(draft_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_rule_drafts(path=None, drafts=None):
    draft_path = Path(path) if path is not None else get_rule_drafts_path()
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    payload = drafts or []
    draft_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_rule_drafts(path=None, drafts=None):
    draft_path = Path(path) if path is not None else get_rule_drafts_path()
    existing = load_rule_drafts(draft_path)
    existing_ids = {item.get("draft_id") for item in existing}

    for draft in drafts or []:
        draft_id = draft.get("draft_id")
        if not draft_id or draft_id in existing_ids:
            continue
        existing.append(draft)
        existing_ids.add(draft_id)

    save_rule_drafts(draft_path, existing)
    return existing


def get_pending_rule_drafts(path=None):
    drafts = load_rule_drafts(path)
    return [draft for draft in drafts if draft.get("status", "draft") == "draft"]


def update_rule_draft_status(draft_id, status, path=None):
    drafts = load_rule_drafts(path)
    changed = False
    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            draft["status"] = status
            changed = True
            break

    if changed:
        save_rule_drafts(path, drafts)
    return changed


def delete_rule_draft(draft_id, path=None):
    drafts = load_rule_drafts(path)
    updated_drafts = [draft for draft in drafts if draft.get("draft_id") != draft_id]
    changed = len(updated_drafts) != len(drafts)

    if changed:
        save_rule_drafts(path, updated_drafts)

    return changed
