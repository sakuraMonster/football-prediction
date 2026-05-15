import base64
import json
import os
import re
import sys
import time
from datetime import datetime

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.constants import AUTH_TOKEN_TTL
from src.db.database import Database
from src.utils.rule_drafts import delete_rule_draft, get_pending_rule_drafts, update_rule_draft_status
from src.utils.rule_registry import (
    append_rule,
    convert_draft_to_arbitration_rule,
    convert_draft_to_micro_rule,
    ensure_unique_rule_id,
    get_arbitration_rules_path,
    get_micro_rules_path,
    generate_rule_id_from_draft,
    load_rule_list,
    save_rule_list,
)


def _normalize_scenario_key(value):
    return str(value or "").strip()


def _collect_scenario_options(*rule_groups):
    options = []
    seen = set()
    for group in rule_groups:
        for item in group or []:
            scenario_key = _normalize_scenario_key(item.get("scenario_key"))
            if scenario_key and scenario_key not in seen:
                seen.add(scenario_key)
                options.append(scenario_key)
    return sorted(options)


def _filter_rules_by_scenario(rules, scenario_key):
    normalized = _normalize_scenario_key(scenario_key)
    if not normalized:
        return list(rules or [])
    return [rule for rule in (rules or []) if _normalize_scenario_key(rule.get("scenario_key")) == normalized]


def _find_same_scenario_rules(draft, micro_rules, arbitration_rules):
    scenario_key = _normalize_scenario_key(draft.get("scenario_key"))
    if not scenario_key:
        return []
    candidates = []
    for rule in (micro_rules or []) + (arbitration_rules or []):
        if _normalize_scenario_key(rule.get("scenario_key")) == scenario_key:
            candidates.append(rule)
    return candidates


def _analyze_condition_rigidity(condition):
    text = str(condition or "").strip()
    if not text:
        return []

    issues = []
    if "euro['macau_start']" in text or "euro['bet365_start']" in text:
        issues.append("引用了历史欧赔原始点位")
    if "euro['live_home']" in text or "euro['live_away']" in text:
        issues.append("直接用即时欧赔点位做单场比较")
    if re.search(r"\b(?:>=|<=|>|<)\s\d+\.\d{3,}\b", text):
        issues.append("包含精确小数阈值")
    if "/ euro['" in text or "]['a'] / euro['" in text or "]['h'] / euro['" in text:
        issues.append("使用了精确欧赔比值")

    deduped = []
    for issue in issues:
        if issue not in deduped:
            deduped.append(issue)
    return deduped


def decode_auth_token(token):
    try:
        raw = base64.b64decode(token.encode("utf-8")).decode("utf-8")
        username, timestamp = raw.split("|")
        return username, int(timestamp)
    except Exception:
        return None, 0


def _render_micro_rules_editor(rules, focus_rule_id="", focus_draft=None):
    updated_rules = []
    changed = False

    for i, rule in enumerate(rules):
        title = f"{'🟢' if rule.get('enabled', True) else '⚪'} {rule.get('name', '未命名规则')} [{rule.get('id', '?')}]"
        is_focus_rule = bool(focus_rule_id and rule.get("id") == focus_rule_id)
        with st.expander(title, expanded=is_focus_rule):
            if is_focus_rule and focus_draft:
                st.info(
                    "复盘建议修改点："
                    f" 条件=`{focus_draft.get('suggested_condition', 'False')}`；"
                    f" 动作=`{focus_draft.get('suggested_action', '')}`；"
                    f" 偏向=`{focus_draft.get('suggested_bias', '')}`"
                )
            if rule.get("scenario_key"):
                st.caption(f"盘口剧本：`{rule.get('scenario_key')}`")
            rigidity_issues = _analyze_condition_rigidity(rule.get("condition"))
            if rigidity_issues:
                st.warning("条件过死风险：" + "、".join(rigidity_issues))
            col1, col2 = st.columns([1, 5])

            with col1:
                is_enabled = st.checkbox("启用此规则", value=rule.get("enabled", True), key=f"micro_enable_{i}")
                if is_enabled != rule.get("enabled", True):
                    rule["enabled"] = is_enabled
                    changed = True

            with col2:
                new_condition = st.text_area("触发条件", value=rule.get("condition", ""), key=f"micro_cond_{i}")
                new_template = st.text_area("警告话术模板", value=rule.get("warning_template", ""), key=f"micro_warn_{i}")
                new_bias = st.text_input("预测偏向", value=rule.get("prediction_bias", ""), key=f"micro_bias_{i}")
                new_effect = st.text_input("作用类型", value=rule.get("effect", ""), key=f"micro_effect_{i}")

                if new_condition != rule.get("condition", ""):
                    rule["condition"] = new_condition
                    changed = True
                if new_template != rule.get("warning_template", ""):
                    rule["warning_template"] = new_template
                    changed = True
                if new_bias != rule.get("prediction_bias", ""):
                    rule["prediction_bias"] = new_bias
                    changed = True
                if new_effect != rule.get("effect", ""):
                    rule["effect"] = new_effect
                    changed = True

            updated_rules.append(rule)

    return updated_rules, changed


