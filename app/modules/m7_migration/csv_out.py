"""CSV 导出：字段账、引用账、运行清单。

字段身份按原样字符串写出，大整数不进 float，前后导零不丢。
"""

from __future__ import annotations

import csv
import io
import json

FIELD_HEADER = [
    "field_id", "table", "old_name", "new_name", "old_type", "new_type",
    "change", "type_detail", "required_change", "reader", "writer", "verdict",
    "primary_reason", "bucket", "ref_count", "line_old", "line_new",
]

REF_HEADER = ["consumer", "kind", "ref", "table", "column", "via", "field_id", "reason"]

DISPOSITION_HEADER = [
    "consumer", "kind", "action", "reason", "ref_total", "alias_count",
    "direct_count", "blocking_count", "evidence",
]


def _buffer() -> tuple[io.StringIO, "csv.writer"]:
    buffer = io.StringIO()
    return buffer, csv.writer(buffer, lineterminator="\n")


def fields_csv(rows: list[dict]) -> str:
    buffer, writer = _buffer()
    writer.writerow(FIELD_HEADER)
    for row in rows:
        writer.writerow([
            str(row.get("field_id", "")),
            row.get("table") or "",
            row.get("old_name") or "",
            row.get("new_name") or "",
            row.get("old_type") or "",
            row.get("new_type") or "",
            row.get("change") or "",
            row.get("type_detail") or "",
            row.get("required_change") or "",
            "Y" if row.get("reader_ok") else "N",
            "Y" if row.get("writer_ok") else "N",
            row.get("verdict") or "",
            row.get("primary") or "",
            row.get("bucket") or "",
            str(row.get("ref_count", 0)),
            str(row.get("line_old") or ""),
            str(row.get("line_new") or ""),
        ])
    return buffer.getvalue()


def refs_csv(run: dict) -> str:
    resolution = run.get("resolution") or {}
    buffer, writer = _buffer()
    writer.writerow(REF_HEADER)
    for item in resolution.get("resolved") or []:
        writer.writerow([item["consumer"], item["kind"], item["ref"], item["table"],
                         item["column"], item["via"], str(item["field_id"] or ""),
                         item.get("reason") or ""])
    for item in resolution.get("broken") or []:
        writer.writerow([item["consumer"], item["kind"], item["ref"], item["table"],
                         item["column"], item.get("via") or "broken", "",
                         item.get("reason") or "REF_BROKEN"])
    return buffer.getvalue()


def _evidence_text(evidence: list[dict]) -> str:
    """把逐条依据压成单元格文本；动作与依据和页面同源。"""
    parts = []
    for note in evidence or []:
        ref = note.get("ref") or "—"
        detail = note.get("detail") or ""
        parts.append(f"{ref}[{note.get('via') or '—'}]:{detail}")
    return " | ".join(parts)


def dispositions_csv(run: dict) -> str:
    """消费方处置导出：与 /mapping 页面和 /api/dispositions 共用同一份结论。"""
    payload = run.get("dispositions") or {}
    buffer, writer = _buffer()
    writer.writerow(DISPOSITION_HEADER)
    for row in payload.get("rows") or []:
        writer.writerow([
            row.get("consumer", ""),
            row.get("kind", ""),
            row.get("action", ""),
            row.get("reason", ""),
            str(row.get("ref_total", 0)),
            str(row.get("alias_count", 0)),
            str(row.get("direct_count", 0)),
            str(row.get("blocking_count", 0)),
            _evidence_text(row.get("evidence") or []),
        ])
    return buffer.getvalue()


def ledger_csv(ledger: dict) -> str:
    buffer, writer = _buffer()
    writer.writerow(["item", "value"])
    buckets = ledger.get("buckets") or {}
    for name in ("old_total", "unchanged", "renamed", "retyped", "required",
                 "conflict", "deleted", "added", "new_total"):
        value = buckets.get(name, ledger.get("fields", {}).get(name, 0))
        writer.writerow([name, value])
    refs = ledger.get("refs") or {}
    for name in ("refs_total", "reachable", "broken", "aliased"):
        writer.writerow([name, refs.get(name, 0)])
    return buffer.getvalue()


def manifest_json(manifest: dict) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
