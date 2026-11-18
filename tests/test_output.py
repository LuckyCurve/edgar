import io
import sys
import unittest
from unittest import mock

from edgar.cli.main import _configure_stdout
from edgar.cli.output import paginate, truncate_text


class PaginationTests(unittest.TestCase):
    def test_first_page(self):
        items, meta = paginate(list(range(25)), limit=10, offset=0)
        self.assertEqual(items, list(range(10)))
        self.assertEqual(meta["total"], 25)
        self.assertTrue(meta["has_more"])
        self.assertEqual(meta["next_offset"], 10)

    def test_last_page(self):
        items, meta = paginate(list(range(25)), limit=10, offset=20)
        self.assertEqual(items, [20, 21, 22, 23, 24])
        self.assertFalse(meta["has_more"])
        self.assertIsNone(meta["next_offset"])

    def test_offset_past_end(self):
        items, meta = paginate([1, 2], limit=10, offset=9)
        self.assertEqual(items, [])
        self.assertFalse(meta["has_more"])


class EncodingTests(unittest.TestCase):
    def test_stdout_is_switched_to_utf8(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="gbk")
        with mock.patch.object(sys, "stdout", stream):
            _configure_stdout()
            print("☐")
            stream.flush()
        self.assertEqual(raw.getvalue().decode("utf-8").strip(), "☐")


class TruncateTests(unittest.TestCase):
    def test_truncate(self):
        chunk, meta = truncate_text("abcdefghij", max_chars=4)
        self.assertEqual(chunk, "abcd")
        self.assertEqual(meta["total_chars"], 10)
        self.assertTrue(meta["has_more"])
        self.assertEqual(meta["next_offset"], 4)

    def test_offset(self):
        chunk, meta = truncate_text("abcdefghij", max_chars=4, offset=8)
        self.assertEqual(chunk, "ij")
        self.assertFalse(meta["has_more"])

    def test_full(self):
        chunk, meta = truncate_text("abc", max_chars=100)
        self.assertEqual(chunk, "abc")
        self.assertFalse(meta["has_more"])


if __name__ == "__main__":
    unittest.main()
