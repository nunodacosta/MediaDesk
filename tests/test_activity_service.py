import base64
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import activity_service


class ActivityServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.downloads = self.root / "downloads"
        self.downloads.mkdir()
        self.key = base64.b64encode(b"test activity key material 32byt").decode("ascii")
        self.key_patch = patch.dict(os.environ, {"MEDIADESK_ACTIVITY_KEY": self.key})
        self.key_patch.start()

    def tearDown(self):
        activity_service._release_instance(self.root)
        self.key_patch.stop()
        for handler in list(activity_service.LOG.handlers):
            activity_service.LOG.removeHandler(handler)
            handler.close()
        self.temp.cleanup()

    def test_legacy_config_is_encrypted_and_removed_after_verified_migration(self):
        legacy = self.root / "config.json"
        legacy.write_text(
            json.dumps({"theme": "dark", "po_token": "private-token"}),
            encoding="utf-8",
        )

        with (
            patch.object(
                activity_service,
                "_dpapi_protect",
                side_effect=lambda raw: b"protected:" + raw[::-1],
            ),
            patch.object(
                activity_service,
                "_dpapi_unprotect",
                side_effect=lambda blob: blob.removeprefix(b"protected:")[::-1],
            ),
            patch.object(activity_service.os, "name", "nt"),
        ):
            settings = activity_service.load_config(str(self.root))

        encrypted = (self.root / "data" / "config.enc").read_bytes()
        self.assertEqual(settings["theme"], "dark")
        self.assertEqual(settings["po_token"], "private-token")
        self.assertTrue(encrypted.startswith(activity_service.CONFIG_MAGIC))
        self.assertNotIn(b"private-token", encrypted)
        self.assertFalse(legacy.exists())

    def test_corrupt_encrypted_config_is_preserved_and_reported(self):
        config_path = self.root / "data" / "config.enc"
        config_path.parent.mkdir()
        config_path.write_bytes(activity_service.CONFIG_MAGIC + b"invalid")

        with (
            patch.object(activity_service, "_dpapi_unprotect", side_effect=ValueError("invalid")),
            self.assertRaisesRegex(RuntimeError, "data/config.enc"),
        ):
            activity_service.load_config(str(self.root))

        self.assertTrue(config_path.exists())

    def test_legacy_config_overrides_packaged_encrypted_defaults(self):
        config_path = self.root / "data" / "config.enc"
        legacy_path = self.root / "config.json"
        defaults = {"theme": "system", "language": "pt"}
        legacy_path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

        with (
            patch.object(
                activity_service,
                "_dpapi_protect",
                side_effect=lambda raw: b"protected:" + raw[::-1],
            ),
            patch.object(
                activity_service,
                "_dpapi_unprotect",
                side_effect=lambda blob: blob.removeprefix(b"protected:")[::-1],
            ),
            patch.object(activity_service.os, "name", "nt"),
        ):
            activity_service.save_config(defaults, str(self.root))
            legacy_path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
            loaded = activity_service.load_config(str(self.root))
            stored = activity_service._decode_config(config_path.read_bytes())

        self.assertEqual(loaded, {"theme": "dark", "language": "pt"})
        self.assertFalse(legacy_path.exists())
        self.assertEqual(stored, loaded)

    def test_first_download_encrypts_activity_and_backfills_sidecar_metadata(self):
        old_media = self.downloads / "old" / "old.mp4"
        old_media.parent.mkdir()
        old_media.write_bytes(b"old media")
        old_sidecar = old_media.with_suffix(".info.json")
        old_sidecar.write_text(
            json.dumps({
                "title": "Earlier video",
                "channel": "Example channel",
                "channel_id": "UCexample",
                "uploader": "Example uploader",
                "duration": 120,
                "tags": ["archive"],
            }),
            encoding="utf-8",
        )
        (self.root / "history.json").write_text(
            json.dumps([{
                "url": "https://youtube.com/watch?v=old",
                "date": "2026-01-01T10:00:00",
                "status": "success",
                "file_path": "/downloads/old/old.mp4",
                "platform": "youtube",
            }]),
            encoding="utf-8",
        )
        new_media = self.downloads / "new.mp4"
        new_media.write_bytes(b"new media bytes")

        result = activity_service.record_download({
            "url": "https://youtube.com/watch?v=new",
            "date": "2026-01-02T10:00:00+00:00",
            "title": "Current video",
            "platform": "youtube",
            "channel": "Example channel",
            "uploader": "Example uploader",
            "theme": "ocean",
            "theme_mode": "dark",
            "file_path": "/downloads/new.mp4",
        }, str(self.root))

        encrypted = (self.root / "data" / "activity.enc").read_bytes()
        self.assertTrue(encrypted.startswith(activity_service._MAGIC))
        self.assertNotIn(b"Current video", encrypted)
        data = json.loads(activity_service.decrypt_blob(
            encrypted, base64.b64decode(self.key)
        ).decode("utf-8"))
        old = next(item for item in data["downloads"] if item["title"] == "Earlier video")
        current = next(item for item in data["downloads"] if item["title"] == "Current video")
        self.assertEqual(result["backfilled"], 1)
        self.assertEqual(old["channel_id"], "UCexample")
        self.assertEqual(old["duration"], 120)
        self.assertEqual(old["file_size"], len(b"old media"))
        self.assertIsNone(old["theme"])
        self.assertEqual(current["file_size"], len(b"new media bytes"))
        self.assertEqual(current["theme"], "ocean")
        self.assertEqual(data["platforms"]["youtube"]["count"], 2)

    def test_repeat_downloads_of_same_video_are_aggregated_separately(self):
        entry = {
            "url": "https://vimeo.com/123",
            "title": "Same video",
            "platform": "vimeo",
            "file_path": "/downloads/same.mp4",
        }
        first = activity_service.record_download(
            {**entry, "date": "2026-01-01T10:00:00+00:00"}, str(self.root)
        )
        second = activity_service.record_download(
            {**entry, "date": "2026-01-02T10:00:00+00:00"}, str(self.root)
        )

        activity = activity_service.load_activity(str(self.root))
        self.assertTrue(first["created"])
        self.assertTrue(second["created"])
        self.assertEqual(activity["platforms"]["vimeo"]["count"], 2)
        self.assertEqual(len(activity["downloads"]), 2)

    def test_platform_detection_rejects_lookalike_hosts(self):
        self.assertEqual(
            activity_service.detect_platform("https://m.youtube.com/watch?v=1"),
            "youtube",
        )
        self.assertEqual(
            activity_service.detect_platform("https://evil.youtube.com.attacker.org/video"),
            "evil",
        )
        self.assertEqual(
            activity_service.detect_platform("https://example-youtube.com/video"),
            "example-youtube",
        )

    def test_rss_proposals_respect_platform_filter_and_user_preferences(self):
        published = datetime.now(timezone.utc).isoformat()
        activity = activity_service._empty_activity()
        activity["preferences"]["channels"]["Preferred channel"] = 5
        items = [
            {
                "id": "preferred",
                "url": "https://youtube.com/watch?v=1",
                "title": "New preferred video",
                "published": published,
                "channel_id": "preferred-id",
                "channel_name": "Preferred channel",
                "platform": "youtube",
            },
            {
                "id": "other-platform",
                "url": "https://vimeo.com/2",
                "title": "New unrelated video",
                "published": published,
                "channel_id": "other-id",
                "channel_name": "Other channel",
                "platform": "vimeo",
            },
        ]

        proposals = activity_service.build_proposals(
            items,
            activity,
            {"automation_platforms": ["youtube"], "rss_proposals_max": 5},
            {"seen": [], "proposed": []},
        )

        self.assertEqual([item["id"] for item in proposals], ["preferred"])
        self.assertIn("canal frequente", proposals[0]["reason"])

    def test_suggestion_channels_merge_existing_activity_with_legacy_history(self):
        old_media = self.downloads / "legacy.mp4"
        old_media.write_bytes(b"old")
        old_media.with_suffix(".info.json").write_text(
            json.dumps({
                "title": "Legacy item",
                "channel": "Legacy channel",
                "channel_id": "UC" + "l" * 22,
            }),
            encoding="utf-8",
        )
        (self.root / "history.json").write_text(
            json.dumps([
                {
                    "url": "https://youtube.com/watch?v=legacy",
                    "date": "2026-10-25T10:00:00+00:00",
                    "status": "success",
                    "file_path": "/downloads/legacy.mp4",
                    "platform": "youtube",
                },
                {
                    "url": "https://youtube.com/watch?v=failed",
                    "status": "failed",
                    "file_path": "/downloads/missing.mp4",
                    "platform": "youtube",
                },
            ]),
            encoding="utf-8",
        )
        activity = activity_service._empty_activity()
        activity["downloads"].append({
            "id": "current",
            "url": "https://vimeo.com/current",
            "date": "2026-10-26T10:00:00+00:00",
            "platform": "vimeo",
            "channel": "Current channel",
            "channel_url": "https://vimeo.com/current-channel",
        })
        activity_service._save_activity(activity, str(self.root))

        suggestions = activity_service.suggestion_channels(str(self.root), limit=10)

        self.assertEqual(
            {(item["platform"], item["name"]) for item in suggestions},
            {("youtube", "Legacy channel"), ("vimeo", "Current channel")},
        )
        legacy = next(item for item in suggestions if item["name"] == "Legacy channel")
        self.assertEqual(legacy["url"], "https://www.youtube.com/channel/" + "UC" + "l" * 22)
        self.assertEqual(legacy["count"], 1)
        self.assertTrue(legacy["rss_supported"])
        self.assertEqual(legacy["rss_status"], "supported")

    def test_rss_capability_requires_a_reliable_channel_feed_route(self):
        youtube = activity_service.rss_capability({
            "platform": "youtube",
            "url": "https://www.youtube.com/channel/UC" + "a" * 22,
        })
        self.assertTrue(youtube["rss_supported"])
        self.assertIn("channel_id=UC", youtube["rss_feed_url"])

        no_youtube_id = activity_service.rss_capability({
            "platform": "youtube",
            "url": "https://www.youtube.com/@creator",
        })
        self.assertFalse(no_youtube_id["rss_supported"])
        self.assertEqual(no_youtube_id["rss_status"], "conditional")

        vimeo = activity_service.rss_capability({
            "platform": "vimeo",
            "url": "https://vimeo.com/example",
        })
        self.assertFalse(vimeo["rss_supported"])
        self.assertIn("descontinuados", vimeo["rss_reason"])

        dailymotion = activity_service.rss_capability({
            "platform": "dailymotion",
            "url": "https://www.dailymotion.com/user/example",
        })
        self.assertTrue(dailymotion["rss_supported"])
        self.assertEqual(
            dailymotion["rss_feed_url"],
            "https://www.dailymotion.com/rss/user/example",
        )

        soundcloud_profile = activity_service.rss_capability({
            "platform": "soundcloud",
            "url": "https://soundcloud.com/creator",
        })
        self.assertFalse(soundcloud_profile["rss_supported"])
        self.assertEqual(soundcloud_profile["rss_status"], "conditional")

        direct_feed = activity_service.rss_capability({
            "platform": "web",
            "url": "https://feeds.example/creator.atom",
        })
        self.assertTrue(direct_feed["rss_supported"])
        self.assertEqual(direct_feed["rss_status"], "conditional")

    def test_peer_tube_channel_feed_requires_channel_id_or_explicit_feed(self):
        capability = activity_service.rss_capability({
            "platform": "peertube",
            "url": "https://tube.example/c/channel",
            "channel_id": "channel-id",
        })
        self.assertTrue(capability["rss_supported"])
        self.assertEqual(
            capability["rss_feed_url"],
            "https://tube.example/feeds/videos.xml?videoChannelId=channel-id",
        )
        direct_feed = activity_service.rss_capability({
            "platform": "peertube",
            "url": "https://tube.example/feeds/videos.xml?videoChannelId=channel-id",
        })
        self.assertTrue(direct_feed["rss_supported"])

    def test_historical_downloads_influence_channel_proposal_ranking(self):
        old_media = self.downloads / "preferred.mp4"
        old_media.write_bytes(b"old")
        old_media.with_suffix(".info.json").write_text(
            json.dumps({
                "channel": "Preferred channel",
                "uploader": "Preferred uploader",
            }),
            encoding="utf-8",
        )
        (self.root / "history.json").write_text(
            json.dumps([{
                "url": "https://youtube.com/watch?v=old",
                "date": "2026-10-25T10:00:00+00:00",
                "status": "success",
                "file_path": "/downloads/preferred.mp4",
                "platform": "youtube",
            }]),
            encoding="utf-8",
        )
        activity = activity_service._empty_activity()

        activity_service._merge_historical_preferences(activity, str(self.root))
        proposals = activity_service.build_proposals(
            [{
                "id": "new",
                "url": "https://youtube.com/watch?v=new",
                "title": "New upload",
                "published": datetime.now(timezone.utc).isoformat(),
                "channel_id": "channel-id",
                "channel_name": "preferred channel",
                "author": "preferred uploader",
                "platform": "youtube",
            }],
            activity,
            {"automation_platforms": ["youtube"], "rss_proposals_max": 5},
            {"seen": [], "proposed": []},
        )

        self.assertEqual(len(proposals), 1)
        self.assertIn("canal frequente", proposals[0]["reason"])

    def test_failed_history_entries_do_not_suppress_rss_recommendations(self):
        (self.root / "history.json").write_text(
            json.dumps([
                {"url": "https://youtube.com/watch?v=failed", "status": "failed"},
                {"url": "https://youtube.com/watch?v=complete", "status": "success"},
            ]),
            encoding="utf-8",
        )

        self.assertEqual(
            activity_service._history_urls(str(self.root)),
            {"https://youtube.com/watch?v=complete"},
        )

    def test_service_instance_lock_is_released_on_shutdown(self):
        self.assertTrue(activity_service._acquire_instance(str(self.root)))
        self.assertTrue(activity_service.is_running(str(self.root)))
        activity_service._release_instance(str(self.root))
        self.assertFalse(activity_service.is_running(str(self.root)))


if __name__ == "__main__":
    unittest.main()
