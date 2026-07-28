import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.iptv_provider_manager import IPTVProviderManager, _database_facts
from services.iptv_service import IPTVService


def catalog(prefix):
    return {
        "live": {
            "categories": [{"category_id": "same-category", "category_name": f"{prefix} Live"}],
            "items": [{"stream_id": "same-item", "category_id": "same-category", "name": f"{prefix} Channel"}],
        },
        "movie": {
            "categories": [{"category_id": "same-category", "category_name": f"{prefix} Movies"}],
            "items": [{"stream_id": "same-item", "category_id": "same-category", "name": f"{prefix} Movie"}],
        },
        "series": {
            "categories": [{"category_id": "same-category", "category_name": f"{prefix} Series"}],
            "items": [{"series_id": "same-item", "category_id": "same-category", "name": f"{prefix} Series"}],
        },
    }


class IPTVProviderManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.manager = IPTVProviderManager(self.temporary.name, migrate_legacy=False)

    def tearDown(self):
        self.manager.close()
        self.temporary.cleanup()

    def create(self, name="Provider A", server="https://provider.example", username="user-a"):
        return self.manager.create_provider(name, server, username, "fake-password", False)

    def test_registry_defaults_and_redacted_crud(self):
        self.assertEqual(self.manager.list_providers()["providers"], [])
        created = self.create()
        provider_id = created["provider_id"]

        self.assertRegex(provider_id, r"^[0-9a-f]{32}$")
        self.assertTrue(created["has_password"])
        self.assertTrue(created["has_username"])
        self.assertNotIn("password", created)
        self.assertNotIn("username", created)
        self.assertNotIn("fake-password", json.dumps(created))
        registry = json.loads(self.manager.registry_path.read_text(encoding="utf-8"))
        self.assertNotIn("fake-password", json.dumps(registry))
        self.assertNotIn("user-a", json.dumps(registry))

    def test_duplicate_account_rejected_but_same_server_different_user_allowed(self):
        self.create()
        with self.assertRaisesRegex(ValueError, "already configured"):
            self.create(name="Duplicate", username="user-a")
        second = self.create(name="Provider B", username="user-b")
        self.assertEqual(second["server_url"], "https://provider.example")
        self.assertEqual(self.manager.list_providers()["count"], 2)

    def test_blank_password_preserves_saved_password(self):
        created = self.create()
        provider_id = created["provider_id"]
        config_path = self.manager.service(provider_id).config_path
        before = json.loads(config_path.read_text(encoding="utf-8"))

        updated = self.manager.update_provider(
            provider_id,
            name="Renamed",
            server_url="https://renamed.example/",
            username="",
            password="",
            allow_insecure_tls=True,
        )
        after = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(after["password"], before["password"])
        self.assertEqual(after["username"], before["username"])
        self.assertEqual(updated["name"], "Renamed")
        self.assertTrue(updated["allow_insecure_tls"])

    def test_same_ids_catalog_and_user_state_are_isolated(self):
        first = self.create()
        second = self.create(name="Provider B", server="https://second.example", username="user-b")
        first_service = self.manager.service(first["provider_id"])
        second_service = self.manager.service(second["provider_id"])
        first_service.store.replace_catalog(catalog("First"))
        second_service.store.replace_catalog(catalog("Second"))
        first_service.set_favorite("movie", "same-item", True)
        custom = first_service.create_list("Keep")
        first_service.set_list_item(custom["list_id"], "movie", "same-item", True)
        first_service.store.update_history("movie", "same-item", 10, 100, False)
        first_service.store.cache_detail("movie", "same-item", {"info": {"plot": "First detail"}})
        second_service.store.cache_detail("movie", "same-item", {"info": {"plot": "Second detail"}})

        self.assertEqual(first_service.list_items("movie")["items"][0]["name"], "First Movie")
        self.assertEqual(second_service.list_items("movie")["items"][0]["name"], "Second Movie")
        self.assertEqual(first_service.list_favorites()["total"], 1)
        self.assertEqual(second_service.list_favorites()["total"], 0)
        self.assertEqual(len(first_service.lists()), 1)
        self.assertEqual(second_service.lists(), [])
        self.assertEqual(len(first_service.recent()), 1)
        self.assertEqual(second_service.recent(), [])
        self.assertNotEqual(
            first_service.store.get_cached_detail("movie", "same-item"),
            second_service.store.get_cached_detail("movie", "same-item"),
        )

    def test_images_epg_playback_roots_and_service_instances_are_isolated(self):
        class EPGClient:
            def __init__(self, title):
                self.title = title

            def short_epg(self, _stream_id, _limit):
                return [{"title": self.title, "description": ""}]

        first = self.create()
        second = self.create(name="Provider B", server="https://second.example", username="user-b")
        first_service = self.manager.service(first["provider_id"])
        second_service = self.manager.service(second["provider_id"])
        self.assertIs(first_service, self.manager.service(first["provider_id"]))
        self.assertIsNot(first_service, second_service)
        self.assertNotEqual(first_service.root, second_service.root)
        self.assertNotEqual(first_service.image_cache, second_service.image_cache)
        self.assertNotEqual(first_service.playback_root, second_service.playback_root)
        (first_service.image_cache / "same.jpg").write_bytes(b"first")
        (second_service.image_cache / "same.jpg").write_bytes(b"second")
        self.assertNotEqual(
            (first_service.image_cache / "same.jpg").read_bytes(),
            (second_service.image_cache / "same.jpg").read_bytes(),
        )
        with patch.object(first_service, "client", return_value=EPGClient("First EPG")), patch.object(
            second_service, "client", return_value=EPGClient("Second EPG")
        ):
            self.assertEqual(first_service.epg("same-item")[0]["title"], "First EPG")
            self.assertEqual(second_service.epg("same-item")[0]["title"], "Second EPG")
        for service, marker in ((first_service, b"first"), (second_service, b"second")):
            directory = service.playback_root / "same-token"
            directory.mkdir()
            (directory / "index.m3u8").write_bytes(marker)
            service._sessions["same-token"] = {
                "token": "same-token",
                "directory": directory,
                "process": None,
                "created_at": 0,
                "stopping": False,
            }
        self.assertNotEqual(
            first_service.playback_file("same-token", "index.m3u8").read_bytes(),
            second_service.playback_file("same-token", "index.m3u8").read_bytes(),
        )

    def test_sync_and_remove_one_provider_do_not_change_the_other(self):
        first = self.create()
        second = self.create(name="Provider B", server="https://second.example", username="user-b")
        first_service = self.manager.service(first["provider_id"])
        second_service = self.manager.service(second["provider_id"])
        first_service.store.replace_catalog(catalog("First"))
        second_service.store.replace_catalog(catalog("Second"))
        second_before = second_service.store.status()
        first_service.store.replace_catalog(catalog("First Updated"))
        second_root = second_service.root

        removed = self.manager.remove_provider(first["provider_id"], "Provider A")

        self.assertTrue(removed["success"])
        self.assertEqual(second_service.store.status(), second_before)
        self.assertTrue(second_root.is_dir())
        self.assertEqual(self.manager.list_providers()["count"], 1)

    def test_provider_sync_replaces_only_that_provider_catalog(self):
        class FakeClient:
            def authenticate(self):
                return {"user_info": {"status": "Active"}}

            def live_categories(self):
                return catalog("Synced")["live"]["categories"]

            def live_streams(self):
                return catalog("Synced")["live"]["items"]

            def movie_categories(self):
                return catalog("Synced")["movie"]["categories"]

            def movies(self):
                return catalog("Synced")["movie"]["items"]

            def series_categories(self):
                return catalog("Synced")["series"]["categories"]

            def series(self):
                return catalog("Synced")["series"]["items"]

        first = self.create()
        second = self.create(name="Provider B", server="https://second.example", username="user-b")
        first_service = self.manager.service(first["provider_id"])
        second_service = self.manager.service(second["provider_id"])
        first_service.store.replace_catalog(catalog("First"))
        second_service.store.replace_catalog(catalog("Second"))
        second_before = second_service.store.status()

        with patch.object(first_service, "client", return_value=FakeClient()):
            first_service._sync_worker()

        self.assertEqual(first_service.list_items("movie")["items"][0]["name"], "Synced Movie")
        self.assertEqual(second_service.list_items("movie")["items"][0]["name"], "Second Movie")
        self.assertEqual(second_service.store.status(), second_before)

    def test_removal_requires_exact_name_and_rejects_invalid_ids(self):
        created = self.create()
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.manager.remove_provider(created["provider_id"], "provider a")
        with self.assertRaises(KeyError):
            self.manager.service("../outside")
        self.assertTrue(self.manager.service(created["provider_id"]).root.is_dir())

    def test_error_redaction_removes_credentials_and_query_secrets(self):
        created = self.create()
        message = self.manager.redacted_error(
            "failed username=user-a&password=fake-password for user-a",
            created["provider_id"],
        )
        self.assertNotIn("user-a", message)
        self.assertNotIn("fake-password", message)
        self.assertIn("[redacted]", message)


