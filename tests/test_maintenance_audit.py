import json
import unittest

from services.media_file_facts import FILE_FACTS_VERSION, QUALITY_CLASSIFIER_VERSION
from services.maintenance_audit import build_maintenance_audit


def candidate(path, **record):
    resolution = record.get("resolution", "1080p")
    dimensions = {
        "4K": (3840, 2160),
        "1080p": (1920, 1080),
        "720p": (1280, 720),
        "480p": (854, 480),
    }.get(resolution, (0, 0))
    raw = {
        "path": path,
        "filename": path.rsplit("/", 1)[-1],
        "library_root": "E:/Movies",
        "resolution": "1080p",
        "rip_source": "WEB-DL",
        "size": 100,
        "identity_status": "accepted",
        "metadata_accepted": True,
        "identity_title": "Alien",
        "identity_year": "1979",
        "tmdb_id": "348",
        "decision_origin": "user_manual",
        "video_width": dimensions[0],
        "video_height": dimensions[1],
        "video_codec": "AVC",
        "video_profile": "High",
        "video_bit_depth": 8,
        "video_bitrate": 5_000_000,
        "video_frame_rate": 24.0,
        "duration_ms": 100_000,
        "audio_codec": "AAC",
        "audio_channels": 2,
        "audio_bitrate": 192_000,
        "audio_tracks_json": "[]",
        "filename_quality_claim": resolution,
        "quality_class": resolution,
        "quality_source": "measured",
        "quality_conflict": False,
        "file_facts_version": FILE_FACTS_VERSION,
        "classifier_version": QUALITY_CLASSIFIER_VERSION,
        "probe_status": "ok",
        **record,
    }
    result = {
        "path": path,
        "raw_json": raw,
        "resolution": raw["resolution"],
        "rip_source": raw["rip_source"],
        "size": raw["size"],
        "identity_status": raw["identity_status"],
        "metadata_status": raw.get("metadata_status", raw["identity_status"]),
        "metadata_accepted": raw["metadata_accepted"],
        "identity_title": raw.get("identity_title", ""),
        "identity_year": raw.get("identity_year", ""),
        "tmdb_id": raw.get("tmdb_id", ""),
        "imdb_id": raw.get("imdb_id", ""),
        "plex_guid": raw.get("plex_guid", ""),
        "library_root": raw["library_root"],
        "plex_json": {},
        "manual_json": {},
        "tmdb_json": {
            "tmdb_id": raw.get("tmdb_id", ""),
            "imdb_id": raw.get("imdb_id", ""),
            "title": raw.get("identity_title", ""),
            "year": raw.get("identity_year", ""),
        } if raw.get("tmdb_id") else {},
    }
    return result


