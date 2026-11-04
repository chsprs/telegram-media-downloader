#!/usr/bin/env python3
"""
Self-check smoke test untuk telegram-media-downloader.
Jalankan: python3 test_bot.py
"""

import unittest

from bot import (
    LRUCache,
    URL_REGEX,
    estimate_sizes,
    fmt_duration,
    human_size,
    progress_bar,
    is_authorized,
    format_keyboard,
    approval_keyboard,
)


class TestHelpers(unittest.TestCase):
    def test_lru_cache(self):
        cache = LRUCache(capacity=2)
        cache.set("1", "a")
        cache.set("2", "b")
        self.assertEqual(cache.get("1"), "a")
        cache.set("3", "c")
        self.assertEqual(cache.get("1"), "a")
        self.assertIsNone(cache.get("2"))
        self.assertEqual(cache.get("3"), "c")

    def test_url_regex(self):
        cases = [
            ("Lihat ini https://vt.tiktok.com/ZSxyz/ mantap", "https://vt.tiktok.com/ZSxyz/"),
            ("https://www.instagram.com/reel/C123456/", "https://www.instagram.com/reel/C123456/"),
            ("check: https://youtu.be/dQw4w9WgXcQ?si=abc", "https://youtu.be/dQw4w9WgXcQ?si=abc"),
        ]
        for text, expected in cases:
            m = URL_REGEX.search(text)
            self.assertIsNotNone(m)
            self.assertEqual(m.group(0), expected)

    def test_no_url(self):
        self.assertIsNone(URL_REGEX.search("halo bot apa kabar"))

    def test_human_size(self):
        self.assertEqual(human_size(50 * 1024 * 1024), "50 MB")
        self.assertEqual(human_size(1024), "1 KB")
        self.assertEqual(human_size(0), "0 B")

    def test_fmt_duration(self):
        self.assertEqual(fmt_duration(0), "—")
        self.assertEqual(fmt_duration(59), "0:59")
        self.assertEqual(fmt_duration(725), "12:05")
        self.assertEqual(fmt_duration(3725), "1:02:05")

    def test_progress_bar(self):
        self.assertEqual(progress_bar(0, 10), "░" * 10)
        self.assertEqual(progress_bar(100, 10), "█" * 10)
        self.assertEqual(len(progress_bar(37.5, 10)), 10)

    def test_is_authorized_empty_whitelist(self):
        self.assertTrue(is_authorized(12345))

    def test_estimate_sizes(self):
        info = {
            "duration": 60,
            "formats": [
                {"vcodec": "avc1", "acodec": "none", "height": 1080, "filesize": 20_000_000},
                {"vcodec": "avc1", "acodec": "none", "height": 720, "filesize": 10_000_000},
                {"vcodec": "none", "acodec": "mp4a", "tbr": 128},
            ],
        }
        est = estimate_sizes(info)
        self.assertEqual(est["v1080"], 20_000_000 + 960_000)
        self.assertEqual(est["v720"], 10_000_000 + 960_000)
        self.assertEqual(est["a128"], 960_000)
        self.assertEqual(est["a320"], 2_400_000)
        self.assertNotIn("v480", est)

    def test_keyboards_build(self):
        mk = format_keyboard("12345678", {"v720": 5_000_000})
        datas = [b.callback_data for row in mk.keyboard for b in row]
        self.assertIn("f:v720:12345678", datas)
        self.assertTrue(all(len(d.encode()) <= 64 for d in datas))

        ak = approval_keyboard("12345678", "a192")
        adatas = [b.callback_data for row in ak.keyboard for b in row]
        self.assertIn("ok:a192:12345678", adatas)
        self.assertTrue(all(len(d.encode()) <= 64 for d in adatas))


if __name__ == "__main__":
    unittest.main()
