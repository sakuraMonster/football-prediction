import json
import re
from pathlib import Path


def get_rules_base_dir():
    return Path(__file__).resolve().parents[2] / "data" / "rules"


def get_micro_rules_path():
    return get_rules_base_dir() / "micro_signals.json"


def get_arbitration_rules_path():
    return get_rules_base_dir() / "arbitration_rules.json"


def load_rule_list(path):
    rule_path = Path(path)
    if not rule_path.exists():
        return []

    try:
        return json.loads(rule_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_rule_list(path, rules):
    rule_path = Path(path)
    rule_path.parent.mkdir(parents=True, exist_ok=True)
    rule_path.write_text(json.dumps(rules or [], ensure_ascii=False, indent=2), encoding="utf-8")


def _slugify_rule_id(text, fallback="rule"):
    normalized = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", str(text or "")).strip("_").lower()
    return normalized or fallback


def _contains_cjk(text):
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def ensure_unique_rule_id(candidate_id, existing_ids=None, fallback="rule"):
    existing_ids = set(existing_ids or [])
    base_id = _slugify_rule_id(candidate_id, fallback=fallback)
    unique_id = base_id
    suffix = 2

    while unique_id in existing_ids:
        unique_id = f"{base_id}_{suffix}"
        suffix += 1

    return unique_id


def generate_rule_id_from_draft(draft, category=None, existing_ids=None):
    rule_category = category or draft.get("category") or draft.get("target_scope")
    prefix = "micro_rule" if rule_category in ("micro_signal", "warning") else "arbitration_rule"

    title_source = draft.get("title") or draft.get("problem_type") or draft.get("trigger_condition_nl") or ""
    title_slug = _slugify_rule_id(title_source, fallback="")
    fallback_source = draft.get("draft_id") or title_source or prefix
    base_source = title_slug if title_slug and not _contains_cjk(title_slug) else fallback_source
    base_id = _slugify_rule_id(base_source, fallback=prefix)

    if not base_id.startswith(prefix):
        base_id = f"{prefix}_{base_id}"

    return ensure_unique_rule_id(base_id, existing_ids=existing_ids, fallback=prefix)


def actual_nspf_to_bias(value):
    text = str(value or "").strip()
    return text if text in {"胜", "平", "负", "胜平", "平负", "胜负"} else ""


def _normalize_logic_expression(expr):
    text = str(expr or "").strip()
    if not text:
        return "False"

    text = re.sub(r"\bAND\b", "and", text, flags=re.IGNORECASE)
    text = re.sub(r"\bOR\b", "or", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNOT\b", "not", text, flags=re.IGNORECASE)
    text = re.sub(r"\bIS\s+TRUE\b", "is True", text, flags=re.IGNORECASE)
    text = re.sub(r"\bIS\s+FALSE\b", "is False", text, flags=re.IGNORECASE)

    between_pattern = re.compile(
        r"(?P<left>[A-Za-z_][A-Za-z0-9_\[\]\'\"]*)\s+BETWEEN\s+(?P<start>[^ ]+)\s+AND\s+(?P<end>[^ )]+)",
        flags=re.IGNORECASE,
    )
    while True:
        updated = between_pattern.sub(r"(\g<start> <= \g<left> <= \g<end>)", text)
        if updated == text:
            break
        text = updated

    return text


def normalize_micro_rule_condition(condition):
    text = _normalize_logic_expression(condition)

    alias_replacements = {
        "origin_handicap": "asian['start_hv']",
        "initial_line": "asian['start_hv']",
        "initial_water": "asian['giving_start_w']",
        "current_water": "asian['giving_live_w']",
        "final_water": "asian['giving_live_w']",
        "water_diff": "abs(asian['giving_live_w'] - asian['giving_start_w'])",
    }
    for src, dst in alias_replacements.items():
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)

    text = re.sub(r"(asian\['(?:start_hv|live_hv)'\]\s*[=!]=\s*)'([0-9.]+)'", r"\1\2", text)

    trend_replacements = {
        r"market_trend\s*==\s*'upgrade'": "asian['live_hv'] > asian['start_hv']",
        r'market_trend\s*==\s*"upgrade"': "asian['live_hv'] > asian['start_hv']",
        r"market_trend\s*==\s*'stable'": "asian['live_hv'] == asian['start_hv']",
        r'market_trend\s*==\s*"stable"': "asian['live_hv'] == asian['start_hv']",
        r"market_trend\s*==\s*'down'": "asian['live_hv'] < asian['start_hv']",
        r'market_trend\s*==\s*"down"': "asian['live_hv'] < asian['start_hv']",
        r"handicap_change\s*==\s*'up'": "asian['live_hv'] > asian['start_hv']",
        r'handicap_change\s*==\s*"up"': "asian['live_hv'] > asian['start_hv']",
        r"handicap_change\s*==\s*'stable'": "asian['live_hv'] == asian['start_hv']",
        r'handicap_change\s*==\s*"stable"': "asian['live_hv'] == asian['start_hv']",
        r"handicap_change\s*==\s*'down'": "asian['live_hv'] < asian['start_hv']",
        r'handicap_change\s*==\s*"down"': "asian['live_hv'] < asian['start_hv']",
    }
    for pattern, replacement in trend_replacements.items():
        text = re.sub(pattern, replacement, text)

    unsupported_tokens = []
    for token in ("signal(", "count(", "all(", "dimension.", "extracted_directions"):
        if token in text:
            unsupported_tokens.append(token)

    if unsupported_tokens:
        raise ValueError(
            "微观规则条件包含当前运行时不支持的伪代码/函数："
            + "、".join(unsupported_tokens)
            + "。请改写为 asian/euro/league 上下文可执行的 Python 布尔表达式。"
        )

    return text


def normalize_arbitration_rule_condition(condition):
    text = _normalize_logic_expression(condition)
    alias_replacements = {
        "origin_handicap": "ctx['asian'].get('start_hv')",
        "initial_line": "ctx['asian'].get('start_hv')",
        "initial_water": "ctx['asian'].get('giving_start_w')",
        "current_water": "ctx['asian'].get('giving_live_w')",
        "final_water": "ctx['asian'].get('giving_live_w')",
        "water_diff": "abs(ctx['asian'].get('giving_live_w', 0) - ctx['asian'].get('giving_start_w', 0))",
    }
    for src, dst in alias_replacements.items():
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)

    text = re.sub(r"(?<!ctx\[')asian\[['\"]([^'\"]+)['\"]\]", r"ctx['asian'].get('\1')", text)
    text = text.replace("asian.get(", "ctx['asian'].get(")

    unsupported_tokens = []
    for token in ("signal(", "count(", "dimension.", "extracted_directions"):
        if token in text:
            unsupported_tokens.append(token)
    if unsupported_tokens:
        raise ValueError(
            "仲裁规则条件包含当前运行时不支持的伪代码/函数："
            + "、".join(unsupported_tokens)
            + "。请改写为基于 ctx[...] 的可执行 Python 布尔表达式。"
        )
    return text


