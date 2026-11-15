#!/usr/bin/env python3
"""Compare baseline / v1 / v2 on the locked test split and write the experiment note.

Outputs var/ml/clause/report.json and docs/notes/권리ON AI 구현/11 조항 분류 모델 실험.md.
Every number in the note is computed here; nothing is typed by hand.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.clause_labels import RISK_TYPES
from backend.clause_model import ClauseModel
from scripts.ml.common import DATA, load_split, metrics

NOTE = ROOT / "docs/notes/권리ON AI 구현/11 조항 분류 모델 실험.md"
NAMES = {"baseline": "A. 기준선 (TF-IDF + 로지스틱 회귀)", "v1": "B. 1차 학습 (KLUE-RoBERTa, 문장)", "v2": "C. 2차 학습 (조 제목 문맥·가중치·임계값)"}


def errors(rows, predicted, labels, per_label=3):
    """The most frequent misses and false alarms, with examples, for error analysis."""
    missed, alarms = Counter(), Counter()
    examples = {}
    for row, pred in zip(rows, predicted):
        for label in set(row["labels"]) - set(pred):
            missed[label] += 1
            examples.setdefault(("missed", label), []).append(row)
        for label in set(pred) - set(row["labels"]):
            alarms[label] += 1
            examples.setdefault(("false_alarm", label), []).append(row)
    out = []
    for kind, counter in (("missed", missed), ("false_alarm", alarms)):
        for label, count in counter.most_common(8):
            out.append({"kind": kind, "label": label, "count": count,
                        "examples": [{"title": r["title"], "text": r["text"][:160], "gold": r["labels"]} for r in examples[(kind, label)][:per_label]]})
    return out


def evaluate(data=DATA, models=("baseline", "v1", "v2")):
    test = load_split("test", data)
    gold = [r["labels"] for r in test]
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "test_sentences": len(test),
              "test_documents": len({r["doc_id"] for r in test}), "models": {}}
    for name in models:
        path = Path(data) / name
        if not (path / "meta.json").is_file():
            continue
        model = ClauseModel(path)
        started = time.monotonic()
        predicted = model.predict(test)
        elapsed = time.monotonic() - started
        result = metrics(gold, predicted, model.labels)
        report["models"][name] = {"title": NAMES[name], "meta": {k: model.meta.get(k) for k in ("kind", "base_model", "with_context", "best_epoch", "train_seconds", "dev", "hyperparameters", "config", "device", "threshold_policy", "previous")},
                                  "test": result, "ms_per_sentence": round(elapsed / len(test) * 1000, 2), "errors": errors(test, predicted, model.labels)}
    out = Path(data) / "report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def note(report, card):
    models = report["models"]
    names = list(models)
    lines = ["---", "tags: [권리ON, 모델학습, 평가]", "status: 실험 결과 (scripts/ml/evaluate_clause.py 자동 생성)", "---", "",
             "# 조항 분류 모델 실험", "", "[[00 권리ON 전문기 구현 가이드|시작 노트]] · 이전: [[10 1차 MVP 실행과 검증]] · 다음: [[12 AI 처리 구조]]", "",
             f"생성: {report['created_at'][:19]}Z. 이 문서의 수치는 `scripts/ml/evaluate_clause.py`가 잠근 test에서 계산했다.", "",
             "## 1. 과제와 데이터", "",
             "근로계약서 문장마다 어떤 조항인지(임금액, 손해배상의 예정, 경업금지 등)를 다중 라벨로 분류한다. 분류 결과는 위험·주의 조항 후보 선정과 근로기준법 제17조 필수 항목 누락 확인에 쓰고, 최종 위험 판단은 규칙·원문 대조·에이전트 검증을 거친다.", "",
             "| 분할 | 문서 | 문장 | 유형 없는 문장 |", "| --- | --- | --- | --- |"]
    for split in ("train", "dev", "test"):
        lines.append(f"| {split} | {card['documents'][split]} | {card['sentences'][split]} | {card['sentences_without_type'][split]} |")
    lines += ["", f"- 출처: {card['source']}. Training 아카이브를 문서 단위로 train/dev(9:1)로 나누고, Validation 아카이브 {card['documents']['test']}건을 test로 잠갔다. 같은 내용의 문서는 같은 분할에 둔다.",
              f"- 라벨 {len(card['labels'])}종. `기타`만 붙은 문장은 유형 없음(음성 예)으로, `비밀 유지`는 `비밀 유지 의무`로 합쳤다. 자리표시자 `(@성명1)`은 `[값]`으로 통일했다.", "",
              "## 2. 모델", "", "| 모델 | 구성 | 학습 시간 | best epoch |", "| --- | --- | --- | --- |"]
    for name in names:
        meta = models[name]["meta"]
        config = "char 2-4gram TF-IDF + OvR 로지스틱 회귀" if meta["kind"] == "tfidf" else \
            f"{meta['base_model']}, " + ("조 제목+문장, 희소 라벨 pos_weight, " + (meta.get("threshold_policy") or "라벨별 임계값") if meta.get("with_context") else "문장만, 임계값 0.5") + \
            f", lr {meta['hyperparameters']['lr']}, batch {meta['hyperparameters']['batch_size']}, {meta['hyperparameters']['epochs']} epoch"
        lines.append(f"| {models[name]['title']} | {config} | {meta['train_seconds']}초 | {meta.get('best_epoch') or '-'} |")
    lines += ["", "## 3. test 결과", "", "| 모델 | micro P | micro R | micro F1 | macro F1 | 문장 완전일치 | 문장당 추론(ms) |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for name in names:
        t = models[name]["test"]
        lines.append(f"| {models[name]['title']} | {t['micro']['precision']:.3f} | {t['micro']['recall']:.3f} | {t['micro']['f1']:.3f} | {t['macro']['f1']:.3f} | {t['exact_match']:.3f} | {models[name]['ms_per_sentence']} |")
    lines += ["", "### 위험·주의 조항과 관련된 유형의 F1", "", "| 유형 | test 건수 | " + " | ".join(names) + " |", "| --- | --- | " + " | ".join("---" for _ in names) + " |"]
    first = models[names[0]]["test"]["per_label"]
    for label in RISK_TYPES:
        if label in first:
            lines.append(f"| {label} | {first[label]['support']} | " + " | ".join(f"{models[n]['test']['per_label'][label]['f1']:.3f}" for n in names) + " |")
    lines += ["", "### 전체 유형별 F1", "", "| 유형 | test 건수 | " + " | ".join(names) + " |", "| --- | --- | " + " | ".join("---" for _ in names) + " |"]
    for label in sorted(first, key=lambda l: -first[l]["support"]):
        lines.append(f"| {label} | {first[label]['support']} | " + " | ".join(f"{models[n]['test']['per_label'][label]['f1']:.3f}" for n in names) + " |")
    last = names[-1]
    lines += ["", f"## 4. 오류 분석 ({models[last]['title']})", "", "| 종류 | 유형 | 건수 | 예시 (조 제목 › 문장 / 정답) |", "| --- | --- | --- | --- |"]
    for e in models[last]["errors"][:12]:
        example = e["examples"][0]
        text = f"{example['title'][:24]} › {example['text'][:70]} / {', '.join(example['gold']) or '유형 없음'}".replace("|", "/")
        lines.append(f"| {'놓침' if e['kind'] == 'missed' else '오탐'} | {e['label']} | {e['count']} | {text} |")
    lines += ["", "## 5. 해석과 한계", "",
              "- test는 22개 문서로 작고 서식이 학습 데이터와 비슷하다. 실제 사용자가 올리는 사진·OCR 문장에서는 성능이 낮을 수 있다.",
              "- 조항 유형 분류는 불리함 판단이 아니다. 위험 탐지 성능은 사람이 검수한 위험 라벨로 별도 평가한다(`scripts/ml/evaluate_risk.py`).",
              "- 단일 seed 결과다. 차이가 작은 유형은 반복 실험 없이 우열을 단정하지 않는다.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--no-note", action="store_true")
    args = parser.parse_args()
    report = evaluate(args.data)
    for name, m in report["models"].items():
        print(name, m["test"]["micro"]["f1"], m["test"]["macro"]["f1"], m["ms_per_sentence"], "ms")
    if not args.no_note:
        card = json.loads((args.data / "data_card.json").read_text(encoding="utf-8"))
        NOTE.write_text(note(report, card), encoding="utf-8")
        print("wrote", NOTE.relative_to(ROOT))
