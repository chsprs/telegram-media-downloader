#!/usr/bin/env python3
"""
Self-check smoke test untuk telegram-media-downloader.
Jalankan: python3 test_bot.py
"""

import os
import sys
import time
import threading
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
    download_guard,
    DownloadCancelled,
    prune_stale_downloads,
    startup_cleanup,
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
        def _get_data(b):
            d = getattr(b, 'data', None) or getattr(getattr(b, 'type', None), 'data', None)
            return d.decode("utf-8") if isinstance(d, bytes) else str(d)

        mk = format_keyboard("12345678", {"v720": 5_000_000})
        datas = [_get_data(b) for row in mk for b in row]
        self.assertIn("f:v720:12345678", datas)
        self.assertTrue(all(len(d.encode()) <= 64 for d in datas))

        ak = approval_keyboard("12345678", "a192")
        adatas = [_get_data(b) for row in ak for b in row]
        self.assertIn("ok:a192:12345678", adatas)
        self.assertTrue(all(len(d.encode()) <= 64 for d in adatas))

    def test_mtproto_limit_and_engine(self):
        from bot import MAX_UPLOAD_MB, MAX_TELEGRAM_FILESIZE, client
        self.assertGreaterEqual(MAX_UPLOAD_MB, 1000)
        self.assertEqual(MAX_TELEGRAM_FILESIZE, MAX_UPLOAD_MB * 1024 * 1024)
        self.assertIsNotNone(client)

    def test_disk_check(self):
        from bot import disk_check, MIN_FREE_DISK_MB
        self.assertEqual(disk_check(0), "")
        huge = 1 << 60
        msg = disk_check(huge)
        self.assertIn("Ruang disk tidak cukup", msg)
        self.assertIn("Butuh", msg)
        self.assertGreater(MIN_FREE_DISK_MB, 0)

    def test_download_pool_bounded(self):
        from bot import _pool, MAX_CONCURRENT_DOWNLOADS
        self.assertGreaterEqual(MAX_CONCURRENT_DOWNLOADS, 1)
        self.assertLessEqual(_pool._max_workers, 4)


    def test_url_regex_strip_punctuation(self):
        cases = [
            ("Link: https://vt.tiktok.com/ZSxyz/.", "https://vt.tiktok.com/ZSxyz/"),
            ("Cek https://instagram.com/p/123, mantap", "https://instagram.com/p/123"),
            ("(sumber: https://youtu.be/abc?si=1)", "https://youtu.be/abc?si=1"),
        ]
        for text, expected in cases:
            m = URL_REGEX.search(text)
            self.assertIsNotNone(m)
            cleaned = m.group(0).rstrip(".,);:!?\"'”’>")
            self.assertEqual(cleaned, expected)

    def test_audio_title_clean(self):
        title = "Judul Video\nMulti line\r\nTest"
        cleaned = " ".join(title.split())[:60]
        self.assertEqual(cleaned, "Judul Video Multi line Test")
        self.assertNotIn("\n", cleaned)


    def test_prune_stale_downloads(self):
        import tempfile, os, time
        from bot import prune_stale_downloads, DOWNLOAD_DIR
        # Buat file dummy tua (> 3600s lalu)
        old_file = os.path.join(DOWNLOAD_DIR, "test_stale_old.mp4")
        with open(old_file, "wb") as f:
            f.write(b"old")
        # Mundurkan mtime ke 2 jam lalu
        two_hours_ago = time.time() - 7200
        os.utime(old_file, (two_hours_ago, two_hours_ago))

        # Buat file baru
        new_file = os.path.join(DOWNLOAD_DIR, "test_stale_new.mp4")
        with open(new_file, "wb") as f:
            f.write(b"new")

        pruned = prune_stale_downloads(max_age_seconds=3600)
        self.assertGreaterEqual(pruned, 1)
        self.assertFalse(os.path.exists(old_file))
        self.assertTrue(os.path.exists(new_file))
        # Bersihkan file baru
        os.remove(new_file)


class TestDownloadGuard(unittest.TestCase):
    def test_cancelled_by_user(self):
        cancel = threading.Event()
        why = {}
        try:
            download_guard(cancel, why)
        except DownloadCancelled:
            raise AssertionError("seharusnya tidak raise saat belum dibatalkan")
        cancel.set()
        try:
            download_guard(cancel, why)
            raise AssertionError("harusnya raise DownloadCancelled")
        except DownloadCancelled as e:
            self.assertEqual(why["why"], "user")


