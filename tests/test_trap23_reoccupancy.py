"""TRAP-23：连续两次改名后过渡列名被别的身份占用。

- 老报表按最早名字、中间登记按过渡名字取数，都不能被悄悄接到新占用者；
- 已按当前列名登记的新任务直连，必须改接的任务给出 SWITCH；
- 别名仍可达的消费方可以保留旧名；
- 同一登记重跑不新增改接记录；发布中断保留上一份完整结果与全部导出。
"""

from __future__ import annotations

import csv
import io

import pytest

from app import store
from app.modules.m1_intake import service as intake
from app.modules.m2_types import service as types
from app.modules.m4_mapping import (
    disposition,
    reoccupancy,
    rename,
    service as map_service,
)
from app.modules.m6_batches import publish, service as batch_service

CHAIN = {
    "old_file": "schema_chain_v2.sql",
    "new_file": "schema_chain_v3.sql",
    "refs_file": "refs_chain.json",
    "base_file": "schema_chain_v1.sql",
}


def _snapshots():
    base = types.prepare(intake.ingest("schema_chain_v1.sql"))
    old = types.prepare(intake.ingest("schema_chain_v2.sql"))
    new = types.prepare(intake.ingest("schema_chain_v3.sql"))
    return base, old, new


def _graph_and_owners(base, old, new):
    graph = rename.merge_edges(
        rename.build_edges(base["fields"], old["fields"]),
        rename.build_edges(old["fields"], new["fields"]),
    )
    owners = [map_service.owner_index(snapshot["fields"])
              for snapshot in (base, old, new)]
    return graph, owners


def test_rename_chain_still_resolves_without_reoccupancy():
    """无占用时，最早名字沿两跳链解析到最终名字（TRAP-22 行为不回退）。"""
    base, old, new = _snapshots()
    graph, _ = _graph_and_owners(base, old, new)
    resolved = rename.resolve(graph, "dim_shipment", "track_code")
    assert resolved["canonical"] == "waybill_code"
    assert resolved["path"] == ["track_code", "tracking_no", "waybill_code"]
    assert resolved["hops"] == 2


def test_chain_audit_flags_reoccupied_transitional_name():
    """链上的过渡名字 tracking_no 同时属于 fid=5002 与 fid=5004，审计必须拦下。"""
    base, old, new = _snapshots()
    graph, owners = _graph_and_owners(base, old, new)
    audit = reoccupancy.chain_identity_audit(graph, "dim_shipment",
                                             "track_code", owners)
    assert audit["blocked"] is True
    assert audit["reason"] == "NAME_REOCCUPIED"
    occupied_names = {item["name"] for item in audit["occupied"]}
    assert "tracking_no" in occupied_names


def test_legacy_name_is_not_silently_rebound():
    """最早名字 track_code 不允许解析到新占用者，必须进断链。"""
    base, old, new = _snapshots()
    refs = map_service.load_refs("refs_chain.json")
    graph, owners = _graph_and_owners(base, old, new)
    resolution = map_service.resolve(refs["consumers"], old["fields"],
                                     new["fields"], graph, version_owners=owners)
    broken = {(item["consumer"], item["column"]): item
              for item in resolution["broken"]}
    legacy = broken[("ads.rpt_shipment_legacy", "track_code")]
    assert legacy["via"] == "rebound"
    assert legacy["reason"] == "NAME_REOCCUPIED"
    assert legacy["field_id"] is None


def test_transitional_name_consumer_must_stop():
    """按过渡名 tracking_no 登记的中间视图，名字已被 fid=5004 占用，判停下。"""
    base, old, new = _snapshots()
    refs = map_service.load_refs("refs_chain.json")
    graph, owners = _graph_and_owners(base, old, new)
    resolution = map_service.resolve(refs["consumers"], old["fields"],
                                     new["fields"], graph, version_owners=owners)
    broken = {(item["consumer"], item["column"]): item
              for item in resolution["broken"]}
    mid = broken[("dw.mv_shipment_mid", "tracking_no")]
    assert mid["reason"] == "NAME_REOCCUPIED"

    rows = disposition.build_dispositions(resolution)
    actions = {row["consumer"]: row["action"] for row in rows}
    assert actions["dw.mv_shipment_mid"] == disposition.STOP
    assert actions["ads.rpt_shipment_legacy"] == disposition.STOP


def test_current_name_task_and_clean_view_dispositions():
    base, old, new = _snapshots()
    refs = map_service.load_refs("refs_chain.json")
    graph, owners = _graph_and_owners(base, old, new)
    resolution = map_service.resolve(refs["consumers"], old["fields"],
                                     new["fields"], graph, version_owners=owners)
    rows = disposition.build_dispositions(resolution)
    actions = {row["consumer"]: row["action"] for row in rows}
    # 已按当前列名 waybill_code 登记，别名可达同一身份 -> 旧名可继续用
    assert actions["dw.task_waybill_current"] == disposition.KEEP_OLD
    # 只引用未改名字段 -> 必须按当前列名取数
    assert actions["dw.mv_shipment_city"] == disposition.SWITCH
    summary = disposition.summarize(rows)
    assert summary == {"consumers": 4, "keep_old": 1, "switch": 1, "stop": 2}


def test_ref_account_still_balanced_under_reoccupancy():
    base, old, new = _snapshots()
    refs = map_service.load_refs("refs_chain.json")
    graph, owners = _graph_and_owners(base, old, new)
    resolution = map_service.resolve(refs["consumers"], old["fields"],
                                     new["fields"], graph, version_owners=owners)
    total = sum(len(item["refs"]) for item in refs["consumers"])
    assert resolution["reachable"] + resolution["broken_count"] == total
    assert resolution["broken_count"] == 2


