"""A reference translation must never alter amounts, dates, places or who owes what."""
import json
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import URLError

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.auto_translation import is_faithful, lock, restore, translate_texts
from backend.knowledge import ROOT


def replies(mapping):
    def fake(schema, prompt, **kwargs):
        batch = json.loads(prompt[prompt.index('{"T'):])
        return {k: mapping(v) for k, v in batch.items()}, "fake"
    return fake


class IntegrityTests(unittest.TestCase):
    def test_values_are_locked_and_restored_exactly(self):
        text = "계약기간 2026년 11월 16일, 09시 00분, 월급 2,300,000원, 서울특별시 마포구 성산로 148-2, 1층"
        masked, values = lock(text)
        self.assertNotRegex(masked, r"2026|2,300,000|마포구|09")
        restored = restore(masked, values)
        for value in ("2026-11-16", "09:00", "2,300,000원", "서울특별시 마포구 성산로 148-2, 1층"):
            self.assertIn(value, restored)

    def test_weekdays_are_fixed_per_language(self):
        masked, values = lock("매주 화요일~토요일 근무", "zh")
        self.assertEqual(sorted(values.values()), ["星期二", "星期六"])
        self.assertEqual(sorted(lock("토요일 근무", "es")[1].values()), ["sábado"])

    def test_letter_spaced_chinese_is_closed_up(self):
        with patch("backend.auto_translation.generate", side_effect=replies(lambda text: "劳 动 合 同 书")):
            self.assertEqual(translate_texts(["근 로 계 약 서"], "zh"), {"근 로 계 약 서": "劳动合同书"})

    def test_tenant_synonym_counts_as_the_same_party(self):
        self.assertFalse(self.rejected("새 세입자를 구하는 조건이다", "La condición es encontrar un nuevo arrendatario"))

    def rejected(self, source, output, language="es"):
        masked, values = lock(source)
        return not is_faithful(masked, output, values, language)

    def test_changed_number_is_rejected(self):
        self.assertTrue(self.rejected("주당 40시간 근무", "60 horas de trabajo por semana"))
        self.assertFalse(self.rejected("주당 40시간 근무", "40 horas de trabajo por semana"))

    def test_dropped_token_is_rejected(self):
        self.assertTrue(self.rejected("월급 2,300,000원 지급", "pago del salario mensual completo"))

    def test_swapped_or_invented_party_is_rejected(self):
        self.assertTrue(self.rejected("임차인은 임대인에게 보증금을 지급한다", "El arrendatario paga el depósito al vendedor"))
        self.assertTrue(self.rejected("임대인이 수리비를 부담한다", "El arrendatario asume los gastos de reparación"))
        self.assertFalse(self.rejected("임대인이 수리비를 부담한다", "El arrendador asume los gastos de reparación"))

    def test_fragment_and_foreign_script_are_rejected(self):
        self.assertTrue(self.rejected("다음과 같이 계약을 체결하고 성실히 이행한다", "se denomina"))
        self.assertTrue(self.rejected("근무 장소는 본사 사무실이다", "El lugar de trabajo es 特别市 oficina central"))

    def test_failed_line_is_retried_alone_then_left_out(self):
        calls = []

        def fake(schema, prompt, **kwargs):
            batch = json.loads(prompt[prompt.index('{"T'):])
            calls.append(len(batch))
            return {k: "Texto traducido completo aquí" if "좋은" in v else "60 horas de trabajo" for k, v in batch.items()}, "fake"

        with patch("backend.auto_translation.generate", side_effect=fake):
            output = translate_texts(["좋은 문장을 번역한다", "주당 40시간 근무"], "es")
        self.assertEqual(calls, [2, 1])
        self.assertEqual(list(output), ["좋은 문장을 번역한다"])


class ApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.client = TestClient(create_app(Path(folder.name) / "t.sqlite3"))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        sample = next(s for s in self.client.get("/api/samples").json() if s["id"] == "employment-cafe")
        id = self.client.post("/api/analyses", json={"title": "t", "text": (ROOT / "samples/employment-cafe.txt").read_text(), "contract_type": "employment", "context": sample["context"]}).json()["analysis_id"]
        for _ in range(200):
            self.result = self.client.get(f"/api/analyses/{id}").json()
            if self.result["status"] not in {"queued", "running"}:
                break
            time.sleep(0.05)
        self.url = f"/api/analyses/{id}/auto-translation"

    def poll(self):
        for _ in range(400):
            data = self.client.post(self.url, json={"analysis_revision": 1, "language": "es"}).json()
            if data["status"] != "running":
                return data
            time.sleep(0.02)
        raise AssertionError("translation did not finish")

    def test_translates_blocks_and_review_and_caches(self):
        def spanish(text):
            roles = "".join(f" {word}" for role, word in (("근로자", "trabajador"), ("사업주", "empleador")) if role in text)
            tokens = " ".join(re.findall(r"\{\{\d+\}\}", text))
            digits = " ".join(re.findall(r"\d+", re.sub(r"\{\{\d+\}\}", "", text).replace(",", "")))
            return f"Traducción completa de esta línea del contrato{roles} {tokens} {digits}"

        fake = replies(spanish)
        with patch("backend.auto_translation.generate", side_effect=fake) as model:
            data = self.poll()
            count = model.call_count
            again = self.poll()
        self.assertEqual(data["status"], "complete")
        self.assertEqual(model.call_count, count)
        self.assertEqual(again["blocks"], data["blocks"])
        quote = self.result["review"]["findings"][0]["evidence"][0]
        self.assertIn(quote["block_id"], data["blocks"])
        self.assertIn("Traducción", data["result"]["review"]["findings"][0]["title"])
        # The Korean evidence stays untouched for comparison.
        self.assertEqual(data["result"]["review"]["findings"][0]["evidence"][0]["quote"], quote["quote"])
        self.assertTrue(any("2026-11-16" in line for line in data["blocks"].values()))

    def test_model_down_reports_failure_and_can_retry(self):
        with patch("backend.auto_translation.generate", side_effect=URLError("refused")):
            failed = self.poll()
        self.assertEqual(failed["status"], "failed")
        self.assertIn("Ollama", failed["error"])
        with patch("backend.auto_translation.generate", side_effect=replies(lambda text: text)):
            self.assertEqual(self.poll()["status"], "complete")

    def test_rejected_lines_stay_out_rather_than_showing_a_wrong_translation(self):
        with patch("backend.auto_translation.generate", side_effect=replies(lambda text: "60 horas")):
            data = self.poll()
        self.assertEqual(data["blocks"], {})
        self.assertGreater(data["untranslated_lines"], 0)
        self.assertEqual(data["result"]["review"]["headline"], self.result["review"]["headline"])
