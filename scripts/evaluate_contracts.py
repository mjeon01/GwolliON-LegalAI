#!/usr/bin/env python3
"""Separate annotated-field recovery from curated clause-warning regression."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mvp.analysis import extract, evaluate
from mvp.corpus import DEFAULT_DB
from mvp.extraction import LABELS as FIELD_PATTERNS, blocks_from_text, rules_extract
from mvp.schemas import AnalyzeRequest
from scripts.inspect_downloaded_data import json_members, read_json

LABELS = {"임금액": "wage", "임금지급일": "payment_date", "임금지급방법": "payment_method", "근로시간": "work_hours", "근로계약기간": "period", "근무장소": "workplace", "담당업무": "job_description", "휴일": "holiday", "휴가": "annual_leave", "휴게시간": "break_time", "근로일": "work_days"}


def field_benchmark():
    directory = ROOT / "data/계약법률문서/Validation"
    counts, fields, details = Counter(), {}, []
    with closing(sqlite3.connect(f"file:{DEFAULT_DB}?mode=ro", uri=True)) as db:
        training_hashes = {r[0] for r in db.execute("SELECT DISTINCT content_hash FROM records WHERE split='Training'")}
    for label_path in sorted((directory / "02.라벨링데이터").glob("*.zip")):
        suffix = label_path.name.split("_", 1)[-1]
        source_path = next((directory / "01.원천데이터").glob("*_" + suffix))
        with zipfile.ZipFile(source_path) as sources, zipfile.ZipFile(label_path) as annotations:
            originals = {Path(i.filename).stem: i for i in json_members(sources)}
            for item in json_members(annotations):
                label = read_json(annotations, item)["document"]
                category = label["metadata"]["file_info"]["document_category"]["detail_category"]
                if category not in {"근로(고용)계약서", "아르바이트계약서", "연봉계약서"}:
                    continue
                counts["selected_documents"] += 1
                source = read_json(sources, originals[Path(item.filename).stem])["document"]
                body = "\n".join(str(c["text"]) for section in source.get("sub_documents", []) for c in section.get("contents", []) if isinstance(c, dict) and c.get("text"))
                if hashlib.sha256(body.encode()).hexdigest() in training_hashes:
                    counts["excluded_exact_training_duplicate"] += 1
                    continue
                found = rules_extract(blocks_from_text(body), "employment")
                orders = Counter(str(section.get("sort_order")) for section in source.get("sub_documents", []))
                by_line = {str(section.get("sort_order")): "\n".join(str(c["text"]) for c in section.get("contents", []) if isinstance(c, dict) and c.get("text")).strip() for section in source.get("sub_documents", []) if orders[str(section.get("sort_order"))] == 1}
                tagged, missed, span_missed = set(), set(), set()
                for section in label.get("sections", []):
                    original = by_line.get(str(section.get("format", {}).get("position", {}).get("line")))
                    if not original or original != str(section.get("content", {}).get("description", "")).strip():
                        counts["unmatched_annotation_sections"] += 1
                        continue
                    for tag in section.get("content", {}).get("content_labels", []):
                        canonical = "".join(str(tag).split())
                        if canonical not in LABELS:
                            continue
                        key = LABELS[canonical]
                        tagged.add(key)
                        counts["mapped_field_spans"] += 1
                        matched = bool(re.search(FIELD_PATTERNS[key], original))
                        counts["detected_field_mentions"] += matched
                        if not matched:
                            span_missed.add(key)
                for key in tagged:
                    stat = fields.setdefault(key, Counter())
                    stat["tagged_documents"] += 1
                    stat["mention_detected_documents"] += bool(re.search(FIELD_PATTERNS[key], body))
                    stat["value_extracted_documents"] += bool(found[key])
                    if not re.search(FIELD_PATTERNS[key], body):
                        missed.add(key)
                counts["evaluated_documents"] += 1
                counts["documents_with_unfilled_placeholders"] += bool(re.search(r"@(?:금액|날짜|주소)|\(\s*\)|년\s*월\s*일", body))
                details.append({"document_id": Path(item.filename).stem, "category": category, "tagged_fields": sorted(tagged), "missed_topic_spans_fields": sorted(span_missed), "missing_field_mentions": sorted(missed), "value_extracted_fields": sorted(k for k in tagged if found[k])})
    return {"method": "rules", "metric": "원문과 정확히 대응한 항목 라벨의 탐지 회수율과 값 추출 관찰 (법률 판단 정확도 아님)", "counts": dict(counts),
            "span_recovery": counts["detected_field_mentions"] / counts["mapped_field_spans"] if counts["mapped_field_spans"] else None,
            "fields": {k: dict(stat) for k, stat in fields.items()}, "documents": details,
            "limitations": ["전문가 검수된 불리함·위법 정답 라벨이 아님", "빈 서식에는 임금 라벨이 있어도 실제 금액을 추출하면 안 됨; 값 추출 건수는 정확도가 아닌 관찰값", "동일 원문 중복을 제외했지만 유사 양식 중복은 별도 검수 필요"]}


CASES = [
    ("normal_work", "employment", "worker", "", []),
    ("penalty", "employment", "worker", "퇴사하면 위약금 300만원을 지급한다.", ["penalty"]),
    ("deduction", "employment", "worker", "실수로 발생한 손해는 급여에서 공제한다.", ["wage_deduction"]),
    ("negated_penalty", "employment", "worker", "퇴사 위약금은 정하지 않는다.", []),
    ("mixed_no_space", "employment", "worker", "퇴사 위약금은 정하지 않는다.실수로 발생한 손해는 급여에서 공제한다.", ["wage_deduction"]),
    ("separate_allowance", "employment", "worker", "연장근로수당은 월급에 포함하지 않고 별도로 지급한다.", []),
    ("included_allowance", "employment", "worker", "월급에는 연장근로수당이 모두 포함되며 별도 수당은 지급하지 않는다.", ["included_allowance"]),
    ("leave_waiver", "employment", "worker", "근로자는 연차휴가를 일괄 포기한다.", ["leave_waiver"]),
    ("noncompete", "employment", "worker", "퇴사 후 동종업계 취업을 금지한다.", ["noncompete"]),
    ("unpaid_trial", "employment", "worker", "수습 기간의 실제 매장 업무는 무급으로 한다.", ["unpaid_trial"]),
    ("normal_lease", "lease", "tenant", "", []),
    ("conditional_return", "lease", "tenant", "보증금은 새 임차인이 구해지면 반환한다.", ["deposit_return"]),
    ("landlord_perspective", "lease", "landlord", "보증금은 새 임차인이 구해지면 반환한다.", []),
    ("repair_shift", "lease", "tenant", "노후로 인한 모든 수리비는 임차인이 부담한다.", ["repair_burden"]),
    ("registration_waiver", "lease", "tenant", "임차인은 전입신고를 하지 않는다.", ["registration_waiver"]),
    ("registration_allowed", "lease", "tenant", "임차인의 전입신고를 금지하지 않는다.", []),
    ("deposit_deduction", "lease", "tenant", "임대인은 보증금에서 수리비를 임의로 공제한다.", ["deposit_deduction"]),
    ("sale_advance", "sale", "buyer", "잔금 전액 지급 후 소유권 이전 등기를 한다.", ["sale_advance"]),
    ("sale_seller_perspective", "sale", "seller", "잔금 전액 지급 후 소유권 이전 등기를 한다.", []),
    ("sale_transfer_first", "sale", "seller", "소유권 등기를 먼저 이전하고 이후 잔금을 받는다.", ["sale_transfer_first"]),
    ("sale_defect_waiver", "sale", "buyer", "매도인은 모든 하자에 대한 책임을 지지 않는다.", ["sale_defect_waiver"]),
]


def clause_benchmark(engine="rules"):
    totals, cases = Counter(), []
    for identifier, kind, role, clause, expected in CASES:
        base = (ROOT / ("samples/employment-basic.txt" if kind == "employment" else "samples/lease-basic.txt")).read_text() if kind != "sale" else "부동산 매매계약서\n목적물: 가상시 가상로 10\n매매대금: 3억원\n잔금 지급일: 2026-11-01\n소유권 이전: 잔금 지급과 등기서류 제공은 동시에 이행한다."
        request = AnalyzeRequest(text=base + "\n" + clause, contract_type=kind, user_role=role, engine=engine, context={"document_complete": True, "event_date": "2026-10-11"})
        blocks, terms, metadata = extract(request)
        result = evaluate(request, blocks, terms, metadata, identifier, 1)
        observed = {f["issue_type"] for f in result["review"]["findings"]}
        gold = set(expected)
        totals["true_positive"] += len(observed & gold)
        totals["false_positive"] += len(observed - gold)
        totals["false_negative"] += len(gold - observed)
        cases.append({"id": identifier, "role": role, "expected": expected, "observed": sorted(observed), "pass": observed == gold, "verdict": result["review"]["verdict"]})
    tp, fp, fn = (totals[k] for k in ("true_positive", "false_positive", "false_negative"))
    return {"engine": engine, "cases": cases, "passed": sum(c["pass"] for c in cases), "total": len(cases), "counts": dict(totals),
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "limitations": ["개발자가 지정한 제한된 가상 회귀 사례; 실제 계약 정확도나 전문가 법률 평가를 의미하지 않음", "규칙 범위 밖의 누락과 일반화 성능은 별도 사례 수집·전문가 검수가 필요"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["rules", "ollama"], default="rules")
    args = parser.parse_args()
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "field_recovery": field_benchmark(), "clause_regression": clause_benchmark(args.engine)}
    target = ROOT / "var/evaluation/contracts.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"report": str(target.relative_to(ROOT)), "field_counts": report["field_recovery"]["counts"], "span_recovery": report["field_recovery"]["span_recovery"], "clause_cases_passed": report["clause_regression"]["passed"], "clause_cases_total": report["clause_regression"]["total"], "clause_failures": [c for c in report["clause_regression"]["cases"] if not c["pass"]]}, ensure_ascii=False))