def test_chain_run_via_batch_service(client):
    run = batch_service.execute(**CHAIN)
    payload = run["dispositions"]
    actions = {row["consumer"]: row["action"] for row in payload["rows"]}
    assert actions == {
        "ads.rpt_shipment_legacy": "STOP_REVIEW",
        "dw.mv_shipment_mid": "STOP_REVIEW",
        "dw.task_waybill_current": "KEEP_OLD_NAME",
        "dw.mv_shipment_city": "SWITCH_TO_CURRENT",
    }
    # 断链引用带着占用原因码
    reasons = {item.get("reason") for item in run["resolution"]["broken"]}
    assert "NAME_REOCCUPIED" in reasons


def test_rerun_same_registration_adds_no_row(client):
    first = batch_service.execute(**CHAIN)
    count_after_first = store.count_runs()
    again = batch_service.execute(**CHAIN)
    assert again["run_id"] == first["run_id"]
    assert again["reused"] is True
    assert store.count_runs() == count_after_first


def test_publish_interruption_keeps_previous_run_and_exports(client):
    from app.modules.m7_migration import service as migration

    previous = store.latest_run()
    previous_exports = {
        "spec": migration.spec_markdown(previous),
        "fields": migration.fields_csv_text(previous),
        "refs": migration.refs_csv_text(previous),
        "ledger": migration.ledger_csv_text(previous),
    }
    seq_before = store.current_version_seq()
    count_before = store.count_runs()

    with pytest.raises(publish.PublishInterrupted):
        batch_service.execute(**CHAIN, params={"wave": "would-break"},
                              fail_before_commit=True)

    # 没有新增批次，序号不前进，上一份结果原样可读
    assert store.count_runs() == count_before
    assert store.current_version_seq() == seq_before
    survivor = store.latest_run()
    assert survivor["run_id"] == previous["run_id"]
    assert migration.spec_markdown(survivor) == previous_exports["spec"]
    assert migration.fields_csv_text(survivor) == previous_exports["fields"]
    assert migration.refs_csv_text(survivor) == previous_exports["refs"]
    assert migration.ledger_csv_text(survivor) == previous_exports["ledger"]


def test_publish_interruption_endpoint_returns_500(client):
    count_before = store.count_runs()
    response = client.post("/api/runs",
                           json={**CHAIN, "fail_before_commit": True})
    assert response.status_code == 500
    assert response.json()["error"] == "PUBLISH_INTERRUPTED"
    assert store.count_runs() == count_before


def test_disposition_api_matches_export_and_page(client):
    batch_service.execute(**CHAIN)
    api_rows = client.get("/api/dispositions").json()["rows"]
    api_actions = {row["consumer"]: row["action"] for row in api_rows}

    csv_text = client.get("/api/export/dispositions.csv").text
    csv_rows = list(csv.DictReader(io.StringIO(csv_text)))
    csv_actions = {row["consumer"]: row["action"] for row in csv_rows}
    assert csv_actions == api_actions
    # 依据列非空，与页面证据同源
    assert all(row["evidence"] for row in csv_rows)

    page = client.get("/mapping").text
    for consumer in api_actions:
        assert consumer in page
    assert "消费方处置" in page


def test_spec_markdown_contains_disposition_section(client):
    from app.modules.m7_migration import service as migration

    run = batch_service.execute(**CHAIN)
    text = migration.spec_markdown(run)
    assert "## 6 消费方处置" in text
    # 迁移单处置表用消费方处置码，逐引用的 NAME_REOCCUPIED 留在引用账
    assert "STOP_REVIEW" in text
    assert "KEEP_OLD_NAME" in text
    assert "SWITCH_TO_CURRENT" in text
    refs_csv = migration.refs_csv_text(run)
    assert "NAME_REOCCUPIED" in refs_csv


def test_disposition_module_handles_empty_resolution():
    rows = disposition.build_dispositions({"resolved": [], "broken": []})
    assert rows == []
    assert disposition.summarize(rows) == {
        "consumers": 0, "keep_old": 0, "switch": 0, "stop": 0,
    }


def test_is_reoccupied_helper():
    owners = [
        {("t", "a"): "1"},
        {("t", "a"): "1"},
        {("t", "a"): "2"},
    ]
    assert reoccupancy.is_reoccupied(owners, "t", "a", "1") is True
    assert reoccupancy.is_reoccupied(owners, "t", "a", "2") is False
    assert reoccupancy.is_reoccupied(owners, "t", "missing", "1") is False


def test_reason_codes_registered_with_break_severity():
    from app import reasons

    for code in ("NAME_REOCCUPIED", "CONSUMER_STOP", "CONSUMER_SWITCH"):
        assert code in reasons.CODES
        assert reasons.severity(code) == "break"
    assert reasons.severity("CONSUMER_KEEP_OLD") == "warn"


def test_default_seed_run_has_dispositions(run):
    """默认样例批次同样产出三档处置，且与引用账守恒一致。"""
    payload = run["dispositions"]
    summary = payload["summary"]
    assert summary["consumers"] == 7
    assert summary["keep_old"] + summary["switch"] + summary["stop"] == 7
    # 含断链的消费方必须全部判停下
    broken_consumers = {item["consumer"] for item in run["resolution"]["broken"]}
    stopped = {row["consumer"] for row in payload["rows"]
               if row["action"] == "STOP_REVIEW"}
    assert broken_consumers <= stopped
    # 别名仍可达的 order_no 消费方保留旧名
    keep = {row["consumer"] for row in payload["rows"]
            if row["action"] == "KEEP_OLD_NAME"}
    assert "dw.mv_order_daily" in keep