def normalize_arbitration_rule_action(action_type, action_payload=None, explanation="", suggested_bias=""):
    payload = dict(action_payload or {})
    action_text = str(action_type or "").strip()
    allowed_actions = {
        "abort_prediction",
        "force_double",
        "cap_confidence",
        "forbid_override",
        "require_override_reason",
    }

    if action_text in allowed_actions:
        return action_text, payload

    combined_text = " ".join(
        part for part in [action_text, explanation, suggested_bias] if str(part or "").strip()
    )

    if any(keyword in combined_text for keyword in ["无法预测", "建议回避", "直接回避", "信息不足", "熔断", "规避"]):
        if "message" not in payload:
            payload["message"] = action_text or explanation or "信息不足，建议回避"
        return "abort_prediction", payload

    confidence_match = re.search(r"(置信度|上限|不超过)\D{0,6}(\d{2,3})", combined_text)
    if confidence_match:
        payload["confidence_cap"] = int(confidence_match.group(2))
        return "cap_confidence", payload

    if "双选" in combined_text:
        payload.setdefault("nspf", True)
        payload.setdefault("rq", True)
        return "force_double", payload

    if any(keyword in combined_text for keyword in ["必须补充", "说明原因", "解释原因", "推翻原因"]):
        return "require_override_reason", payload

    if any(keyword in combined_text for keyword in ["禁止", "不得", "不应", "优先考虑", "优先跟随", "保护", "推翻"]):
        return "forbid_override", payload

    return "require_override_reason", payload