def _render_arbitration_rules_editor(rules, focus_rule_id="", focus_draft=None):
    updated_rules = []
    changed = False

    for i, rule in enumerate(rules):
        title = f"{'🟢' if rule.get('enabled', True) else '⚪'} {rule.get('name', '未命名仲裁规则')} [{rule.get('id', '?')}]"
        is_focus_rule = bool(focus_rule_id and rule.get("id") == focus_rule_id)
        with st.expander(title, expanded=is_focus_rule):
            if is_focus_rule and focus_draft:
                st.info(
                    "复盘建议修改点："
                    f" 条件=`{focus_draft.get('suggested_condition', 'False')}`；"
                    f" 动作=`{focus_draft.get('suggested_action', '')}`；"
                    f" 摘要=`{focus_draft.get('trigger_condition_nl', '')}`"
                )
            if rule.get("scenario_key"):
                st.caption(f"盘口剧本：`{rule.get('scenario_key')}`")
            col1, col2 = st.columns([1, 5])

            with col1:
                is_enabled = st.checkbox("启用此规则", value=rule.get("enabled", True), key=f"arb_enable_{i}")
                if is_enabled != rule.get("enabled", True):
                    rule["enabled"] = is_enabled
                    changed = True

            with col2:
                new_condition = st.text_area("触发条件", value=rule.get("condition", ""), key=f"arb_cond_{i}")
                new_action_type = st.text_input("动作类型", value=rule.get("action_type", ""), key=f"arb_action_{i}")
                new_action_payload = st.text_area(
                    "动作参数(JSON)",
                    value=json.dumps(rule.get("action_payload", {}), ensure_ascii=False, indent=2),
                    key=f"arb_payload_{i}",
                )
                new_explanation = st.text_area(
                    "解释模板",
                    value=rule.get("explanation_template", ""),
                    key=f"arb_explain_{i}",
                )
                new_priority = st.number_input(
                    "优先级",
                    min_value=0,
                    max_value=999,
                    value=int(rule.get("priority", 0)),
                    key=f"arb_priority_{i}",
                )

                if new_condition != rule.get("condition", ""):
                    rule["condition"] = new_condition
                    changed = True
                if new_action_type != rule.get("action_type", ""):
                    rule["action_type"] = new_action_type
                    changed = True
                if new_explanation != rule.get("explanation_template", ""):
                    rule["explanation_template"] = new_explanation
                    changed = True
                if int(new_priority) != int(rule.get("priority", 0)):
                    rule["priority"] = int(new_priority)
                    changed = True

                try:
                    payload = json.loads(new_action_payload or "{}")
                    if payload != rule.get("action_payload", {}):
                        rule["action_payload"] = payload
                        changed = True
                except Exception:
                    st.warning("动作参数不是合法 JSON，保存前请先修正。")

            updated_rules.append(rule)

    return updated_rules, changed


