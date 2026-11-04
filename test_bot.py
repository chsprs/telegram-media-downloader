#!/usr/bin/env python3
"""
Self-check smoke test for telegram-media-downloader components.
Run with: python3 test_bot.py
"""

import os
import re
import unittest
from bot import LRUCache, URL_REGEX

class TestBotComponents(unittest.TestCase):
    def test_lru_cache(self):
        cache = LRUCache(capacity=2)
        cache.set("1", "https://example.com/1")
        cache.set("2", "https://example.com/2")
        self.assertEqual(cache.get("1"), "https://example.com/1")
        # Adding 3 should evict 2 because 1 was accessed
        cache.set("3", "https://example.com/3")
        self.assertEqual(cache.get("1"), "https://example.com/1")
        self.assertIsNone(cache.get("2"))
        self.assertEqual(cache.get("3"), "https://example.com/3")

    def test_url_regex(self):
        links = [
            ("Lihat ini https://vt.tiktok.com/ZSxyz/ mantap", "https://vt.tiktok.com/ZSxyz/"),
            ("https://www.instagram.com/reel/C123456/", "https://www.instagram.com/reel/C123456/"),
            ("check: https://youtu.be/dQw4w9WgXcQ?si=abc", "https://youtu.be/dQw4w9WgXcQ?si=abc"),
        ]
        for text, expected in links:
            match = URL_REGEX.search(text)
            self.assertIsNotNone(match)
            self.assertEqual(match.group(0), expected)

    def test_no_url(self):
        self.assertIsNone(URL_REGEX.search("halo bot apa kabar"))

    def test_is_authorized_empty(self):
        from bot import is_authorized
        self.assertTrue(is_authorized(12345))

if __name__ == "__main__":
    unittest.main()