class TestStartupCleanup(unittest.TestCase):
    def test_startup_wipes_all(self):
        from bot import DOWNLOAD_DIR
        old_file = os.path.join(DOWNLOAD_DIR, "startup_test_old.mp4")
        # Pastikan ada file dummy lama
        with open(old_file, "wb") as f:
            f.write(b"garbage")
        time_stamp = time.time() - 7200
        os.utime(old_file, (time_stamp, time_stamp))
        result = startup_cleanup()
        self.assertGreater(result, 0)  # minimal satu file terhapus
        # Bersihkan sisa
        try:
            os.remove(old_file)
        except FileNotFoundError:
            pass


    def test_req_id_unique(self):
        from bot import new_req_id
        ids = {new_req_id() for _ in range(2000)}
        self.assertEqual(len(ids), 2000)
        for rid in list(ids)[:50]:
            self.assertEqual(len(rid), 10)
            self.assertTrue(rid.isalnum())

    def test_download_media_picks_largest_file(self):
        import os, glob as _glob
        import bot as B

        class FakeYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=True):
                rid = os.path.basename(self.opts["outtmpl"]).split("_", 1)[0]
                for name, size in ((f"{rid}_x.webm", 100), (f"{rid}_x.mp4", 5000),
                                   (f"{rid}_x.mp4.part", 1)):
                    with open(os.path.join(B.DOWNLOAD_DIR, name), "wb") as fh:
                        fh.write(b"0" * size)
                return {"id": "x"}

        real = B.yt_dlp.YoutubeDL
        B.yt_dlp.YoutubeDL = FakeYDL
        try:
            rid = B.new_req_id()
            path = B.download_media("u", "v720", rid)
            self.assertTrue(path.endswith(".mp4"))
            self.assertEqual(os.path.getsize(path), 5000)
        finally:
            B.yt_dlp.YoutubeDL = real
            B.cleanup(rid)

    def test_probe_inflight_released_on_failure(self):
        import asyncio
        import bot as B
        sent = []
        real_edit = B.client.edit_message
        real_probe = B.probe

        async def fake_edit(*a, **k):
            sent.append(a)

        B.client.edit_message = fake_edit
        B.probe = lambda url: (_ for _ in ()).throw(RuntimeError("boom"))

        try:
            B._probes_inflight.add(999)
            asyncio.run(B._probe_and_send(1, 999, "u", 2))
            self.assertNotIn(999, B._probes_inflight)
            self.assertTrue(sent)
        finally:
            B.client.edit_message = real_edit
            B.probe = real_probe
            B._probes_inflight.discard(999)

    def test_download_guard_disk_check_throttled(self):
        import bot as B
        calls = []
        real_usage = B.shutil.disk_usage
        real_ts = list(B._guard_disk_ts)

        class DU:
            free = 10 ** 12

        B.shutil.disk_usage = lambda p: (calls.append(1), DU)[1]
        try:
            B._guard_disk_ts[0] = 0.0
            B.download_guard(None, {})
            B.download_guard(None, {})
            B.download_guard(None, {})
            self.assertEqual(len(calls), 1)
        finally:
            B.shutil.disk_usage = real_usage
            B._guard_disk_ts[0] = real_ts[0]


    def test_ydl_retry_transient_then_ok(self):
        import bot as B
        calls = []

        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=False):
                calls.append(url)
                if len(calls) < 3:
                    raise B.yt_dlp.utils.DownloadError(
                        "Unable to extract universal data for rehydration")
                return {"id": "ok"}

        real = B.yt_dlp.YoutubeDL
        B.yt_dlp.YoutubeDL = FakeYDL
        try:
            info = B._ydl_retry({}, "u", download=True, attempts=3, base_delay=0)
            self.assertEqual(info["id"], "ok")
            self.assertEqual(len(calls), 3)
        finally:
            B.yt_dlp.YoutubeDL = real

    def test_ydl_retry_fatal_not_retried(self):
        import bot as B
        calls = []

        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=False):
                calls.append(url)
                raise B.yt_dlp.utils.DownloadError("This video is private")

        real = B.yt_dlp.YoutubeDL
        B.yt_dlp.YoutubeDL = FakeYDL
        try:
            with self.assertRaises(B.yt_dlp.utils.DownloadError):
                B._ydl_retry({}, "u", download=True, attempts=3, base_delay=0)
            self.assertEqual(len(calls), 1)
        finally:
            B.yt_dlp.YoutubeDL = real

    def test_cancel_not_retried(self):
        import bot as B
        calls = []

        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=False):
                calls.append(url)
                raise B.DownloadCancelled("dibatalkan pengguna")

        real = B.yt_dlp.YoutubeDL
        B.yt_dlp.YoutubeDL = FakeYDL
        try:
            with self.assertRaises(B.DownloadCancelled):
                B._ydl_retry({}, "u", download=True, attempts=3, base_delay=0)
            self.assertEqual(len(calls), 1)
        finally:
            B.yt_dlp.YoutubeDL = real


if __name__ == "__main__":
    unittest.main()
