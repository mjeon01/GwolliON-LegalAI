"""Runs only with TEST_DATABASE_URL; rows it creates are removed afterwards."""
import os
import unittest
from uuid import uuid4

from backend.store import Store, StaleRevision, postgres_sql

URL = os.environ.get("TEST_DATABASE_URL")


class SqlTests(unittest.TestCase):
    def test_rewrites_sqlite_only_syntax(self):
        sql = postgres_sql("SELECT json_extract(request,'$.document_id') FROM analyses WHERE id=? AND created_at < datetime('now','-1 day')")
        self.assertEqual(sql.count("%s"), 1)
        self.assertIn("request::jsonb->>'document_id'", sql)
        self.assertNotIn("datetime(", sql)


@unittest.skipUnless(URL, "TEST_DATABASE_URL is not set")
class PostgresStoreTests(unittest.TestCase):
    def setUp(self):
        self.store, self.id = Store(URL), str(uuid4())
        self.addCleanup(self.store.delete, self.id)
        self.store.create(self.id, {"title": "테스트", "document_id": None})

    def test_lifecycle_chat_translation_and_stale_writes(self):
        store, id = self.store, self.id
        self.assertTrue(store.start(id))
        self.assertFalse(store.start(id))
        store.finish(id, result={"status": "completed", "n": 1})
        self.assertEqual(store.get(id)["result"]["n"], 1)
        self.assertIn(id, [a["analysis_id"] for a in store.list()])
        store.append_chat(id, 1, 0, {"q": "질문"})
        with self.assertRaises(StaleRevision):
            store.append_chat(id, 1, 0, {"q": "늦은 질문"})
        self.assertEqual(store.chat(id, 1), [{"q": "질문"}])
        store.save_translation(id, 1, "zh", "auto_review", "h", {"v": 1})
        store.save_translation(id, 1, "zh", "auto_review", "h", {"v": 2})
        self.assertEqual(store.translation(id, 1, "zh", "auto_review", "h"), {"v": 2})
        store.revise(id, 1, {"title": "새"}, {"status": "completed"})
        with self.assertRaises(StaleRevision):
            store.revise(id, 1, {"title": "새"}, {"status": "completed"})

    def test_documents_keep_binary_pages_and_a_second_instance_sees_them(self):
        pages = [{"page": 1, "width": 10, "height": 20, "image": b"\x00\xffpng", "words": [{"t": "가"}]}]
        document = self.store.save_document(pages)
        other = Store(URL)
        self.assertEqual(bytes(other.document_image(document, 1)), b"\x00\xffpng")
        self.assertEqual(other.document_pages(document)[0]["words"], [{"t": "가"}])
        self.store.set_document_words(document, 1, None)
        self.assertIsNone(other.document_pages(document)[0]["words"])
        linked = str(uuid4())
        self.addCleanup(self.store.delete, linked)
        self.store.create(linked, {"title": "연결", "document_id": document})
        self.assertTrue(self.store.delete(linked))
        self.assertIsNone(other.document_image(document, 1))