def _render_prefilled_micro_rule_form(draft, micro_rules_path):
    st.markdown("### ✍️ 预填新增微观规则")
    default_rule = convert_draft_to_micro_rule(draft)
    draft_token = draft.get("draft_id") or "unknown"
    existing_ids = {item.get("id") for item in load_rule_list(micro_rules_path)}
    generated_rule_id = generate_rule_id_from_draft(draft, category="micro_signal", existing_ids=existing_ids)
    rule_id = st.text_input("规则ID", value=generated_rule_id, key=f"prefill_micro_id::{draft_token}")
    name = st.text_input("规则名称", value=default_rule.get("name", ""), key=f"prefill_micro_name::{draft_token}")
    level = st.text_input("风险级别", value=default_rule.get("level", ""), key=f"prefill_micro_level::{draft_token}")
    condition = st.text_area("触发条件", value=default_rule.get("condition", ""), key=f"prefill_micro_condition::{draft_token}")
    warning_template = st.text_area("警告话术模板", value=default_rule.get("warning_template", ""), key=f"prefill_micro_warn::{draft_token}")
    prediction_bias = st.text_input("预测偏向", value=default_rule.get("prediction_bias", ""), key=f"prefill_micro_bias::{draft_token}")
    effect = st.text_input("作用类型", value=default_rule.get("effect", ""), key=f"prefill_micro_effect::{draft_token}")
    if default_rule.get("scenario_key"):
        st.caption(f"盘口剧本：`{default_rule.get('scenario_key')}`")
    rigidity_issues = _analyze_condition_rigidity(default_rule.get("condition"))
    if rigidity_issues:
        st.warning("预填条件存在过死风险：" + "、".join(rigidity_issues))

    if st.button("➕ 按预填内容新增微观规则", key=f"prefill_create_micro::{draft_token}"):
        final_rule_id = ensure_unique_rule_id(rule_id or generated_rule_id, existing_ids=existing_ids, fallback="micro_rule")
        append_rule(
            micro_rules_path,
            {
                "id": final_rule_id,
                "name": name,
                "category": "micro_signal",
                "level": level,
                "condition": condition,
                "warning_template": warning_template,
                "prediction_bias": prediction_bias,
                "effect": effect,
                "scenario_key": default_rule.get("scenario_key") or draft.get("scenario_key") or "",
                "scenario_parts": default_rule.get("scenario_parts") or draft.get("scenario_parts") or [],
                "scenario_version": default_rule.get("scenario_version") or draft.get("scenario_version") or "v1",
                "enabled": True,
                "source": "rule_draft_prefill",
            },
        )
        delete_rule_draft(draft.get("draft_id"))
        st.success(f"已按预填内容新增微观规则 `{final_rule_id}`，并自动删除草稿。")
        time.sleep(1)
        st.rerun()


def _render_prefilled_arbitration_rule_form(draft, arbitration_rules_path):
    st.markdown("### ✍️ 预填新增仲裁规则")
    default_rule = convert_draft_to_arbitration_rule(draft)
    draft_token = draft.get("draft_id") or "unknown"
    existing_ids = {item.get("id") for item in load_rule_list(arbitration_rules_path)}
    generated_rule_id = generate_rule_id_from_draft(draft, category="arbitration_guard", existing_ids=existing_ids)
    rule_id = st.text_input("规则ID", value=generated_rule_id, key=f"prefill_arb_id::{draft_token}")
    name = st.text_input("规则名称", value=default_rule.get("name", ""), key=f"prefill_arb_name::{draft_token}")
    priority = st.number_input("优先级", min_value=0, max_value=999, value=int(default_rule.get("priority", 0)), key=f"prefill_arb_priority::{draft_token}")
    condition = st.text_area("触发条件", value=default_rule.get("condition", ""), key=f"prefill_arb_condition::{draft_token}")
    action_type = st.text_input("动作类型", value=default_rule.get("action_type", ""), key=f"prefill_arb_action::{draft_token}")
    action_payload = st.text_area(
        "动作参数(JSON)",
        value=json.dumps(default_rule.get("action_payload", {}), ensure_ascii=False, indent=2),
        key=f"prefill_arb_payload::{draft_token}",
    )
    explanation = st.text_area("解释模板", value=default_rule.get("explanation_template", ""), key=f"prefill_arb_explain::{draft_token}")
    if default_rule.get("scenario_key"):
        st.caption(f"盘口剧本：`{default_rule.get('scenario_key')}`")

    if st.button("➕ 按预填内容新增仲裁规则", key=f"prefill_create_arb::{draft_token}"):
        payload = json.loads(action_payload or "{}")
        final_rule_id = ensure_unique_rule_id(rule_id or generated_rule_id, existing_ids=existing_ids, fallback="arbitration_rule")
        append_rule(
            arbitration_rules_path,
            {
                "id": final_rule_id,
                "name": name,
                "category": "arbitration_guard",
                "priority": int(priority),
                "condition": condition,
                "action_type": action_type,
                "action_payload": payload,
                "explanation_template": explanation,
                "scenario_key": default_rule.get("scenario_key") or draft.get("scenario_key") or "",
                "scenario_parts": default_rule.get("scenario_parts") or draft.get("scenario_parts") or [],
                "scenario_version": default_rule.get("scenario_version") or draft.get("scenario_version") or "v1",
                "enabled": True,
                "source": "rule_draft_prefill",
            },
        )
        delete_rule_draft(draft.get("draft_id"))
        st.success(f"已按预填内容新增仲裁规则 `{final_rule_id}`，并自动删除草稿。")
        time.sleep(1)
        st.rerun()