class IPTVLegacyMigrationTests(unittest.TestCase):
    def _legacy(self, root):
        legacy_root = Path(root) / "iptv"
        service = IPTVService(legacy_root, "legacy-fixture")
        service.save_config("https://legacy.example", "legacy-user", "legacy-password", True)
        service.store.replace_catalog(catalog("Legacy"))
        service.set_favorite("movie", "same-item", True)
        custom = service.create_list("Legacy List")
        service.set_list_item(custom["list_id"], "live", "same-item", True)
        service.store.update_history("movie", "same-item", 23, 100, False)
        service.store.cache_detail("movie", "same-item", {"info": {"plot": "Cached"}})
        (service.image_cache / "cached.jpg").write_bytes(b"fixture-image")
        (service.playback_root / "old-session").mkdir()
        service.close()
        return legacy_root

    def test_full_migration_preserves_state_excludes_playback_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            legacy_root = self._legacy(temporary)
            before = _database_facts(legacy_root / "iptv.sqlite")

            manager = IPTVProviderManager(temporary)
            first = manager.list_providers()
            provider = first["providers"][0]
            provider_id = provider["provider_id"]
            migrated_root = Path(temporary) / "iptv" / "providers" / provider_id
            after = _database_facts(migrated_root / "iptv.sqlite")
            backups = list((Path(temporary) / "iptv" / "migration-backups").iterdir())

            self.assertEqual(provider["name"], "Lionz")
            self.assertEqual(before, after)
            self.assertEqual(provider["counts"], {"live": 1, "movie": 1, "series": 1})
            self.assertEqual(manager.service(provider_id).list_favorites()["total"], 1)
            self.assertEqual(len(manager.service(provider_id).lists()), 1)
            self.assertEqual(len(manager.service(provider_id).recent()), 1)
            self.assertFalse((migrated_root / "playback" / "old-session").exists())
            self.assertFalse((legacy_root / "playback").exists())
            self.assertFalse((legacy_root / "provider.json").exists())
            self.assertFalse((legacy_root / "iptv.sqlite").exists())
            self.assertEqual(len(backups), 1)
            manager.close()

            restarted = IPTVProviderManager(temporary)
            try:
                self.assertEqual(
                    restarted.list_providers()["providers"][0]["provider_id"],
                    provider_id,
                )
                self.assertEqual(
                    len(list((Path(temporary) / "iptv" / "migration-backups").iterdir())),
                    1,
                )
            finally:
                restarted.close()

    def test_interrupted_migration_rolls_back_legacy_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            legacy_root = self._legacy(temporary)
            before = _database_facts(legacy_root / "iptv.sqlite")
            original = IPTVProviderManager._save_registry

            def fail_registry(manager, registry):
                if registry.get("providers"):
                    raise OSError("fixture interruption")
                return original(manager, registry)

            with patch.object(IPTVProviderManager, "_save_registry", fail_registry):
                with self.assertRaisesRegex(OSError, "fixture interruption"):
                    IPTVProviderManager(temporary)

            self.assertTrue((legacy_root / "provider.json").is_file())
            self.assertEqual(_database_facts(legacy_root / "iptv.sqlite"), before)
            self.assertTrue((legacy_root / "images" / "cached.jpg").is_file())
            self.assertFalse((legacy_root / "providers.json").exists())
            provider_entries = [
                path for path in (legacy_root / "providers").iterdir()
                if not path.name.startswith(".")
            ]
            self.assertEqual(provider_entries, [])

    def test_config_only_migration_and_corrupt_registry_handling(self):
        with tempfile.TemporaryDirectory() as temporary:
            legacy_root = Path(temporary) / "iptv"
            legacy_root.mkdir()
            (legacy_root / "provider.json").write_text(json.dumps({
                "server_url": "https://legacy.example",
                "username": "legacy-user",
                "password": "legacy-password",
                "allow_insecure_tls": False,
            }), encoding="utf-8")
            manager = IPTVProviderManager(temporary)
            try:
                provider = manager.list_providers()["providers"][0]
                self.assertEqual(provider["name"], "Lionz")
                self.assertEqual(provider["counts"], {"live": 0, "movie": 0, "series": 0})
            finally:
                manager.close()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "iptv"
            root.mkdir()
            (root / "providers.json").write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unreadable"):
                IPTVProviderManager(temporary)


if __name__ == "__main__":
    unittest.main()