class MaintenanceAuditTest(unittest.TestCase):
    def test_projects_storage_upgrades_and_identity_from_one_catalog_snapshot(self):
        audit = build_maintenance_audit([
            candidate("E:/Movies/Alien.1979.4K.Remux.mkv", resolution="4K", rip_source="Remux", size=400),
            candidate("E:/Movies/Alien.1979.1080p.WEB-DL.mkv", size=100),
            candidate(
                "E:/Movies/Heat.1995.720p.WEB-DL.mkv",
                identity_title="Heat",
                identity_year="1995",
                tmdb_id="949",
                resolution="720p",
            ),
            candidate(
                "E:/Movies/Unsorted/Deep/Unknown.2025.mkv",
                identity_status="review",
                metadata_status="review",
                metadata_accepted=False,
                identity_title="",
                identity_year="",
                tmdb_id="",
            ),
        ], generation=42)

        self.assertEqual(audit["source"], "catalog")
        self.assertEqual(audit["generation"], 42)
        self.assertEqual(audit["summary"]["duplicate_groups"], 1)
        self.assertEqual(audit["summary"]["recommended_removals"], 1)
        self.assertEqual(audit["summary"]["upgrade_candidates"], 1)
        self.assertEqual(audit["upgrades"]["items"][0]["title"], "Heat")
        self.assertEqual(audit["summary"]["identity_issues"], 1)
        self.assertEqual(audit["summary"]["unmatched_files"], 1)
        self.assertEqual(audit["summary"]["verification_gaps"], 0)
        self.assertTrue(audit["identity"]["items"][0]["fixable_path"])

    def test_conflicting_strong_ids_never_become_a_duplicate_group(self):
        audit = build_maintenance_audit([
            candidate("E:/Movies/Shared.2000.One.mkv", identity_title="Shared", identity_year="2000", tmdb_id="100"),
            candidate("E:/Movies/Shared.2000.Two.mkv", identity_title="Shared", identity_year="2000", tmdb_id="200"),
        ])

        self.assertEqual(audit["storage"]["groups"], [])

    def test_title_and_year_drift_is_not_a_conflict(self):
        drift = candidate(
            "E:/Movies/Conflict.One.mkv",
            identity_title="The Lost Chapter",
            identity_year="2025",
            tmdb_id="100",
        )
        drift["plex_json"] = {"plex_title": "The Lost Chapter Extended", "plex_year": "2024", "tmdb_id": "100"}

        audit = build_maintenance_audit([drift])

        self.assertEqual(audit["summary"]["hard_conflicts"], 0)
        self.assertEqual(audit["summary"]["verification_gaps"], 0)
        self.assertEqual(audit["identity"]["verification"], [])

    def test_public_id_conflict_is_separate_from_unmatched_repair(self):
        conflict = candidate("E:/Movies/Conflict.mkv", tmdb_id="100")
        conflict["plex_json"] = {"plex_title": "Other Movie", "plex_year": "2025", "tmdb_id": "999"}

        audit = build_maintenance_audit([conflict])

        self.assertEqual(audit["summary"]["hard_conflicts"], 1)
        self.assertEqual(audit["summary"]["verification_gaps"], 1)
        self.assertEqual(audit["identity"]["items"], [])
        self.assertEqual(audit["identity"]["verification"][0]["metadata_status"], "conflict")

    def test_unverified_duplicate_is_visible_but_never_recommended_automatically(self):
        first = candidate(
            "E:/Movies/Frailty.2001.One.mkv",
            identity_title="Temptation's Hour",
            identity_year="2001",
            tmdb_id="1387467",
            parsed_title="Frailty",
            parsed_year="2001",
            resolution="720p",
        )
        second = candidate(
            "E:/Movies/Frailty.2001.Two.mkv",
            identity_title="Temptation's Hour",
            identity_year="2001",
            tmdb_id="1387467",
            parsed_title="Frailty",
            parsed_year="2001",
            resolution="720p",
        )
        for item in (first, second):
            item["plex_json"] = {"plex_title": "Frailty", "plex_year": "2001"}

        audit = build_maintenance_audit([first, second])

        self.assertEqual(len(audit["storage"]["groups"]), 1)
        group = audit["storage"]["groups"][0]
        self.assertFalse(group["identity_safe"])
        self.assertTrue(group["needs_identity_review"])
        self.assertEqual(group["files"][1]["recommendation"], "review")
        self.assertEqual(audit["summary"]["recommended_removals"], 0)
        self.assertEqual(audit["upgrades"]["items"], [])
        self.assertEqual(audit["summary"]["verification_gaps"], 2)

    def test_shared_tmdb_identity_is_safe_without_a_plex_snapshot(self):
        best = candidate(
            "E:/Movies/Alien.1979.4K.Remux.mkv",
            resolution="4K",
            rip_source="Remux",
            size=400,
            decision_origin="library_reconcile",
        )
        lower = candidate(
            "E:/Movies/Alien.1979.1080p.WEB-DL.mkv",
            resolution="1080p",
            rip_source="WEB-DL",
            size=100,
        )
        lower["plex_json"] = {
            "plex_title": "Alien",
            "plex_year": "1979",
            "tmdb_id": "348",
        }

        audit = build_maintenance_audit([best, lower])

        group = audit["storage"]["groups"][0]
        self.assertEqual(group["files"][0]["verification_status"], "audit_pending")
        self.assertTrue(group["identity_safe"])
        self.assertFalse(group["needs_identity_review"])
        self.assertEqual(group["files"][1]["recommendation"], "recommended")
        self.assertEqual(audit["summary"]["recommended_removals"], 1)

    def test_provider_audit_backlog_is_separate_from_manual_identity_review(self):
        pending = candidate(
            "E:/Movies/Elle.2016.mkv",
            identity_title="Elle",
            identity_year="2016",
            tmdb_id="337674",
            decision_origin="identity_audit",
        )

        audit = build_maintenance_audit([pending])

        self.assertEqual(audit["summary"]["automated_identity_checks"], 1)
        self.assertEqual(audit["summary"]["verification_gaps"], 0)
        self.assertEqual(audit["identity"]["verification"], [])

    def test_the_monkey_encode_tradeoff_is_never_an_automatic_removal(self):
        avc = candidate(
            "E:/Movies/The.Monkey.2025.1080p.x264.mkv",
            identity_title="The Monkey",
            identity_year="2025",
            tmdb_id="1124620",
            video_width=1800,
            video_height=960,
            video_codec="AVC",
            video_profile="High@L4.1",
            video_bit_depth=8,
            video_bitrate=2_250_404,
            size=1_720_266_381,
            quality_nonstandard=True,
        )
        hevc = candidate(
            "E:/Movies/The.Monkey.2025.1080p.x265.10bit.mkv",
            identity_title="The Monkey",
            identity_year="2025",
            tmdb_id="1124620",
            video_width=1800,
            video_height=960,
            video_codec="HEVC",
            video_profile="Main 10@L4@Main",
            video_bit_depth=10,
            video_bitrate=2_000_527,
            size=1_539_806_886,
            quality_nonstandard=True,
        )

        audit = build_maintenance_audit([avc, hevc])

        group = audit["storage"]["groups"][0]
        self.assertTrue(group["identity_safe"])
        self.assertEqual(group["recommended_count"], 0)
        self.assertEqual(group["reclaimable_bytes"], 0)
        self.assertEqual(
            {row["verdict"] for row in group["files"]},
            {"encoding_tradeoff"},
        )
        self.assertEqual(
            {row["role"] for row in group["files"]},
            {"tradeoff"},
        )
        self.assertTrue(all(row["recommendation"] == "review" for row in group["files"]))
        self.assertTrue(all("cross-codec quality cannot be proven" in row["reason"] for row in group["files"]))
        self.assertTrue(all("172.1 MB (10.5%)" in row["reason"] for row in group["files"]))
        self.assertEqual(
            {row["quality_display"] for row in group["files"]},
            {"1080-class - 1800 x 960"},
        )

    def test_lolita_minor_crop_does_not_hide_a_decisive_resolution_winner(self):
        high = candidate(
            "E:/Movies/Lolita.1997.1080p.BluRay.x264.YIFY.mp4",
            identity_title="Lolita",
            identity_year="1997",
            tmdb_id="9769",
            imdb_id="tt0119558",
            video_width=1920,
            video_height=1040,
            video_bitrate=2_041_000,
            duration_ms=8_260_000,
            audio_bitrate=93_848,
            size=2_254_000_000,
        )
        low = candidate(
            "E:/Movies/Lolita.1997.720p.BluRay.x264.YIFY.mp4",
            identity_title="Lolita",
            identity_year="1997",
            tmdb_id="9769",
            imdb_id="tt0119558",
            resolution="720p",
            video_width=1280,
            video_height=688,
            video_bitrate=847_000,
            duration_ms=8_260_000,
            audio_bitrate=93_848,
            size=975_000_000,
        )

        audit = build_maintenance_audit([low, high])

        group = audit["storage"]["groups"][0]
        self.assertEqual(group["recommended_count"], 1)
        self.assertEqual(group["files"][0]["verdict"], "recommended_keep")
        self.assertEqual(group["files"][1]["verdict"], "recommended_removal")
        self.assertIn("2.27× fewer pixels", group["files"][1]["reason"])
        self.assertIn("framing differs by 0.77% (minor crop)", group["files"][1]["reason"])

    def test_vamps_frame_rate_timing_normalization_supports_content_equivalence_not_quality(self):
        bluray = candidate(
            "E:/Movies/Vamps.2012.1080p.BRrip.x264.YIFY.mp4",
            identity_title="Vamps",
            identity_year="2012",
            tmdb_id="73935",
            imdb_id="tt1545106",
            video_width=1920,
            video_height=1036,
            video_frame_rate=23.976,
            video_codec="AVC",
            video_profile="High@L4",
            video_bitrate=2_062_000,
            duration_ms=5_558_468,
            audio_codec="AAC",
            audio_channels=2,
            audio_bitrate=96_000,
            size=1_500_000_000,
        )
        dvd = candidate(
            "E:/Movies/Vamps.2012.DVDRip.XviD-PTpOWeR.avi",
            identity_title="Vamps",
            identity_year="2012",
            tmdb_id="73935",
            imdb_id="tt1545106",
            resolution="336p",
            quality_class="336p",
            video_width=624,
            video_height=336,
            video_frame_rate=25.0,
            video_codec="MPEG-4 Visual",
            video_profile="Simple@L3",
            video_bitrate=968_433,
            duration_ms=5_330_320,
            audio_codec="MPEG Audio",
            audio_channels=2,
            audio_bitrate=128_000,
            size=739_000_000,
        )

        audit = build_maintenance_audit([dvd, bluray])

        group = audit["storage"]["groups"][0]
        self.assertEqual(group["recommended_count"], 1)
        self.assertEqual(group["files"][0]["verdict"], "recommended_keep")
        self.assertEqual(group["files"][1]["verdict"], "recommended_removal")
        self.assertTrue(group["files"][1]["comparison_uses_frame_rate"])
        self.assertIn("9.49× fewer pixels", group["files"][1]["reason"])
        self.assertIn("23.976 and 25 fps timing normalization", group["files"][1]["reason"])
        self.assertIn("estimated frame count matches within 0.01%", group["files"][1]["reason"])

    def test_shorter_keeper_requires_review_when_deletion_candidate_is_longer(self):
        high = candidate("E:/Movies/Alien.1979.1080p.mkv")
        low = candidate(
            "E:/Movies/Alien.1979.720p.different.mkv",
            resolution="720p",
            duration_ms=120_000,
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        self.assertEqual(group["recommended_count"], 0)
        self.assertEqual(group["files"][0]["verdict"], "quality_winner_verify_cut")
        self.assertEqual(group["files"][1]["verdict"], "lower_quality_verify_cut")
        self.assertIn("deletion candidate is 20.0s longer", group["files"][1]["reason"])

    def test_better_video_does_not_auto_delete_superior_primary_audio(self):
        high = candidate("E:/Movies/Alien.1979.1080p.stereo.mkv")
        low = candidate(
            "E:/Movies/Alien.1979.720p.5.1.mkv",
            resolution="720p",
            audio_channels=6,
            audio_bitrate=640_000,
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        self.assertEqual(group["recommended_count"], 0)
        self.assertEqual(group["files"][0]["verdict"], "quality_winner_verify_cut")
        self.assertEqual(group["files"][1]["verdict"], "quality_tradeoff")
        self.assertIn("better primary audio", group["files"][1]["reason"])
        self.assertTrue(any(
            "better primary audio" in blocker
            for blocker in group["files"][1]["decision_blockers"]
        ))

    def test_decisive_video_can_trade_lossy_surround_for_stereo_with_warning(self):
        high = candidate("E:/Movies/Alien.1979.1080p.stereo.mkv")
        low = candidate(
            "E:/Movies/Alien.1979.480p.5.1.mkv",
            resolution="480p",
            audio_codec="AC-3",
            audio_channels=6,
            audio_bitrate=448_000,
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        removal = next(row for row in group["files"] if row["resolution"] == "480p")
        self.assertEqual(group["recommended_count"], 1)
        self.assertEqual(removal["verdict"], "recommended_removal")
        self.assertEqual(removal["decision_blockers"], [])
        self.assertTrue(any(
            "4x-or-greater pixel advantage" in warning
            for warning in removal["decision_warnings"]
        ))

    def test_four_times_video_overrides_lossless_surround_audio_with_warning(self):
        high = candidate("E:/Movies/Alien.1979.1080p.stereo.mkv")
        low = candidate(
            "E:/Movies/Alien.1979.480p.lossless.5.1.mkv",
            resolution="480p",
            audio_codec="FLAC",
            audio_channels=6,
            audio_bitrate=1_500_000,
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        removal = next(row for row in group["files"] if row["resolution"] == "480p")
        self.assertEqual(group["recommended_count"], 1)
        self.assertEqual(removal["recommendation"], "recommended")
        self.assertTrue(any(
            "4x-or-greater pixel advantage" in warning
            for warning in removal["decision_warnings"]
        ))

    def test_equivalent_video_selects_the_better_primary_audio(self):
        stereo = candidate("E:/Movies/Alien.1979.1080p.stereo.mkv")
        surround = candidate(
            "E:/Movies/Alien.1979.1080p.surround.mkv",
            audio_channels=6,
            audio_bitrate=640_000,
        )

        audit = build_maintenance_audit([stereo, surround])

        group = audit["storage"]["groups"][0]
        removal = next(row for row in group["files"] if row["filename"].endswith("stereo.mkv"))
        keeper = next(row for row in group["files"] if row["filename"].endswith("surround.mkv"))
        self.assertEqual(group["recommended_count"], 1)
        self.assertEqual(removal["verdict"], "recommended_removal")
        self.assertEqual(keeper["verdict"], "recommended_keep")
        self.assertIn("equivalent video quality", removal["reason"])

    def test_audio_language_loss_warns_but_does_not_cancel_quality_selection(self):
        high = candidate(
            "E:/Movies/Alien.1979.1080p.mkv",
            audio_tracks_json=json.dumps([
                {"language": "eng", "codec": "AAC", "channels": 2},
            ]),
        )
        low = candidate(
            "E:/Movies/Alien.1979.720p.multi.mkv",
            resolution="720p",
            audio_tracks_json=json.dumps([
                {"language": "eng", "codec": "AAC", "channels": 2},
                {"language": "fra", "codec": "AAC", "channels": 2},
            ]),
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        removal = next(row for row in group["files"] if row["resolution"] == "720p")
        keeper = next(row for row in group["files"] if row["resolution"] == "1080p")
        self.assertEqual(removal["recommendation"], "recommended")
        self.assertEqual(removal["audio_language_losses"], ["French"])
        self.assertTrue(any("loses audio language" in warning.lower() for warning in removal["decision_warnings"]))
        self.assertEqual(keeper["audio_language_losses"], [])
        self.assertFalse(any("loses audio language" in warning.lower() for warning in keeper["decision_warnings"]))

    def test_frame_rate_does_not_outvote_resolution(self):
        high = candidate(
            "E:/Movies/Alien.1979.1080p.23fps.mkv",
            video_frame_rate=23.976,
        )
        low = candidate(
            "E:/Movies/Alien.1979.720p.60fps.mkv",
            resolution="720p",
            video_frame_rate=60,
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        removal = next(row for row in group["files"] if row["resolution"] == "720p")
        self.assertEqual(removal["recommendation"], "recommended")
        self.assertFalse(removal["comparison_uses_frame_rate"])

    def test_decisive_video_accepts_framing_difference_up_to_three_percent(self):
        high = candidate(
            "E:/Movies/The.Bay.2012.1080p.mkv",
            identity_title="The Bay",
            identity_year="2012",
            tmdb_id="33266",
            video_width=1920,
            video_height=1008,
        )
        low = candidate(
            "E:/Movies/The.Bay.2012.480p.avi",
            identity_title="The Bay",
            identity_year="2012",
            tmdb_id="33266",
            resolution="480p",
            video_width=720,
            video_height=368,
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        removal = next(row for row in group["files"] if row["resolution"] == "480p")
        self.assertEqual(group["recommended_count"], 1)
        self.assertEqual(removal["verdict"], "recommended_removal")
        self.assertIn("framing differs by 2.65%", removal["reason"])

    def test_decisive_video_still_blocks_framing_difference_over_three_percent(self):
        high = candidate(
            "E:/Movies/Alien.1979.1080p.mkv",
            video_width=1920,
            video_height=1080,
        )
        low = candidate(
            "E:/Movies/Alien.1979.480p.cropped.mkv",
            resolution="480p",
            video_width=720,
            video_height=360,
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        removal = next(row for row in group["files"] if row["resolution"] == "480p")
        self.assertEqual(group["recommended_count"], 0)
        self.assertEqual(removal["recommendation"], "review")
        self.assertTrue(any(
            "automatic selection allows up to 3.00%" in blocker
            for blocker in removal["decision_blockers"]
        ))

    def test_decisive_video_accepts_runtime_difference_within_point_seven_five_percent(self):
        high = candidate(
            "E:/Movies/Alien.1979.1080p.mkv",
            duration_ms=5_723_135,
        )
        low = candidate(
            "E:/Movies/Alien.1979.480p.mkv",
            resolution="480p",
            duration_ms=5_692_542,
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        removal = next(row for row in group["files"] if row["resolution"] == "480p")
        self.assertEqual(group["recommended_count"], 1)
        self.assertEqual(removal["verdict"], "recommended_removal")
        self.assertIn("keeper is 30.6s longer", removal["reason"])

    def test_longer_keeper_is_safe_without_a_symmetric_sixty_second_cap(self):
        high = candidate(
            "E:/Movies/Alien.1979.1080p.mkv",
            duration_ms=10_800_000,
        )
        low = candidate(
            "E:/Movies/Alien.1979.480p.long-cut.mkv",
            resolution="480p",
            duration_ms=10_739_000,
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        removal = next(row for row in group["files"] if row["resolution"] == "480p")
        self.assertEqual(group["recommended_count"], 1)
        self.assertEqual(removal["recommendation"], "recommended")
        self.assertIn("keeper is 61.0s longer", removal["reason"])

    def test_longer_keeper_is_safe_even_below_four_times_pixels_when_audio_is_not_worse(self):
        high = candidate(
            "E:/Movies/The.Cured.2017.1080p.mkv",
            identity_title="The Cured",
            identity_year="2017",
            tmdb_id="469721",
            video_width=1920,
            video_height=800,
            duration_ms=5_723_135,
        )
        low = candidate(
            "E:/Movies/The.Cured.2017.720p.mkv",
            identity_title="The Cured",
            identity_year="2017",
            tmdb_id="469721",
            resolution="720p",
            video_width=1280,
            video_height=528,
            duration_ms=5_692_542,
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        removal = next(row for row in group["files"] if row["resolution"] == "720p")
        self.assertEqual(group["recommended_count"], 1)
        self.assertEqual(removal["recommendation"], "recommended")
        self.assertIn("keeper is 30.6s longer", removal["reason"])

    def test_hollow_man_missing_bitrates_and_dc_marker_warn_without_blocking(self):
        high = candidate(
            "E:/Movies/Hollow.Man.2000.1080p.BluRay.x264.AAC5.1.mp4",
            identity_title="Hollow Man",
            identity_year="2000",
            tmdb_id="9383",
            imdb_id="tt0164052",
            resolution="1080p",
            rip_source="Blu-ray",
            video_width=1918,
            video_height=1040,
            video_bitrate=2_250_000,
            duration_ms=7_155_148,
            audio_channels=6,
            audio_bitrate=384_000,
            size=2_360_616_680,
        )
        low = candidate(
            "E:/Movies/Hollow.Man.2000.DC.720p.BRRip.x264.YIFY.mkv",
            identity_title="Hollow Man",
            identity_year="2000",
            tmdb_id="9383",
            imdb_id="tt0164052",
            resolution="720p",
            rip_source="BDRip",
            video_width=1280,
            video_height=692,
            video_bitrate=0,
            duration_ms=7_155_155,
            audio_channels=2,
            audio_bitrate=0,
            size=790_852_266,
        )

        audit = build_maintenance_audit([low, high])

        group = audit["storage"]["groups"][0]
        rows = {row["filename"]: row for row in group["files"]}
        removal = rows["Hollow.Man.2000.DC.720p.BRRip.x264.YIFY.mkv"]
        self.assertEqual(group["recommended_count"], 1)
        self.assertEqual(removal["recommendation"], "recommended")
        self.assertEqual(removal["verdict"], "recommended_removal")
        self.assertEqual(removal["decision_blockers"], [])
        self.assertTrue(any("video bitrate" in warning for warning in removal["decision_warnings"]))
        self.assertTrue(any("primary-audio bitrate" in warning for warning in removal["decision_warnings"]))
        self.assertTrue(any("Director's Cut" in warning for warning in removal["decision_warnings"]))
        self.assertTrue(any("runtime" in passed for passed in removal["decision_passed"]))
        self.assertTrue(any("2.25x" in passed for passed in removal["decision_passed"]))

    def test_resolution_hierarchy_is_not_overturned_by_filename_source_or_bit_depth(self):
        cases = {
            "source": {
                "high": {"rip_source": "WEBRip"},
                "low": {"rip_source": "Blu-ray"},
                "reason": "lower source tier",
            },
            "bit_depth": {
                "high": {"video_bit_depth": 8},
                "low": {"video_bit_depth": 10},
                "reason": "8-bit versus 10-bit",
            },
        }
        for name, values in cases.items():
            with self.subTest(name=name):
                high = candidate(
                    f"E:/Movies/Alien.1979.1080p.{name}.mkv",
                    **values["high"],
                )
                low = candidate(
                    f"E:/Movies/Alien.1979.720p.{name}.mkv",
                    resolution="720p",
                    **values["low"],
                )

                audit = build_maintenance_audit([high, low])

                group = audit["storage"]["groups"][0]
                self.assertEqual(group["recommended_count"], 1)
                candidate_row = next(row for row in group["files"] if row["resolution"] == "720p")
                self.assertEqual(candidate_row["verdict"], "recommended_removal")

    def test_multi_file_group_uses_pairwise_dominance_instead_of_one_reference(self):
        high = candidate("E:/Movies/Alien.1979.4K.mkv", resolution="4K", video_bitrate=12_000_000)
        middle = candidate("E:/Movies/Alien.1979.1080p.mkv", video_bitrate=5_000_000)
        low = candidate("E:/Movies/Alien.1979.720p.mkv", resolution="720p", video_bitrate=3_000_000)

        audit = build_maintenance_audit([middle, low, high])

        group = audit["storage"]["groups"][0]
        self.assertEqual(group["recommended_count"], 2)
        verdicts = {row["filename"]: row["verdict"] for row in group["files"]}
        self.assertEqual(verdicts["Alien.1979.4K.mkv"], "recommended_keep")
        self.assertEqual(verdicts["Alien.1979.1080p.mkv"], "recommended_removal")
        self.assertEqual(verdicts["Alien.1979.720p.mkv"], "recommended_removal")

    def test_duplicate_dominance_matrix_blocks_uncertain_differences(self):
        base = candidate("E:/Movies/Alien.1979.1080p.reference.mkv")
        cases = {
            "missing": {"probe_status": "corrupt"},
            "conflict": {"quality_conflict": True},
            "codec": {"video_codec": "HEVC"},
            "bit_depth": {"video_bit_depth": 10},
            "duration": {"duration_ms": 120_000},
            "audio_codec": {"audio_codec": "DTS"},
            "aspect": {"video_width": 1440, "video_height": 1080},
            "edition": {"filename": "Alien.1979.Extended.1080p.mkv"},
        }
        for name, changes in cases.items():
            with self.subTest(name=name):
                other = candidate(f"E:/Movies/Alien.1979.{name}.mkv", **changes)
                audit = build_maintenance_audit([base, other])
                group = audit["storage"]["groups"][0]
                self.assertEqual(group["recommended_count"], 0)
                self.assertEqual(group["files"][1]["recommendation"], "review")

    def test_strong_lower_dimensions_are_recommended_with_safe_content_evidence(self):
        high = candidate(
            "E:/Movies/Alien.1979.1080p.mkv",
            video_bitrate=5_000_000,
        )
        low = candidate(
            "E:/Movies/Alien.1979.720p.mkv",
            resolution="720p",
            video_bitrate=3_000_000,
        )

        audit = build_maintenance_audit([high, low])

        group = audit["storage"]["groups"][0]
        self.assertEqual(group["recommended_count"], 1)
        self.assertEqual(group["files"][1]["recommendation"], "recommended")
        self.assertEqual(group["files"][1]["verdict"], "recommended_removal")
        self.assertIn("2.25× fewer pixels", group["files"][1]["reason"])


if __name__ == "__main__":
    unittest.main()
