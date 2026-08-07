import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_to_article.llm.factory import create_llm_client
from data_to_article.llm.mock import MockClient


class TestMockLLM(unittest.TestCase):
    def test_create_mock(self):
        cfg = {"llm": {"provider": "mock"}}
        client = create_llm_client(cfg)
        self.assertIsInstance(client, MockClient)

    def test_chat_deterministic(self):
        cfg = {"llm": {"provider": "mock"}}
        client = create_llm_client(cfg)
        resp = client.chat([{"role": "user", "content": "你好世界"}])
        self.assertIn("你好世界", resp.content)
        self.assertEqual(resp.model, "mock-1")


if __name__ == "__main__":
    unittest.main()
