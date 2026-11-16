"""发布守卫：计算与落库分开，发布中断不得污染上一份完整结果。

一次批次先在内存里把全部判定、账目与导出文本算齐（prepare 阶段），
最后才一次性写库（commit 阶段）。提交前任何一步抛错都直接冒泡，
SQLite 里上一条批次保持原样，版本序号也不前进，导出仍指向旧结果。

同输入重跑命中批次键时整体短路，连 version_seq 都不取，保证不新增改接记录。
"""

from __future__ import annotations

from app import errors


class PublishInterrupted(errors.FieldmapError):
    """模拟发布中断：发生在落库之前，用于验证旧结果完整保留。"""

    status = 500
    code = "PUBLISH_INTERRUPTED"
    label = "发布中断"


def assert_can_commit(run: dict, fail_before_commit: bool) -> None:
    """落库前的最后一道闸；测试可通过 fail_before_commit 模拟中断。"""
    if fail_before_commit:
        raise PublishInterrupted(
            "发布在落库前中断，上一份批次结果保持不变",
            detail={"run_id": run.get("run_id"), "reason": "PUBLISH_INTERRUPTED"},
        )