def _render_micro_rule_generator(base_dir, micro_rules_path):
    st.markdown("---")
    st.subheader("🤖 AI 自动提炼微观规则")
    st.markdown("将复盘报告中的盘口错误分析粘贴到下方，AI 会提炼成一条可直接落到微观规则库的配置。")

    review_text = st.text_area("输入复盘报告", height=150)
    if st.button("✨ 生成微观规则配置"):
        if not review_text.strip():
            st.warning("请输入复盘报告内容。")
        else:
            with st.spinner("AI 正在提炼微观规则..."):
                try:
                    from src.llm.predictor import LLMPredictor

                    predictor = LLMPredictor()
                    prompt = f"""
你是一个精通 Python 和竞彩盘口分析的专家。
请基于下面的复盘报告，生成一条盘口微观规则。

上下文可用变量：
- asian['start_hv']
- asian['live_hv']
- asian['giving_start_w']
- asian['giving_live_w']
- asian['receiving_live_w']
- euro['p_draw']
- league['is_euro_cup']

严格输出 JSON，必须包含字段：
{{
  "id": "规则英文ID",
  "name": "规则中文名",
  "category": "micro_signal",
  "level": "🔴高危",
  "condition": "Python 布尔表达式",
  "warning_template": "中文警告话术",
  "prediction_bias": "胜/平/负/胜平/平负/胜负",
  "effect": "规则作用类型",
  "enabled": true
}}

复盘报告如下：
{review_text}
"""
                    response = predictor.client.chat.completions.create(
                        model=predictor.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                    )
                    result_text = response.choices[0].message.content.strip()
                    if result_text.startswith("```json"):
                        result_text = result_text[7:]
                    if result_text.startswith("```"):
                        result_text = result_text[3:]
                    if result_text.endswith("```"):
                        result_text = result_text[:-3]

                    st.session_state["new_generated_rule"] = json.loads(result_text.strip())
                    st.success("✅ 微观规则提炼成功，请确认后保存。")
                except Exception as e:
                    st.error(f"生成规则失败: {e}")

    if "new_generated_rule" in st.session_state:
        st.write("### 预览生成的微观规则")
        st.json(st.session_state["new_generated_rule"])

        if st.button("➕ 添加到微观规则库并保存"):
            append_rule(micro_rules_path, st.session_state["new_generated_rule"])
            del st.session_state["new_generated_rule"]
            st.success("新规则已成功添加到微观规则库！")
            time.sleep(1)
            st.rerun()