def convert_draft_to_arbitration_rule(draft):
    title = draft.get("rule_name") or draft.get("title") or draft.get("problem_type") or "未命名仲裁规则"
    action_type, action_payload = normalize_arbitration_rule_action(
        draft.get("action_type") or draft.get("suggested_action"),
        action_payload=draft.get("action_payload") if isinstance(draft.get("action_payload"), dict) else None,
        explanation=draft.get("explanation_template") or draft.get("trigger_condition_nl") or draft.get("problem_type") or title,
        suggested_bias=draft.get("suggested_bias") or "",
    )
    priority_value = draft.get("priority")
    normalized_priority = int(priority_value) if isinstance(priority_value, (int, float)) else (80 if priority_value == "high" else 60)
    return {
        "id": str(draft.get("rule_id") or generate_rule_id_from_draft(draft, category="arbitration_guard")).strip(),
        "name": title,
        "category": "arbitration_guard",
        "priority": normalized_priority,
        "condition": normalize_arbitration_rule_condition(draft.get("suggested_condition") or "False"),
        "action_type": action_type,
        "action_payload": action_payload,
        "explanation_template": draft.get("explanation_template") or draft.get("trigger_condition_nl") or draft.get("problem_type") or title,
        "scenario_key": draft.get("scenario_key") or "",
        "scenario_parts": draft.get("scenario_parts") or [],
        "scenario_version": draft.get("scenario_version") or "v1",
        "enabled": True,
        "source": "rule_draft",
    }


def convert_draft_to_micro_rule(draft):
    title = draft.get("rule_name") or draft.get("title") or draft.get("problem_type") or "未命名微观规则"
    trigger_text = draft.get("warning_message_template") or draft.get("trigger_condition_nl") or draft.get("problem_type") or title
    priority_value = draft.get("priority")
    level = "🔴高危" if (isinstance(priority_value, (int, float)) and int(priority_value) >= 80) or priority_value == "high" else "🟡关注"
    actual_bias = actual_nspf_to_bias(draft.get("actual_nspf"))
    return {
        "id": str(draft.get("rule_id") or generate_rule_id_from_draft(draft, category="micro_signal")).strip(),
        "name": title,
        "category": "micro_signal",
        "level": level,
        "condition": normalize_micro_rule_condition(draft.get("suggested_condition") or "False"),
        "warning_template": trigger_text,
        "prediction_bias": actual_bias or draft.get("prediction_bias") or draft.get("suggested_bias") or "",
        "effect": draft.get("effect_type") or draft.get("suggested_action") or "",
        "scenario_key": draft.get("scenario_key") or "",
        "scenario_parts": draft.get("scenario_parts") or [],
        "scenario_version": draft.get("scenario_version") or "v1",
        "enabled": True,
        "source": "rule_draft",
    }


def append_rule(path, rule):
    rules = load_rule_list(path)
    existing_ids = {item.get("id") for item in rules}
    if rule.get("id") not in existing_ids:
        rules.append(rule)
        save_rule_list(path, rules)
    return rules
