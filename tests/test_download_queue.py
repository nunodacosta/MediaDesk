import json
import sys
import tempfile
import threading
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import server


class DownloadRequestTests(unittest.TestCase):
    def setUp(self):
        self.base_request = {
            "urls": ["https://example.com/video"],
            "mode": "video",
            "quality": "best",
            "vformat": "mp4",
            "retry_count": 2,
        }

    def test_validates_clip_playlist_and_proxy_options(self):
        request = {
            **self.base_request,
            "clip_start": "00:00:15",
            "clip_end": "00:00:25",
            "playlist_items": "1,3-4",
            "playlist_sort": "duration-longest",
            "proxy": "socks5://127.0.0.1:9050",
            "priority": 1,
        }

        validated = server._validate_download_request(request)

        self.assertEqual(validated["options"]["clip_start"], "00:00:15")
        self.assertEqual(validated["options"]["playlist_items"], "1,3-4")
        self.assertEqual(validated["options"]["playlist_sort"], "duration-longest")
        self.assertEqual(validated["priority"], 1)

    def test_rejects_invalid_clip_playlist_and_proxy_options(self):
        requests = (
            {**self.base_request, "clip_end": "12"},
            {**self.base_request, "clip_start": "25", "clip_end": "10"},
            {**self.base_request, "playlist_items": "1,,3"},
            {**self.base_request, "playlist_sort": "invalid"},
            {**self.base_request, "proxy": "javascript:alert(1)"},
            {**self.base_request, "priority": "1"},
        )

        for request in requests:
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    server._validate_download_request(request)

    def test_sorts_selected_playlist_items_by_duration_and_quality(self):
        entries = [
            {"duration": 80, "height": 720},
            {"duration": 20, "height": 1080},
            {"duration": 40, "formats": [{"height": 2160}]},
            {"height": 144},
        ]

        by_duration = server._sort_playlist_entries(
            entries, "duration-shortest", playlist_items="1-3"
        )
        by_quality = server._sort_playlist_entries(
            entries, "quality-highest", playlist_items="1,2,3"
        )

        self.assertEqual([index for index, _ in by_duration], [2, 3, 1])
        self.assertEqual([index for index, _ in by_quality], [3, 2, 1])
        self.assertEqual(
            [index for index, _ in server._sort_playlist_entries(entries, "duration-longest")],
            [1, 3, 2, 4],
        )
        self.assertEqual(
            [index for index, _ in server._sort_playlist_entries(
                entries, "duration-shortest", reverse=True
            )],
            [1, 3, 2, 4],
        )

    def test_playlist_sort_keeps_original_indices_for_unavailable_entries(self):
        entries = [
            {"duration": 30},
            None,
            {"duration": 10},
        ]

        sorted_entries = server._sort_playlist_entries(
            entries, "duration-shortest", playlist_items="2-3"
        )

        self.assertEqual([index for index, _ in sorted_entries], [3])

    def test_sorted_playlist_resolves_metadata_then_returns_ordered_urls(self):
        info = {
            "_type": "playlist",
            "entries": [
                {"webpage_url": "https://example.com/1", "height": 720},
                {"webpage_url": "https://example.com/2", "height": 1080},
                {"webpage_url": "https://example.com/3", "height": 2160},
            ],
        }
        process = Mock(returncode=0)
        process.communicate.return_value = (json.dumps(info), "")
        process.stdout = StringIO()
        process.stderr = StringIO()

        with patch.object(server.subprocess, "Popen", return_value=process), \
                patch.object(server, "get_downloads_dir", return_value=tempfile.gettempdir()), \
                patch.object(server, "BIN_DIR", tempfile.gettempdir()), \
                patch.dict(server.config, {"use_cookies": False, "use_po_token": False}), \
                patch.object(server, "download_cancel_requested", False), \
                patch.object(server, "broadcast_log"):
            ordered = server._extract_sorted_playlist_urls(
                "https://example.com/playlist",
                {
                    "playlist_sort": "quality-highest",
                    "playlist_items": "1,2,3",
                    "playlist_reverse": False,
                    "proxy": "",
                },
            )

        self.assertEqual(
            ordered,
            [
                "https://example.com/3",
                "https://example.com/2",
                "https://example.com/1",
            ],
        )

    def test_proxy_credentials_are_not_persisted(self):
        job = {"options": {"proxy": "socks5://user:secret@host:9050"}}

        persisted = server._queue_persisted_copy(job)

        self.assertNotIn("proxy", persisted["options"])
        self.assertTrue(persisted["proxy_requires_reentry"])

    def test_command_includes_selected_output_options(self):
        commands = []
        options = {
            "retry_count": 0,
            "audio_format": "flac",
            "proxy": "socks5://127.0.0.1:9050",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "embed_chapters": True,
            "write_info_json": True,
            "playlist_items": "1,3-4",
            "playlist_reverse": True,
            "clip_start": "15",
            "clip_end": "25",
        }
        with patch.dict(server.config, {"download_delay": 0}), \
                patch.object(server, "download_cancel_requested", False), \
                patch.object(server, "execute_cmd_and_check", side_effect=lambda cmd: (commands.append(list(cmd)) or (True, None))):
            server.run_download_with_fallback(
                "https://example.com/audio",
                "audio",
                "0",
                "mp4",
                False,
                "none",
                "pt",
                True,
                options,
            )

        command = commands[0]
        self.assertIn("--newline", command)
        self.assertEqual(command[command.index("--audio-format") + 1], "flac")
        self.assertEqual(command[command.index("--download-sections") + 1], "*15-25")
        for flag in (
            "--proxy",
            "--embed-metadata",
            "--embed-thumbnail",
            "--convert-thumbnails",
            "--embed-chapters",
            "--write-info-json",
            "--playlist-items",
            "--playlist-reverse",
        ):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--retries") + 1], "0")
        self.assertEqual(command[command.index("--fragment-retries") + 1], "0")


