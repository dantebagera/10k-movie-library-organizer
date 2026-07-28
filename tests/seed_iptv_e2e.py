import sys
from pathlib import Path

from services.iptv_provider_manager import IPTVProviderManager


def catalog(label):
    return {
        "live": {
            "categories": [{"category_id": "shared", "category_name": f"{label} Live"}],
            "items": [{"stream_id": "7", "category_id": "shared", "name": f"{label} Channel"}],
        },
        "movie": {
            "categories": [{"category_id": "shared", "category_name": f"{label} Movies"}],
            "items": [{
                "stream_id": "7",
                "category_id": "shared",
                "name": f"{label} Movie",
                "container_extension": "mp4",
            }],
        },
        "series": {
            "categories": [{"category_id": "shared", "category_name": f"{label} Series"}],
            "items": [{"series_id": "7", "category_id": "shared", "name": f"{label} Series"}],
        },
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Expected the isolated CP_TEST_ROOT")
    test_root = Path(sys.argv[1]).resolve()
    manager = IPTVProviderManager(test_root / "user-data", migrate_legacy=False)
    try:
        first = manager.create_provider(
            "Provider One",
            "https://provider-one.invalid",
            "fixture-one",
            "fixture-password-one",
            False,
        )
        second = manager.create_provider(
            "Provider Two",
            "https://provider-two.invalid",
            "fixture-two",
            "fixture-password-two",
            True,
        )
        first_service = manager.service(first["provider_id"])
        second_service = manager.service(second["provider_id"])
        first_service.store.replace_catalog(catalog("First"))
        second_service.store.replace_catalog(catalog("Second"))
        first_service.set_favorite("movie", "7", True)
        first_list = first_service.create_list("First fixture list")
        first_service.set_list_item(first_list["list_id"], "movie", "7", True)
        first_service.store.update_history("movie", "7", 12, 100, False)
        second_list = second_service.create_list("Second fixture list")
        second_service.set_list_item(second_list["list_id"], "series", "7", True)
        manager.set_selection(first["provider_id"])
    finally:
        manager.close()


if __name__ == "__main__":
    main()
