"""消费方处置判定：每个下游还能不能用旧名、何时必须改接、何时必须停下。

结论只认引用身份解析的结果，不按当前列名想当然：

- KEEP_OLD_NAME  全部引用都能经别名落到同一身份，旧名可继续使用，
                  但要建兼容视图；别名链断或名字被占用时不在此列。
- SWITCH         引用只认当前列名（名字还在、身份一致），必须改接到新名，
                  典型是登记里已经写了当前版本列名的新任务。
- STOP           任一引用断链、被别的身份占用、别名不安全或成环，
                  禁止静默改接，必须人工停下复核。

页面与导出共用本模块的同一份结论与证据，避免两处各说各话。
"""

from __future__ import annotations

# 处置动作（稳定字符串，进 API、页面与 CSV）
KEEP_OLD = "KEEP_OLD_NAME"
SWITCH = "SWITCH_TO_CURRENT"
STOP = "STOP_REVIEW"

# resolution 里的 via -> 处置语义
SAFE_ALIAS_VIA = {"alias"}
DIRECT_VIA = {"direct"}
# 这些 via 都意味着不能自动改接
BLOCKING_VIA = {
    "rebound",        # 名字还在但身份换了
    "deleted",        # 字段已删除
    "unsafe_alias",   # 改名同时换类型，别名不安全
    "unknown_name",   # 旧版本里就没有这个名字
    "cycle",          # 别名链成环
}

ACTION_REASON = {
    KEEP_OLD: "CONSUMER_KEEP_OLD",
    SWITCH: "CONSUMER_SWITCH",
    STOP: "CONSUMER_STOP",
}

ACTION_LABEL = {
    KEEP_OLD: "可继续用旧名（建别名视图）",
    SWITCH: "必须改接当前列名",
    STOP: "必须停下复核",
}


def _ref_action(item: dict) -> tuple[str, str]:
    """单条引用 -> (动作, 原因码)。"""
    via = item.get("via") or "unknown_name"
    if via in BLOCKING_VIA:
        return STOP, "CONSUMER_STOP"
    if via in SAFE_ALIAS_VIA:
        return KEEP_OLD, "CONSUMER_KEEP_OLD"
    if via in DIRECT_VIA:
        return SWITCH, "CONSUMER_SWITCH"
    return STOP, "CONSUMER_STOP"


def build_dispositions(resolution: dict) -> list[dict]:
    """把逐条引用汇总成每个消费方一条处置结论。

    一个消费方只要有一条阻断引用，整体即 STOP；否则有别名引用即 KEEP_OLD；
    全部直连当前列名才是 SWITCH。
    """
    grouped: dict[str, dict] = {}

    def _bucket(consumer: str, kind: str):
        return grouped.setdefault(consumer, {
            "consumer": consumer,
            "kind": kind,
            "refs": [],
            "actions": set(),
            "blocking_refs": [],
            "alias_refs": [],
            "direct_refs": [],
        })

    for item in resolution.get("resolved") or []:
        bucket = _bucket(item["consumer"], item.get("kind") or "task")
        action, _ = _ref_action(item)
        bucket["actions"].add(action)
        bucket["refs"].append(item)
        if action == KEEP_OLD:
            bucket["alias_refs"].append(item)
        elif action == SWITCH:
            bucket["direct_refs"].append(item)

    for item in resolution.get("broken") or []:
        bucket = _bucket(item["consumer"], item.get("kind") or "task")
        bucket["actions"].add(STOP)
        bucket["refs"].append(item)
        bucket["blocking_refs"].append(item)

    rows: list[dict] = []
    for consumer in sorted(grouped):
        bucket = grouped[consumer]
        if STOP in bucket["actions"]:
            action = STOP
        elif KEEP_OLD in bucket["actions"]:
            action = KEEP_OLD
        else:
            action = SWITCH
        rows.append({
            "consumer": consumer,
            "kind": bucket["kind"],
            "action": action,
            "reason": ACTION_REASON[action],
            "label": ACTION_LABEL[action],
            "ref_total": len(bucket["refs"]),
            "alias_count": len(bucket["alias_refs"]),
            "direct_count": len(bucket["direct_refs"]),
            "blocking_count": len(bucket["blocking_refs"]),
            "evidence": _evidence(bucket, action),
        })
    return rows


def _evidence(bucket: dict, action: str) -> list[dict]:
    """给出该结论的可追溯依据，页面表格与导出 CSV 共用。"""
    notes: list[dict] = []
    for item in bucket["blocking_refs"]:
        notes.append({
            "ref": item.get("ref"),
            "via": item.get("via") or "unknown_name",
            "detail": item.get("detail") or "引用断链，禁止静默改接",
            "field_id": item.get("field_id"),
            "new_name": item.get("new_name"),
        })
    for item in bucket["alias_refs"]:
        notes.append({
            "ref": item.get("ref"),
            "via": item.get("via"),
            "detail": item.get("detail") or "经别名链解析到同一身份",
            "field_id": item.get("field_id"),
            "new_name": item.get("new_name"),
        })
    for item in bucket["direct_refs"]:
        notes.append({
            "ref": item.get("ref"),
            "via": item.get("via"),
            "detail": item.get("detail") or "名字与身份均未变，按当前列名取数",
            "field_id": item.get("field_id"),
            "new_name": item.get("new_name"),
        })
    if not notes and action == SWITCH:
        notes.append({"ref": None, "via": "direct",
                      "detail": "登记已按当前版本列名，直接取数",
                      "field_id": None, "new_name": None})
    return notes


def summarize(rows: list[dict]) -> dict:
    return {
        "consumers": len(rows),
        "keep_old": sum(1 for row in rows if row["action"] == KEEP_OLD),
        "switch": sum(1 for row in rows if row["action"] == SWITCH),
        "stop": sum(1 for row in rows if row["action"] == STOP),
    }
