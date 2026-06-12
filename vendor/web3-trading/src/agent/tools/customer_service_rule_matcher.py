# -*- coding: utf-8 -*-
"""
规则匹配引擎 — 将 MCP 返回的结构化数据与预定义规则进行匹配

核心流程:
1. load_rules(scene) — 从 MCP Prompt Server / 本地文件加载规则 JSON
2. normalize_mcp_data(scene, data) — 将 MCP Integer/Boolean 值转为规则使用的标签
3. resolve_field(data, dotted_path) — 解析嵌套字段 (e.g. "accountVerifyInfo.verificationType")
4. match_rules(data, rules_list) — 遍历规则, 找到第一个完全匹配的规则
5. try_rule_match(scene, mcp_data) — 主入口: 加载规则 → 归一化 → 匹配 → 返回答案

规则格式:
  每条规则是一个 dict, 包含 rules / answer / question / note 字段
  rules 字段是 AND 条件集合, 支持:
    - 精确匹配:    "field": "value"
    - 数组 IN:     "field": ["val1", "val2"]   (MCP值 ∈ 数组 → 匹配)
    - 运算符对象:  "field": {"op": "contains|not_contains|<|>=|!=|not_in", "value": ...}
    - 动态引用:    "field": {"op": "<", "ref": "other.field"}
    - 语义条件:    "_semantic": "..."  (需 LLM 判断, 此处跳过标记为 partial match)
    - 兜底:        "_fallback": "..."  (所有规则都不匹配时返回)
    - 复杂条件:    "_complex": "..."   (需代码特殊处理, 此处跳过)
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
# 值映射表 — MCP 返回值 → 规则标签
# ════════════════════════════════════════════════════════════

# KYC 场景: verificationType / verificationStatus / reviewStatus 是 Integer
_KYC_VERIFICATION_TYPE_MAP = {
    1: "个人身份认证",   # KYC
    2: "机构身份认证",   # KYB
    3: "从未提交过KYC信息",  # Unverified
}

_KYC_VERIFICATION_STATUS_MAP = {
    1: "认证通过",       # Passed
    2: "待审核",         # Pending / In Review
    3: "认证不通过",      # Failed
    4: "从未提交过KYC信息",  # Not Submitted
    # 扩展值 (真实 API 可能有更多枚举):
    5: "审核通过",       # Approved (alias)
    6: "审核不通过",      # Rejected (alias)
    7: "Watch List审核不通过",  # Watch List rejected
    8: "不通过认证",      # Verification denied
}

_KYC_REVIEW_STATUS_MAP = {
    1: "认证通过",       # Pass
    2: "未审核",         # Not started / In Review
    3: "审核不通过",      # Fail
    # 扩展值:
    4: "待Watch List人工审核",
    5: "Watch List审核不通过",
    6: "Watch List人工审核不通过",
    7: "不通过认证",
    8: "Level 1 restriction",
    9: "Level 2 restriction",
}

_KYC_PAN_STATUS_MAP = {
    0: "待处理",         # Pending
    1: "通过",           # Approved
    2: "拒绝",           # Rejected
    3: "处理中",         # Processing
    4: "人工审核中",      # Manual review
}

_KYC_OPERATOR_MAP = {
    "system": "机器审核",
    "auto": "机器审核",
    "ekyc": "机器审核",
    "manual": "客服",
    "admin": "客服",
    "cs": "客服",
}

# Asset 场景: isTransferFreeze 是 Boolean
_ASSET_TRANSFER_FREEZE_MAP = {
    True: "冻结",
    False: "正常",
}

# P2P 场景: Boolean 字段 → Yes/No
_BOOL_YES_NO = {
    True: "Yes",
    False: "No",
}

# Account 场景: isAccountDeleted Boolean → 中文
_ACCOUNT_DELETED_MAP = {
    True: "被注销",
    False: "未被注销",
}

# Account 场景: accountFrozenStatus / withdrawalFrozenStatus / tradingFrozenStatus
# API 返回 String 类型, 可能是中文(已正确) 或 英文/Boolean(需映射)
_ACCOUNT_FROZEN_STATUS_MAP = {
    True: "被冻结",
    False: "未被冻结",
    "FROZEN": "被冻结",
    "NOT_FROZEN": "未被冻结",
    "frozen": "被冻结",
    "not_frozen": "未被冻结",
    "true": "被冻结",
    "false": "未被冻结",
    # 如果 MCP 直接返回中文, 这些 key 不会命中, 值保持原样
}

# P2P 场景: orderStatus (MCP 返回英文 → 规则使用中文)
_P2P_ORDER_STATUS_MAP = {
    "COMPLETED": "已完成",
    "CANCELLED": "已取消",
    "CANCELED": "已取消",
    "PENDING": "待付款",
    "UNPAID": "待付款",
    "PAID": "已付款，待放币",
    "PAID_PENDING_RELEASE": "已付款，待放币",
    "APPEAL": "已付款，待放币",  # appeal 状态下订单本身是 paid
}

# P2P 场景: appealStatus (MCP 返回英文 → 规则使用标签)
_P2P_APPEAL_STATUS_MAP = {
    "OPEN": "Appeal",
    "PENDING": "Appeal",
    "RESOLVED": "Appeal Done",
    "CLOSED": "Appeal Done",
    None: "Normal",
    "": "Normal",
}

# Deposit 场景: assetDeposit.status
_DEPOSIT_STATUS_MAP = {
    "SUCCESS": "成功",
    "PENDING": "待处理",
    "FAILED": "失败",
}

# Withdrawal 场景: frontWithdrawalRecord.status
_WITHDRAWAL_FRONT_STATUS_MAP = {
    "SUCCESS": "已完成",
    "COMPLETED": "已完成",
    "DONE": "已完成",
    # "Processing" 在规则中就是英文, 不需要映射
}


# ════════════════════════════════════════════════════════════
# 数据归一化
# ════════════════════════════════════════════════════════════

def _apply_map(data: dict, path: str, mapping: dict) -> None:
    """对嵌套 dict 中指定路径的值进行映射转换 (in-place)"""
    parts = path.split(".")
    obj = data
    for p in parts[:-1]:
        if isinstance(obj, dict):
            obj = obj.get(p)
        else:
            return
        if obj is None:
            return
    if isinstance(obj, dict):
        key = parts[-1]
        val = obj.get(key)
        if val in mapping:
            obj[key] = mapping[val]
        # 如果值是字符串形式的整数, 也尝试映射
        elif isinstance(val, str) and val.isdigit():
            int_val = int(val)
            if int_val in mapping:
                obj[key] = mapping[int_val]


def normalize_mcp_data(scene: str, data: dict) -> dict:
    """
    将 MCP 返回的原始数据归一化为规则文件使用的标签格式。
    返回深拷贝, 不修改原始数据。
    """
    import copy
    normalized = copy.deepcopy(data)

    if scene == "kyc":
        _apply_map(normalized, "accountVerifyInfo.verificationType", _KYC_VERIFICATION_TYPE_MAP)
        _apply_map(normalized, "accountVerifyInfo.verificationStatus", _KYC_VERIFICATION_STATUS_MAP)
        _apply_map(normalized, "accountVerifyInfo.reviewStatus", _KYC_REVIEW_STATUS_MAP)
        _apply_map(normalized, "accountVerifyInfo.operator", _KYC_OPERATOR_MAP)
        _apply_map(normalized, "panInfo.panStatus", _KYC_PAN_STATUS_MAP)

    elif scene == "account":
        _apply_map(normalized, "accountStatus.isAccountDeleted", _ACCOUNT_DELETED_MAP)
        for field in ["accountFrozenStatus", "withdrawalFrozenStatus", "tradingFrozenStatus"]:
            _apply_map(normalized, f"accountStatus.{field}", _ACCOUNT_FROZEN_STATUS_MAP)

    elif scene == "asset":
        _apply_map(normalized, "userInfo.isTransferFreeze", _ASSET_TRANSFER_FREEZE_MAP)

    elif scene == "p2p":
        # 布尔字段 → Yes/No
        for field in ["isP2PBlacklist", "emailLinked", "tradingPasswordEnabled"]:
            _apply_map(normalized, f"p2pUserInfo.{field}", _BOOL_YES_NO)
            _apply_map(normalized, field, _BOOL_YES_NO)
        # orderStatus / appealStatus 英文 → 中文
        _apply_map(normalized, "p2pOrderInfo.orderStatus", _P2P_ORDER_STATUS_MAP)
        _apply_map(normalized, "p2pOrderInfo.appealStatus", _P2P_APPEAL_STATUS_MAP)
        # 扁平化: P2P rules 使用 flat 字段名, MCP 返回嵌套结构
        normalized = _flatten_p2p(normalized)
        # 扁平化后再处理顶层字段 (如果数据本身就是 flat 结构)
        _apply_map(normalized, "orderStatus", _P2P_ORDER_STATUS_MAP)
        if normalized.get("appealStatus") not in ("Appeal", "Appeal Done", "Normal"):
            _apply_map(normalized, "appealStatus", _P2P_APPEAL_STATUS_MAP)

    elif scene == "deposit":
        _apply_map(normalized, "assetDeposit.status", _DEPOSIT_STATUS_MAP)

    elif scene == "withdraw":
        _apply_map(normalized, "frontWithdrawalRecord.status", _WITHDRAWAL_FRONT_STATUS_MAP)

    return normalized


def _flatten_p2p(data: dict) -> dict:
    """
    P2P 规则使用 flat 字段名 (e.g. orderStatus, isP2PBlacklist),
    但 MCP 返回嵌套结构 (p2pUserInfo.isP2PBlacklist, p2pOrderInfo.orderStatus)。
    将嵌套字段提升到顶层, 原始嵌套结构保留 (双路兼容)。
    """
    for sub_key in ["p2pUserInfo", "p2pOrderInfo"]:
        sub = data.get(sub_key)
        if isinstance(sub, dict):
            for k, v in sub.items():
                if k not in data:  # 不覆盖已存在的顶层字段
                    data[k] = v
    return data


# ════════════════════════════════════════════════════════════
# 字段解析 & 匹配
# ════════════════════════════════════════════════════════════

def resolve_field(data: dict, dotted_path: str) -> Any:
    """
    从嵌套 dict 中按点分路径取值。

    e.g. resolve_field(data, "accountVerifyInfo.verificationType")
         → data["accountVerifyInfo"]["verificationType"]
    """
    obj = data
    for part in dotted_path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
        if obj is None:
            return None
    return obj


def _match_single_condition(data_value: Any, rule_value: Any, data: dict) -> bool:
    """
    单条件匹配:
    - rule_value 是 list    → data_value ∈ list (IN 匹配)
    - rule_value 是 dict    → 运算符匹配 (op: contains/not_contains/</>=/ !=/ not_in)
    - rule_value 是标量     → 精确匹配 (== )
    """
    # ---- 运算符对象 ----
    if isinstance(rule_value, dict):
        op = rule_value.get("op", "")

        # 动态引用: 比较另一个字段
        if "ref" in rule_value:
            ref_val = resolve_field(data, rule_value["ref"])
            if ref_val is None or data_value is None:
                return False
            try:
                dv = float(data_value)
                rv = float(ref_val)
            except (ValueError, TypeError):
                return False
            return _compare_op(op, dv, rv)

        target = rule_value.get("value")

        if op == "contains":
            return _op_contains(data_value, target)

        if op == "not_contains":
            return not _op_contains(data_value, target)

        if op == "not_in":
            if isinstance(target, list):
                return data_value not in target
            return data_value != target

        if op == "not_in_known_reasons":
            # 特殊: ekycReviewFailedReason 不在已知列表中
            return True  # fallback —— 由上层按优先级排序, 此规则放最后

        if op == "==_userId":
            # 特殊: 等于当前 userId, 由调用方注入
            return True  # 需要在 match_rules 外部处理

        if op in ("<", "<=", ">", ">=", "!=", "=="):
            try:
                # 先尝试日期比较
                dv = _parse_comparable(data_value)
                rv = _parse_comparable(target)
                return _compare_op(op, dv, rv)
            except (ValueError, TypeError):
                return False

        if op == "desc":
            # 描述性条件, 无法精确匹配, skip
            return True

        logger.warning(f"[RuleMatcher] unknown op: {op}")
        return False

    # ---- 数组 IN ----
    if isinstance(rule_value, list):
        return data_value in rule_value

    # ---- 精确匹配 (含类型宽松) ----
    if rule_value == data_value:
        return True

    # 字符串 vs 数字宽松比较
    if isinstance(rule_value, (int, float)) and isinstance(data_value, str):
        try:
            return rule_value == float(data_value)
        except (ValueError, TypeError):
            pass
    if isinstance(data_value, (int, float)) and isinstance(rule_value, str):
        try:
            return float(rule_value) == float(data_value)
        except (ValueError, TypeError):
            pass

    # bool vs string
    if isinstance(data_value, bool) and isinstance(rule_value, str):
        return _BOOL_YES_NO.get(data_value) == rule_value
    if isinstance(rule_value, bool) and isinstance(data_value, str):
        return _BOOL_YES_NO.get(rule_value) == data_value

    return False


def _op_contains(data_value: Any, target: Any) -> bool:
    """
    contains 语义:
    - target 是 list → 任一元素出现在 data_value 中
    - target 是 str → target 是 data_value 的子串
    """
    if data_value is None:
        return False
    dv_str = str(data_value)
    if isinstance(target, list):
        return any(str(t) in dv_str for t in target)
    return str(target) in dv_str


def _parse_comparable(val: Any) -> Any:
    """将值转为可比较类型 (数字 或 datetime)"""
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        # 尝试 ISO date
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
        return float(val)
    return val


def _compare_op(op: str, left: Any, right: Any) -> bool:
    """执行比较运算"""
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "!=":
        return left != right
    if op == "==":
        return left == right
    return False


# ════════════════════════════════════════════════════════════
# 规则匹配主逻辑
# ════════════════════════════════════════════════════════════

def match_rules(data: dict, rules_list: List[dict]) -> Optional[dict]:
    """
    遍历规则列表, 返回第一条所有条件均满足的规则。

    跳过的条件:
    - _semantic: 需要 LLM 语义判断, 不在此处匹配
    - _complex: 复杂组合条件, 需要特殊代码处理
    - _fallback: 兜底规则, 放到最后

    返回: 匹配的规则 dict, 或 None
    """
    fallback_rule = None
    semantic_candidates = []

    for rule in rules_list:
        conditions = rule.get("rules", {})

        # 兜底规则: 所有其他规则不匹配时返回
        if "_fallback" in conditions:
            fallback_rule = rule
            continue

        # 空条件 = 兜底
        if not conditions or conditions == {}:
            fallback_rule = fallback_rule or rule
            continue

        has_semantic = "_semantic" in conditions or "_complex" in conditions
        all_non_semantic_matched = True
        non_semantic_count = 0

        for field, expected in conditions.items():
            # 跳过语义/复杂条件
            if field.startswith("_"):
                continue

            non_semantic_count += 1
            actual = resolve_field(data, field)
            if not _match_single_condition(actual, expected, data):
                all_non_semantic_matched = False
                break

        if not all_non_semantic_matched:
            continue

        # 所有非语义条件都匹配
        if has_semantic:
            # 有语义条件: 记录为候选, 优先让纯条件匹配的规则胜出
            semantic_candidates.append(rule)
            continue

        if non_semantic_count > 0:
            return rule

    # 如果有语义候选但无纯条件匹配, 返回第一个语义候选 (需 LLM 在上层做进一步判断)
    if semantic_candidates:
        return semantic_candidates[0]

    return fallback_rule


# ════════════════════════════════════════════════════════════
# 规则加载
# ════════════════════════════════════════════════════════════

_SCENE_TO_RULES_FILE = {
    "p2p": "ptp_rules",
    "deposit": "deposit_rules",
    "withdraw": "withdrawal_rules",
    "account": "account_rules",
    "kyc": "kyc_rules",
    "asset": "asset_rules",
}

_RULES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompt")


def _load_rules_from_file(scene: str) -> Optional[List[dict]]:
    """从本地 prompt 文件加载规则 JSON"""
    filename = _SCENE_TO_RULES_FILE.get(scene)
    if not filename:
        return None
    filepath = os.path.join(_RULES_DIR, filename)
    if not os.path.exists(filepath):
        logger.warning(f"[RuleMatcher] rules file not found: {filepath}")
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[RuleMatcher] failed to load rules: {filepath}, err={e}")
        return None


async def load_rules(scene: str) -> Optional[List[dict]]:
    """
    加载场景规则:
    1. 优先从 MCP Prompt Server (Redis → 本地缓存) 获取
    2. 降级从本地 prompt 文件加载
    """
    filename = _SCENE_TO_RULES_FILE.get(scene)
    if not filename:
        return None

    try:
        from mcp.mcp_http_client import mcp_client
        raw = await mcp_client.get_prompt(filename)
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.debug(f"[RuleMatcher] MCP prompt not available for {filename}: {e}")

    return _load_rules_from_file(scene)


# ════════════════════════════════════════════════════════════
# 答案后处理
# ════════════════════════════════════════════════════════════

def render_answer(answer: Any, mcp_data: dict) -> str:
    """
    渲染答案模板:
    1. 替换 {{field}} 模板变量
    2. 处理结构化答案 (list of {type, content/url})
    """
    if isinstance(answer, list):
        # 结构化答案: [{type: "text", content: "..."}, {type: "image", url: "..."}]
        parts = []
        for item in answer:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(_render_template(item.get("content", ""), mcp_data))
                elif item.get("type") == "image":
                    parts.append(f"![image]({item.get('url', '')})")
            else:
                parts.append(str(item))
        return "\n".join(parts)

    if isinstance(answer, str):
        return _render_template(answer, mcp_data)

    return str(answer)


def _render_template(text: str, data: dict) -> str:
    """替换 {{field.path}} 模板变量"""
    def replacer(m):
        path = m.group(1).strip()
        val = resolve_field(data, path)
        return str(val) if val is not None else ""

    return re.sub(r"\{\{(.+?)\}\}", replacer, text)


# ════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════

async def try_rule_match(scene: str, mcp_data: dict) -> Optional[Dict[str, Any]]:
    """
    规则匹配主入口。

    Args:
        scene: 场景标识 (p2p / deposit / withdraw / account / kyc / asset)
        mcp_data: MCP 工具返回的 data 字段 (已经过 _clean_data 去 null)

    Returns:
        匹配成功: {"matched": True, "rule_id": "K1", "answer": "...", "question": "...", "has_semantic": bool}
        匹配失败: None
    """
    if not mcp_data or not scene:
        return None

    rules_list = await load_rules(scene)
    if not rules_list:
        logger.info(f"[RuleMatcher] no rules loaded for scene={scene}")
        return None

    # 归一化 MCP 数据
    normalized = normalize_mcp_data(scene, mcp_data)
    logger.debug(f"[RuleMatcher] normalized data for scene={scene}: {json.dumps(normalized, ensure_ascii=False, default=str)[:500]}")

    # 匹配
    matched_rule = match_rules(normalized, rules_list)
    if not matched_rule:
        return None

    rule_id = matched_rule.get("id", "unknown")
    raw_answer = matched_rule.get("answer", "")
    question = matched_rule.get("question", "")
    conditions = matched_rule.get("rules", {})
    has_semantic = "_semantic" in conditions or "_complex" in conditions
    is_fallback = "_fallback" in conditions or conditions == {}

    # 渲染答案模板
    final_answer = render_answer(raw_answer, normalized)

    logger.info(
        f"[RuleMatcher] matched rule={rule_id}, scene={scene}, "
        f"question={question}, has_semantic={has_semantic}, is_fallback={is_fallback}"
    )

    return {
        "matched": True,
        "rule_id": rule_id,
        "question": question,
        "answer": final_answer,
        "has_semantic": has_semantic,
        "is_fallback": is_fallback,
    }