class QueueWorkerTests(unittest.TestCase):
    def test_worker_runs_high_priority_jobs_first(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs = [
                {
                    "id": "normal",
                    "status": "queued",
                    "priority": 0,
                    "created_at": "2026-01-01T00:00:00",
                    "scheduled_at": "",
                    "urls": ["https://example.com/normal"],
                    "completed": 0,
                },
                {
                    "id": "high",
                    "status": "queued",
                    "priority": 1,
                    "created_at": "2026-01-02T00:00:00",
                    "scheduled_at": "",
                    "urls": ["https://example.com/high"],
                    "completed": 0,
                },
            ]
            completed = []
            with patch.multiple(
                server,
                _queue_jobs=jobs,
                QUEUE_FILE=str(Path(temp) / "queue.json"),
                PAUSE_FILE=str(Path(temp) / ".pause"),
                CANCEL_FILE=str(Path(temp) / ".cancel"),
                _queue_worker_running=True,
                _active_download_id=None,
                download_cancel_requested=False,
            ), patch.object(
                server,
                "_process_queue_job",
                side_effect=lambda job: (completed.append(job["id"]) or ("completed", "")),
            ):
                server._queue_worker()

            self.assertEqual(completed, ["high", "normal"])
            self.assertTrue(all(job["status"] == "completed" for job in jobs))

    @unittest.skipUnless(hasattr(server.subprocess, "CREATE_NO_WINDOW"), "Windows-only process flag")
    def test_cancel_interrupts_process_without_waiting_for_output(self):
        with tempfile.TemporaryDirectory() as temp:
            cancel_file = Path(temp) / ".cancel"
            pause_file = Path(temp) / ".pause"

            def request_cancel():
                time.sleep(0.3)
                cancel_file.write_text("", encoding="utf-8")

            with patch.object(server, "CANCEL_FILE", str(cancel_file)), \
                    patch.object(server, "PAUSE_FILE", str(pause_file)), \
                    patch.object(server, "download_cancel_requested", False), \
                    patch.object(server, "current_process", None):
                threading.Thread(target=request_cancel, daemon=True).start()
                started = time.monotonic()
                result = server.execute_cmd_and_check(
                    [sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(15)"]
                )
                elapsed = time.monotonic() - started

            self.assertEqual(result, (False, None))
            self.assertLess(elapsed, 5)


if __name__ == "__main__":
    unittest.main()
