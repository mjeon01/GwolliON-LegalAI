#!/usr/bin/env python3
"""Inspect ZIP inventories and contract labels without extracting or printing text."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def shape(value: object, depth: int = 0) -> object:
    if depth >= 5:
        return type(value).__name__
    if isinstance(value, dict):
        return {str(k): shape(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        return {"type": "list", "sample_length": len(value), "sample_item": shape(value[0], depth + 1) if value else None}
    return type(value).__name__


def json_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    return [item for item in archive.infolist() if not item.is_dir() and not item.filename.startswith("__MACOSX/") and item.filename.lower().endswith(".json")]


def read_json(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> dict:
    if member.file_size > 16 * 1024 * 1024:
        raise ValueError("JSON entry exceeds the inspection size limit")
    obj = json.loads(archive.read(member).decode("utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError("Expected a JSON object")
    return obj


def inspect_contracts(data_root: Path) -> dict:
    report = {"splits": {}, "source_label_pairs_checked": 0}
    selected_categories = {"근로(고용)계약서", "아르바이트계약서"}
    ids_by_split = {}
    for split in ("Training", "Validation"):
        split_stats = {"label_documents": 0, "categories": {}, "pairing": {}, "employment": {}}
        categories = Counter()
        all_ids = set()
        for path in sorted((data_root / "계약법률문서" / split / "02.라벨링데이터").glob("*.zip")):
            with zipfile.ZipFile(path) as archive:
                for item in json_members(archive):
                    document = read_json(archive, item)["document"]
                    category = document["metadata"]["file_info"]["document_category"]["detail_category"]
                    categories[category] += 1
                    all_ids.add(Path(item.filename).stem)
        split_stats["label_documents"] = sum(categories.values())
        split_stats["categories"] = dict(categories)
        ids_by_split[split] = all_ids
        source_paths = list((data_root / "계약법률문서" / split / "01.원천데이터").glob("*고용계약.zip"))
        label_paths = list((data_root / "계약법률문서" / split / "02.라벨링데이터").glob("*고용계약.zip"))
        if len(source_paths) != 1 or len(label_paths) != 1:
            split_stats["employment"] = {"status": "employment_archive_not_found"}
        else:
            counters = Counter()
            employment_categories = Counter()
            labels = Counter()
            selected_labels = Counter()
            selected_field_documents = Counter()
            key_sets = {"source_document": set(), "label_document": set(), "source_section": set(), "label_section": set()}
            with zipfile.ZipFile(source_paths[0]) as source_zip, zipfile.ZipFile(label_paths[0]) as label_zip:
                sources = {Path(item.filename).stem: item for item in json_members(source_zip)}
                annotations = {Path(item.filename).stem: item for item in json_members(label_zip)}
                pairs = sorted(set(sources) & set(annotations))
                split_stats["pairing"] = {"source_count": len(sources), "label_count": len(annotations), "matched_stems": len(pairs), "source_only": len(set(sources) - set(annotations)), "label_only": len(set(annotations) - set(sources))}
                for document_id in pairs:
                    source = read_json(source_zip, sources[document_id])["document"]
                    label = read_json(label_zip, annotations[document_id])["document"]
                    key_sets["source_document"].update(source)
                    key_sets["label_document"].update(label)
                    category = label["metadata"]["file_info"]["document_category"]["detail_category"]
                    employment_categories[category] += 1
                    counters["selected_documents"] += category in selected_categories
                    source_sections = source.get("sub_documents", [])
                    label_sections = label.get("sections", [])
                    source_by_id = {str(s["id"]): s for s in source_sections}
                    order_counts = Counter(str(s.get("sort_order", "")) for s in source_sections)
                    source_by_order = {str(s.get("sort_order", "")): s for s in source_sections if order_counts[str(s.get("sort_order", ""))] == 1}
                    document_labels = set()
                    counters["source_sections"] += len(source_sections)
                    counters["label_sections"] += len(label_sections)
                    for section in source_sections:
                        key_sets["source_section"].update(section)
                        counters["source_nonnull_coordinates"] += section.get("coordinate") is not None
                        counters["source_text_contents"] += sum(bool(c.get("text")) for c in section.get("contents", []) if isinstance(c, dict))
                    for section in label_sections:
                        key_sets["label_section"].update(section)
                        content = section.get("content", {})
                        labels.update(str(tag) for tag in content.get("content_labels", []))
                        if category in selected_categories:
                            selected_labels.update(str(tag) for tag in content.get("content_labels", []))
                            document_labels.update(str(tag) for tag in content.get("content_labels", []))
                        counters["nonempty_label_descriptions"] += bool(content.get("description"))
                        counters["label_sections_with_line_position"] += bool(section.get("format", {}).get("position", {}).get("line"))
                        original = source_by_id.get(str(section["id"]))
                        if original is not None:
                            counters["matching_section_ids"] += 1
                            texts = [str(c["text"]) for c in original.get("contents", []) if isinstance(c, dict) and c.get("text") is not None]
                            counters["exact_text_pairs"] += str(content.get("description", "")).strip() == "\n".join(texts).strip()
                        line = str(section.get("format", {}).get("position", {}).get("line", ""))
                        positioned_source = source_by_order.get(line)
                        if positioned_source is not None:
                            counters["line_order_matches"] += 1
                            positioned_text = "\n".join(str(c["text"]) for c in positioned_source.get("contents", []) if isinstance(c, dict) and c.get("text") is not None).strip()
                            same_text = str(content.get("description", "")).strip() == positioned_text
                            counters["line_order_exact_text_pairs"] += same_text
                            if category in selected_categories:
                                counters["selected_line_order_matches"] += 1
                                counters["selected_line_order_exact_text_pairs"] += same_text
                        if category in selected_categories:
                            counters["selected_label_sections"] += 1
                    if category in selected_categories:
                        selected_field_documents.update(document_labels)
                report["source_label_pairs_checked"] += len(pairs)
            split_stats["employment"] = {"categories": dict(employment_categories), "counts": dict(counters), "label_counts": dict(labels.most_common()), "selected_label_counts": dict(selected_labels.most_common()), "selected_field_document_counts": dict(selected_field_documents.most_common()), "key_sets": {k: sorted(v) for k, v in key_sets.items()}}
        report["splits"][split] = split_stats
    report["training_validation_filename_overlap"] = len(ids_by_split.get("Training", set()) & ids_by_split.get("Validation", set()))
    report["filename_overlap_is_not_template_overlap_check"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / "var/data-inspection/summary.json")
    args = parser.parse_args()
    archives = []
    failures = []
    for path in sorted(args.data_dir.rglob("*.zip")):
        try:
            with zipfile.ZipFile(path) as archive:
                files = [item for item in archive.infolist() if not item.is_dir() and not item.filename.startswith("__MACOSX/") and not item.filename.endswith(".DS_Store")]
                record = {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path), "compressed_bytes": path.stat().st_size, "entries": len(files), "extensions": dict(Counter(Path(item.filename).suffix.lower() for item in files)), "uncompressed_bytes": sum(item.file_size for item in files)}
                sample = next((item for item in json_members(archive) if item.file_size < 2_000_000), None)
                if sample:
                    record["sample_schema"] = shape(read_json(archive, sample))
                archives.append(record)
        except (zipfile.BadZipFile, ValueError, KeyError, UnicodeError) as exc:
            failures.append({"archive": path.name, "error_type": type(exc).__name__})
    try:
        contracts = inspect_contracts(args.data_dir)
    except (zipfile.BadZipFile, ValueError, KeyError, UnicodeError) as exc:
        contracts = {"error_type": type(exc).__name__}
        failures.append({"scope": "contract_scan", "error_type": type(exc).__name__})
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "archive_count": len(archives), "compressed_bytes": sum(a["compressed_bytes"] for a in archives), "archives": archives, "contracts": contracts, "failures": failures, "scope": {"zip_central_directory": "all archives", "json_schema": "one bounded sample per archive", "contract_label_metadata": "all downloaded contract labels", "employment_source_label_pair": "all downloaded employment pairs", "full_civil_json_validation": False, "full_archive_crc_check": False, "personal_text_exported": False}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    split_summary = {name: {"contract_documents": item.get("label_documents"), "categories": item.get("categories"), "employment_pairing": item.get("pairing"), "employment_counts": item.get("employment", {}).get("counts")} for name, item in contracts.get("splits", {}).items()}
    print(json.dumps({"archive_count": report["archive_count"], "compressed_bytes": report["compressed_bytes"], "splits": split_summary, "failures": failures, "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
