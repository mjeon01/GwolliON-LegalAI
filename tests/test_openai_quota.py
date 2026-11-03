"""The daily cap must stop paid requests before they leave the server."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import openai_client
from backend.openai_client import OpenAIError
from backend.review import openai_review
from backend.store import Store


class QuotaTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name) / "t.sqlite3")
        keys = patch("backend.openai_client.settings", return_value=("key", "model"))
        keys.start()
        self.addCleanup(keys.stop)
        gate = patch("backend.openai_client.quota", self.store.take_openai_call)
        gate.start()
        self.addCleanup(gate.stop)
        limit = patch.dict("os.environ", {"OPENAI_DAILY_LIMIT": "0"})
        limit.start()
        self.addCleanup(limit.stop)

    def test_counter_stops_at_the_limit_and_resets_each_day(self):
        self.assertEqual([self.store.take_openai_call(2, "d1") for _ in range(3)], [True, True, False])
        self.assertTrue(self.store.take_openai_call(2, "d2"))

    def test_generate_makes_no_request_once_the_limit_is_reached(self):
        with patch("backend.openai_client.httpx.Client") as client, self.assertRaises(OpenAIError) as raised:
            self.store.take_openai_call(1)
            openai_client.generate({"type": "object", "properties": {}}, "prompt")
        client.assert_not_called()
        self.assertEqual((raised.exception.code, raised.exception.status), ("openai_daily_limit", 429))

    def test_review_reports_the_limit_rather_than_a_generic_failure(self):
        blocks = [{"block_id": "b1", "page": 1, "text": "제1조 임금은 매월 지급한다."}]
        self.store.take_openai_call(1)
        with self.assertRaises(OpenAIError) as raised:
            openai_review(blocks, "employment", "worker", {})
        self.assertIn("소진", str(raised.exception))
        self.assertEqual(raised.exception.status, 429)