def app():
    st.set_page_config(page_title="风控规则管理", page_icon="⚙️", layout="wide")

    if "auth" in st.query_params and not st.session_state.get("logged_in", False):
        try:
            token = st.query_params["auth"]
            username, login_timestamp = decode_auth_token(token)
            if username and (int(time.time()) - login_timestamp <= AUTH_TOKEN_TTL):
                db = Database()
                user = db.get_user(username)
                db.close()
                if user and datetime.now() <= user.valid_until:
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = user.username
                    st.session_state["role"] = user.role
                    st.session_state["valid_until"] = user.valid_until
                    st.session_state["auth_token"] = token
        except Exception:
            pass

    if not st.session_state.get("logged_in", False):
        st.warning("⚠️ 您尚未登录或会话已过期，请先登录！")
        if st.button("👉 返回登录页面"):
            st.switch_page("app.py")
        st.stop()

    if "auth" not in st.query_params:
        token = st.session_state.get("auth_token", "")
        if not token and st.session_state.get("username"):
            try:
                raw_token = f"{st.session_state['username']}|{int(time.time())}"
                token = base64.b64encode(raw_token.encode("utf-8")).decode("utf-8")
            except Exception:
                token = ""
        if token:
            st.session_state["auth_token"] = token
            st.query_params["auth"] = token

    st.title("⚙️ 动态风控规则管理")
    st.markdown("在此处统一管理微观规则、仲裁保护规则以及复盘自动生成的候选草稿。")

    focus_case = st.query_params.get("focus_case", st.session_state.get("rule_manager_focus_case", ""))
    focus_rule_id = st.query_params.get("focus_rule_id", st.session_state.get("rule_manager_focus_rule_id", ""))
    focus_scope = st.query_params.get("focus_scope", st.session_state.get("rule_manager_focus_scope", ""))
    focus_action = st.query_params.get("focus_action", st.session_state.get("rule_manager_focus_action", ""))
    if focus_case:
        st.session_state["rule_manager_focus_case"] = focus_case
    if focus_rule_id:
        st.session_state["rule_manager_focus_rule_id"] = focus_rule_id
    if focus_scope:
        st.session_state["rule_manager_focus_scope"] = focus_scope
    if focus_action:
        st.session_state["rule_manager_focus_action"] = focus_action
    if focus_case or focus_rule_id or focus_scope or focus_action:
        focus_parts = []
        if focus_case:
            focus_parts.append(f"当前焦点比赛：`{focus_case}`")
        if focus_rule_id:
            focus_parts.append(f"关联旧规则：`{focus_rule_id}`")
        if focus_scope:
            focus_parts.append(f"目标区域：`{focus_scope}`")
        if focus_action:
            focus_parts.append(f"建议动作：`{focus_action}`")
        st.info(" | ".join(focus_parts))

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    micro_rules_path = get_micro_rules_path()
    arbitration_rules_path = get_arbitration_rules_path()
    micro_rules_all = load_rule_list(micro_rules_path)
    arbitration_rules_all = load_rule_list(arbitration_rules_path)
    drafts = get_pending_rule_drafts()

    scenario_options = _collect_scenario_options(micro_rules_all, arbitration_rules_all, drafts)
    selected_scenario = st.selectbox(
        "盘口剧本筛选",
        ["全部剧本"] + scenario_options,
        index=0,
        help="按盘口剧本筛选规则和草稿，便于查看同剧本历史规则与新增草稿。",
    )
    active_scenario_key = "" if selected_scenario == "全部剧本" else selected_scenario

    def _draft_matches_focus(draft):
        draft_case = draft.get("case_id") or "|".join(draft.get("source_matches") or [])
        if focus_case and draft_case == focus_case:
            return True
        if focus_rule_id and draft.get("based_on_rule_id") == focus_rule_id:
            return True
        return False

    visible_drafts = _filter_rules_by_scenario(drafts, active_scenario_key)
    focus_draft = next((draft for draft in visible_drafts if _draft_matches_focus(draft)), None)

    section_options = ["🧩 微观规则", "🛡️ 仲裁规则", "📝 候选草稿"]
    scope_to_section = {
        "micro_signal": "🧩 微观规则",
        "warning": "🧩 微观规则",
        "arbitration_guard": "🛡️ 仲裁规则",
    }
    default_section = scope_to_section.get(focus_scope, "📝 候选草稿" if focus_case or focus_rule_id else "🧩 微观规则")
    selector_focus_token = "|".join(
        [
            focus_scope or "",
            focus_case or "",
            focus_rule_id or "",
            focus_action or "",
        ]
    )
    selected_section = st.radio(
        "规则区域",
        section_options,
        index=section_options.index(default_section),
        horizontal=True,
        key=f"rule_manager_section_selector::{selector_focus_token or 'default'}",
        label_visibility="collapsed",
    )

    if selected_section == "🧩 微观规则":
        micro_rules = _filter_rules_by_scenario(micro_rules_all, active_scenario_key)
        st.subheader("📋 微观规则列表")
        if active_scenario_key:
            st.caption(f"当前仅展示剧本：`{active_scenario_key}`")
        if focus_action == "optimize_existing":
            st.caption("当前为修旧规则模式，优先检查与焦点比赛关联的旧微观规则。")
        elif focus_action == "add_new_rule":
            st.caption("当前为新增规则模式，可基于复盘草稿补充新的微观规则。")
        if focus_action == "add_new_rule" and focus_draft:
            _render_prefilled_micro_rule_form(focus_draft, micro_rules_path)
            st.markdown("---")
        updated_micro_rules, micro_changed = _render_micro_rules_editor(
            micro_rules,
            focus_rule_id=focus_rule_id if focus_scope in ("micro_signal", "warning") else "",
            focus_draft=focus_draft if focus_action == "optimize_existing" else None,
        )
        if micro_changed and st.button("💾 保存微观规则", type="primary"):
            save_rule_list(micro_rules_path, updated_micro_rules)
            st.success("微观规则已保存，下一次预测将自动生效。")
            st.rerun()

        st.markdown("---")
        st.subheader("💡 微观规则变量字典参考")
        st.markdown(
            """
- `asian['start_hv']`: 初盘盘口数值
- `asian['live_hv']`: 即时盘口数值
- `asian['giving_start_w']`: 初盘让球方水位
- `asian['receiving_start_w']`: 初盘受让方水位
- `asian['giving_live_w']`: 即时盘让球方水位
- `asian['receiving_live_w']`: 即时盘受让方水位
- `euro['p_draw']`: 欧赔隐含平局概率
- `euro['favored_side']`: 欧赔初赔低赔方（home/away）
- `euro['strength_gap_label']`: 欧赔强弱档位（接近平势/中度优势/强弱分明/实力鸿沟）
- `euro['movement_side']`: 欧赔主要变动侧（home/away/none）
- `euro['movement_direction']`: 欧赔变动方向（up/down/flat）
- `euro['movement_magnitude']`: 欧赔调幅档位（轻微/中等/剧烈/无显著调幅）
- `league['is_euro_cup']`: 是否欧战
"""
        )
        _render_micro_rule_generator(base_dir, micro_rules_path)

    elif selected_section == "🛡️ 仲裁规则":
        arbitration_rules = _filter_rules_by_scenario(arbitration_rules_all, active_scenario_key)
        st.subheader("📋 仲裁保护规则列表")
        if active_scenario_key:
            st.caption(f"当前仅展示剧本：`{active_scenario_key}`")
        if focus_action == "optimize_existing":
            st.caption("当前为修旧规则模式，优先检查与焦点比赛关联的旧仲裁保护规则。")
        elif focus_action == "add_new_rule":
            st.caption("当前为新增规则模式，可基于复盘草稿补充新的仲裁保护规则。")
        if focus_action == "add_new_rule" and focus_draft:
            _render_prefilled_arbitration_rule_form(focus_draft, arbitration_rules_path)
            st.markdown("---")
        updated_arbitration_rules, arbitration_changed = _render_arbitration_rules_editor(
            arbitration_rules,
            focus_rule_id=focus_rule_id if focus_scope == "arbitration_guard" else "",
            focus_draft=focus_draft if focus_action == "optimize_existing" else None,
        )
        if arbitration_changed and st.button("💾 保存仲裁规则", type="primary"):
            save_rule_list(arbitration_rules_path, updated_arbitration_rules)
            st.success("仲裁保护规则已保存，下一次预测将自动生效。")
            st.rerun()

        st.markdown("---")
        st.subheader("💡 仲裁规则动作参考")
        st.markdown(
            """
- `abort_prediction`: 直接回避，不输出有效预测
- `forbid_override`: 禁止弱证据推翻强盘口
- `force_double`: 强制双选
- `cap_confidence`: 压低置信度上限
- `require_override_reason`: 强制补充推翻原因
"""
        )

    else:
        st.subheader("📝 复盘候选规则草稿")
        if not visible_drafts:
            st.info("当前没有待审核的规则草稿。")
        else:
            visible_drafts = sorted(visible_drafts, key=lambda draft: 0 if _draft_matches_focus(draft) else 1)
            for i, draft in enumerate(visible_drafts):
                source_matches = "、".join(draft.get("source_matches") or []) or "未知来源"
                title = f"{draft.get('title', '未命名草稿')} [{draft.get('target_scope', 'unknown')}]"
                with st.expander(title, expanded=_draft_matches_focus(draft)):
                    st.write(f"问题类型：{draft.get('problem_type', '未标注')}")
                    st.write(f"来源比赛：{source_matches}")
                    st.write(f"处置分类：{draft.get('disposition', '未分类')}")
                    if draft.get("based_on_rule_id"):
                        st.write(f"基于旧规则：`{draft.get('based_on_rule_id')}`")
                    if draft.get("market_review_complete") is False:
                        st.warning("该草稿对应场次的盘口复盘不完整，建议先补充盘口链路再审核。")
                    if draft.get("scenario_key"):
                        st.write(f"盘口剧本Key：`{draft.get('scenario_key')}`")
                    if draft.get("scenario_parts"):
                        st.write(f"盘口剧本拆分：`{' | '.join(draft.get('scenario_parts') or [])}`")
                    same_scenario_rules = _find_same_scenario_rules(draft, micro_rules_all, arbitration_rules_all)
                    if same_scenario_rules:
                        sample = "、".join(f"{rule.get('name', '未命名')}[{rule.get('id', '?')}]" for rule in same_scenario_rules[:3])
                        st.info(f"同剧本已有规则 {len(same_scenario_rules)} 条：{sample}")
                    st.write(f"触发条件描述：{draft.get('trigger_condition_nl', '未提供')}")
                    st.write(f"建议条件：`{draft.get('suggested_condition', 'False')}`")
                    draft_rigidity_issues = _analyze_condition_rigidity(draft.get("suggested_condition"))
                    if draft_rigidity_issues:
                        st.warning("该草稿条件过死：" + "、".join(draft_rigidity_issues))
                    st.write(f"建议动作：`{draft.get('suggested_action', '')}`")
                    if draft.get("suggested_bias"):
                        st.write(f"建议偏向：{draft.get('suggested_bias')}")

                    draft_case = draft.get("case_id") or "|".join(draft.get("source_matches") or [])
                    draft_scope = draft.get("target_scope", "")
                    action_cols = st.columns(2)
                    if draft.get("based_on_rule_id"):
                        repair_params = {
                            "focus_case": draft_case,
                            "focus_rule_id": draft.get("based_on_rule_id", ""),
                            "focus_scope": draft_scope,
                            "focus_action": "optimize_existing",
                        }
                        if action_cols[0].button("修旧规则", key=f"edit_existing_{i}"):
                            st.query_params.update(repair_params)
                            st.rerun()
                    else:
                        action_cols[0].button("修旧规则", key=f"edit_existing_{i}", disabled=True)

                    if action_cols[1].button("新增规则", key=f"create_new_{i}"):
                        st.query_params.update(
                            {
                                "focus_case": draft_case,
                                "focus_rule_id": draft.get("based_on_rule_id", ""),
                                "focus_scope": draft_scope,
                                "focus_action": "add_new_rule",
                            }
                        )
                        st.rerun()

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button("采纳为微观规则", key=f"accept_micro_{i}"):
                            try:
                                rule = convert_draft_to_micro_rule(draft)
                                rule["id"] = ensure_unique_rule_id(
                                    rule.get("id"),
                                    existing_ids={item.get("id") for item in load_rule_list(micro_rules_path)},
                                    fallback="micro_rule",
                                )
                                append_rule(micro_rules_path, rule)
                                delete_rule_draft(draft.get("draft_id"))
                                st.success(f"已采纳为微观规则 `{rule['id']}`，并自动删除草稿。")
                                st.rerun()
                            except Exception as e:
                                st.error(f"草稿无法直接采纳为微观规则：{e}")
                    with col2:
                        if st.button("采纳为仲裁规则", key=f"accept_arb_{i}"):
                            try:
                                rule = convert_draft_to_arbitration_rule(draft)
                                rule["id"] = ensure_unique_rule_id(
                                    rule.get("id"),
                                    existing_ids={item.get("id") for item in load_rule_list(arbitration_rules_path)},
                                    fallback="arbitration_rule",
                                )
                                append_rule(arbitration_rules_path, rule)
                                delete_rule_draft(draft.get("draft_id"))
                                st.success(f"已采纳为仲裁保护规则 `{rule['id']}`，并自动删除草稿。")
                                st.rerun()
                            except Exception as e:
                                st.error(f"草稿无法直接采纳为仲裁规则：{e}")
                    with col3:
                        if st.button("忽略草稿", key=f"reject_draft_{i}"):
                            update_rule_draft_status(draft.get("draft_id"), "rejected")
                            st.info("该草稿已标记为忽略。")
                            st.rerun()


if __name__ == "__main__":
    app()
