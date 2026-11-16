"""改名链上的身份核验：连续两次改名后，过渡列名可能已被别的身份占用。

朴素实现只按列名顺着改名链走，最早版本的名字会被悄悄接到新占用者上，
老报表因此读到语义完全不同的新字段。这里把「名字在每个版本里属于谁」
摆到台面上，链上任何一跳的名字换了身份，整条链都判不可自动改接。

规则只吃快照字段与改名边，不碰存储与页面，保证可单测、可复算。
"""

from __future__ import annotations

from app.modules.m4_mapping import rename


def name_owner_index(fields: list[dict]) -> dict[tuple[str, str], str]:
    """(表小写, 列名小写) -> field_id；同表同名折叠时采信层已保证只剩一个。"""
    return {
        (field["table"].lower(), field["name"].lower()): field["field_id"]
        for field in fields
    }


def chain_identity_audit(edges: dict[str, set[str]], table: str, start_name: str,
                         version_owners: list[dict[tuple[str, str], str]]) -> dict:
    """沿改名链走一遍，逐跳核验每个名字在各版本里的身份归属。

    version_owners：按版本先后排列的 (表, 列名) -> field_id 索引，
    至少包含链头所在旧版本与链尾所在新版本，中间版本可选。

    返回字段：
      blocked   链上是否出现身份被占用/断链，True 时禁止自动改接
      reason    NAME_REOCCUPIED / 既有链原因 / None
      path      解析出的名字链
      hops     跳数
      evidence  逐跳证据，页面与导出共用同一份依据
    """
    chain = rename.resolve(edges, table, start_name)
    path: list[str] = chain["path"]
    evidence: list[dict] = []
    occupied: list[dict] = []

    # 每个名字在各版本里登记过的身份；名字在某个版本缺席则该版本无记录
    for name in path:
        key = (table.lower(), name.lower())
        owners = [owners.get(key) for owners in version_owners]
        seen = sorted({owner for owner in owners if owner is not None})
        evidence.append({"name": name, "owners": seen})
        if len(seen) > 1:
            occupied.append({"name": name, "field_ids": seen})

    blocked = bool(occupied) or chain["cycle"] or chain["ambiguous"]
    if occupied:
        reason = "NAME_REOCCUPIED"
    else:
        reason = chain["reason"]
    return {
        "blocked": blocked,
        "reason": reason,
        "path": path,
        "canonical": chain["canonical"],
        "hops": chain["hops"],
        "cycle": chain["cycle"],
        "ambiguous": chain["ambiguous"],
        "occupied": occupied,
        "evidence": evidence,
    }


def is_reoccupied(version_owners: list[dict[tuple[str, str], str]],
                  table: str, name: str, identity_field_id: str | None) -> bool:
    """单点判断：这个名字在新版本里是否落到了与给定身份不同的字段上。"""
    if not version_owners:
        return False
    current_owner = version_owners[-1].get((table.lower(), name.lower()))
    return current_owner is not None and current_owner != identity_field_id
