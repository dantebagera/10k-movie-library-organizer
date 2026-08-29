import json
import unittest
import socket
import time
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import app


class FakeResponse:
    def __init__(self, payload, raw=False):
        self.payload = payload
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        if self.raw:
            data = self.payload.encode("utf-8")
        else:
            data = json.dumps(self.payload).encode("utf-8")
        return data if size is None or size < 0 else data[:size]


class YtsOption2Tests(unittest.TestCase):
    def setUp(self):
        self.original_url = app._prowlarr_url
        self.original_key = app._prowlarr_key
        self.original_tmdb_key = app._tmdb_key
        self.original_trusted = app._trusted_release_indexers
        self.original_trusted_configured = app._trusted_release_indexers_configured
        app._prowlarr_url = "http://prowlarr.test"
        app._prowlarr_key = "prowlarr-key"
        app._tmdb_key = ""
        app._trusted_release_indexers = ["1"]
        app._trusted_release_indexers_configured = True

    def tearDown(self):
        app._prowlarr_url = self.original_url
        app._prowlarr_key = self.original_key
        app._tmdb_key = self.original_tmdb_key
        app._trusted_release_indexers = self.original_trusted
        app._trusted_release_indexers_configured = self.original_trusted_configured

    def test_explore_search_queries_prowlarr_by_imdb_before_title_year(self):
        requested_queries = []

        def fake_urlopen(request, timeout=0):
            url = request.full_url
            if url.endswith("/api/v1/indexer"):
                return FakeResponse([{"id": 1, "name": "YTS", "enable": True}])
            if "/api/v1/search" in url:
                query = parse_qs(urlparse(url).query).get("query", [""])[0]
                requested_queries.append(query)
                if query == "tt37287335":
                    return FakeResponse([
                        {
                            "title": "Obsession (2025) 1080p WEBRip 5.1 x264 -YTS",
                            "indexer": "YTS",
                            "seeders": 0,
                            "size": 2000,
                            "magnetUrl": "magnet:?xt=urn:btih:69E81483386084CB786D5B9E3E9692DE72A446C5",
                            "downloadUrl": "http://prowlarr.test/download/obsession",
                            "infoUrl": "https://yts.gg/movies/obsession-2025",
                        }
                    ])
                return FakeResponse([])
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
            response = app.app.test_client().get(
                "/api/explore/search?title=Obsession&year=2025&imdb_id=tt37287335"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(requested_queries[0], "tt37287335")
        self.assertEqual(response.get_json()["variants"][0]["title"], "Obsession (2025) 1080p WEBRip 5.1 x264 -YTS")

    def test_explore_search_rejects_polluted_imdb_results_before_title_fallback(self):
        requested_queries = []

        def fake_urlopen(request, timeout=0):
            url = request.full_url
            if url.endswith("/api/v1/indexer"):
                return FakeResponse([{"id": 1, "name": "YTS", "enable": True}])
            if "/api/v1/search" in url:
                query = parse_qs(urlparse(url).query).get("query", [""])[0]
                requested_queries.append(query)
                if query == "tt37287335":
                    return FakeResponse([
                        {
                            "title": "Obsession (2026) 2160p WEB-DL x265",
                            "indexer": "Other",
                            "seeders": 50,
                            "size": 9000,
                            "magnetUrl": "magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                            "infoUrl": "https://example.test/wrong",
                        }
                    ])
                if query == "Obsession 2025":
                    return FakeResponse([
                        {
                            "title": "Obsession (2025) 1080p WEBRip 5.1 x264 -YTS",
                            "indexer": "YTS",
                            "seeders": 0,
                            "size": 2000,
                            "magnetUrl": "magnet:?xt=urn:btih:69E81483386084CB786D5B9E3E9692DE72A446C5",
                            "downloadUrl": "http://prowlarr.test/download/obsession",
                            "infoUrl": "https://yts.gg/movies/obsession-2025",
                        }
                    ])
                return FakeResponse([])
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
            response = app.app.test_client().get(
                "/api/explore/search?title=Obsession&year=2025&imdb_id=tt37287335"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(requested_queries[:2], ["tt37287335", "Obsession 2025"])
        self.assertEqual(response.get_json()["variants"][0]["title"], "Obsession (2025) 1080p WEBRip 5.1 x264 -YTS")

    def test_explore_search_keeps_a_prowlarr_redirect_as_a_download_url(self):
        def fake_urlopen(request, timeout=0):
            url = request.full_url
            if url.endswith("/api/v1/indexer"):
                return FakeResponse([{"id": 6, "name": "The Pirate Bay", "enable": True}])
            if "/api/v1/search" in url:
                return FakeResponse([
                    {
                        "title": "Citizen.Vigilante.2026.1080p.WEBRip.x265",
                        "indexer": "The Pirate Bay",
                        "seeders": 99,
                        "size": 2000,
                        "magnetUrl": "http://prowlarr.test/prowlarr/6/download?id=1",
                        "downloadUrl": None,
                        "infoHash": "0123456789ABCDEF0123456789ABCDEF01234567",
                        "infoUrl": "https://thepiratebay.org/description.php?id=1",
                    }
                ])
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
            response = app.app.test_client().get(
                "/api/explore/search?title=Citizen%20Vigilante&year=2026"
            )

        self.assertEqual(response.status_code, 200)
        variant = response.get_json()["variants"][0]
        self.assertEqual(variant["magnet_url"], "")
        self.assertEqual(variant["download_url"], "http://prowlarr.test/prowlarr/6/download?id=1")
        self.assertEqual(variant["info_hash"], "0123456789abcdef0123456789abcdef01234567")

    def test_explore_search_falls_back_to_tmdb_alternative_title(self):
        app._tmdb_key = "tmdb-key"
        requested_queries = []

        def fake_urlopen(request, timeout=0):
            url = request.full_url
            if url.endswith("/api/v1/indexer"):
                return FakeResponse([{"id": 1, "name": "YTS", "enable": True}])
            if "/api/v1/search" in url:
                query = parse_qs(urlparse(url).query).get("query", [""])[0]
                requested_queries.append(query)
                if query == "Diamanti 2024":
                    return FakeResponse([
                        {
                            "title": "Diamanti (2024) [1080p] [WEBRip] [5 1]",
                            "indexer": "YTS",
                            "seeders": 41,
                            "size": 2500,
                            "magnetUrl": "magnet:?xt=urn:btih:69E81483386084CB786D5B9E3E9692DE72A446C5",
                            "downloadUrl": "http://prowlarr.test/download/diamanti",
                            "infoUrl": "https://yts.gg/movies/diamanti-2024",
                        }
                    ])
                return FakeResponse([])
            raise AssertionError(f"Unexpected URL: {url}")

        with (
            patch("app._fetch_tmdb_metadata_by_id", return_value={"imdb_id": "", "original_title": "Diamanti"}),
            patch("app._smart_match_tmdb_alternative_titles", return_value=["Diamanti", "Diamond", "Diamonds"]),
            patch("app.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            response = app.app.test_client().get(
                "/api/explore/search?title=Diamonds&year=2024&tmdb_id=1299046"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(requested_queries[:2], ["Diamonds 2024", "Diamanti 2024"])
        self.assertEqual(response.get_json()["variants"][0]["title"], "Diamanti (2024) [1080p] [WEBRip] [5 1]")

    def test_prowlarr_match_accepts_alias_titles_but_rejects_wrong_year(self):
        movie = {
            "title": "Diamonds",
            "year": "2024",
            "title_aliases": ["Diamanti"],
        }

        self.assertTrue(app._prowlarr_result_matches_movie(
            {"title": "Diamanti.2024.iTA.WEBDL.1080p.x264"},
            movie,
        ))
        self.assertFalse(app._prowlarr_result_matches_movie(
            {"title": "Diamanti.2023.iTA.WEBDL.1080p.x264"},
            movie,
        ))

    def test_splice_source_evidence_keeps_primary_and_earliest_tmdb_years(self):
        metadata = {
            "tmdb_id": "37707",
            "imdb_id": "tt1017460",
            "title": "Splice",
            "original_title": "Splice",
            "release_date": "2010-06-03",
            "release_years": ["2010", "2009", "2011"],
            "release_years_checked_at": 1,
        }

        with (
            patch("app._movie_tmdb_metadata_for_source_search", return_value=metadata),
            patch("app._smart_match_tmdb_alternative_titles", return_value=[]),
        ):
            movie = app._movie_with_source_title_aliases({
                "title": "Splice",
                "year": "2010",
                "tmdb_id": "37707",
            })

        self.assertEqual(movie["imdb_id"], "tt1017460")
        self.assertEqual(movie["release_years"], ["2010", "2009"])
        self.assertEqual(app._movie_release_queries(movie)[:3], [
            "tt1017460",
            "Splice 2010",
            "Splice 2009",
        ])
        self.assertTrue(app._prowlarr_result_matches_movie(
            {"title": "Splice (2009) 1080p BRRip x264 -YTS"},
            movie,
        ))
        self.assertFalse(app._prowlarr_result_matches_movie(
            {"title": "Splice (2011) 1080p WEB-DL x264"},
            movie,
        ))

    def test_movie_search_merges_and_deduplicates_results_across_queries(self):
        requested_queries = []
        shared = {
            "title": "Splice (2009) 1080p BRRip x264 -YTS",
            "indexer": "YTS",
            "infoHash": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        }
        alternate = {
            "title": "Splice (2010) 720p BluRay x264",
            "indexer": "YTS",
            "infoHash": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
        }

        def fake_search(indexer_ids=None, query="", limit=100, categories="2000", timeout=30):
            requested_queries.append(query)
            if query == "tt1017460":
                return [shared]
            if query == "Splice 2010":
                return [shared, alternate]
            return []

        enriched = {
            "title": "Splice",
            "year": "2010",
            "release_years": ["2010", "2009"],
            "imdb_id": "tt1017460",
            "title_aliases": ["Splice"],
        }
        with (
            patch("app._movie_with_source_title_aliases", return_value=enriched),
            patch("app._prowlarr_search", side_effect=fake_search),
        ):
            results = app._prowlarr_search_movie(["1"], enriched)

        self.assertEqual(requested_queries, ["tt1017460", "Splice 2010", "Splice 2009"])
        self.assertEqual([row["infoHash"] for row in results], [
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
        ])

    def test_progressive_indexer_search_merges_queries_and_keeps_all_qualities(self):
        shared = {
            "title": "Splice (2009) 1080p BRRip x264 -YTS",
            "indexer": "YTS",
            "infoHash": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        }
        lower_quality = {
            "title": "Splice (2009) 720p BRRip x264 -YTS",
            "indexer": "YTS",
            "infoHash": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
        }

        def fake_search(indexer_ids=None, query="", limit=100, categories="2000", timeout=30):
            if query == "tt1017460":
                return [shared]
            if query == "Splice 2009":
                return [shared, lower_quality]
            return []

        movie = {
            "title": "Splice",
            "year": "2010",
            "release_years": ["2010", "2009"],
            "imdb_id": "tt1017460",
            "title_aliases": ["Splice"],
        }
        with patch("app._prowlarr_search", side_effect=fake_search):
            outcome = app._search_movie_on_single_indexer(
                {"id": "1", "name": "YTS"},
                movie,
                app._movie_release_queries(movie),
                deadline_seconds=10,
            )

        variants = app._torrent_variants_from_prowlarr_results(outcome["results"])
        self.assertEqual(len(outcome["results"]), 2)
        self.assertEqual([row["resolution"] for row in variants], ["1080p", "720p"])
        self.assertEqual(variants[0]["info_hash"], "a" * 40)

    def test_movie_search_stops_when_global_deadline_is_exhausted(self):
        requested_timeouts = []

        def fake_search(indexer_ids=None, query="", limit=100, categories="2000", timeout=30):
            requested_timeouts.append((query, timeout))
            raise socket.timeout("timed out")

        with (
            patch("app._movie_with_source_title_aliases", return_value={
                "title": "Alias Heavy",
                "year": "2026",
                "title_aliases": ["Alias Heavy", "Alias One", "Alias Two"],
            }),
            patch("app._prowlarr_search", side_effect=fake_search),
            patch("app.time.monotonic", side_effect=[100, 100, 110, 112]),
        ):
            results = app._prowlarr_search_movie(
                ["1"],
                {"title": "Alias Heavy", "year": "2026"},
                timeout=10,
                deadline_seconds=12,
            )

        self.assertEqual(results, [])
        self.assertEqual(requested_timeouts, [
            ("Alias Heavy 2026", 10),
            ("Alias One 2026", 2),
        ])

    def test_movie_search_uses_remaining_budget_for_each_alias_query(self):
        requested_timeouts = []

        def fake_search(indexer_ids=None, query="", limit=100, categories="2000", timeout=30):
            requested_timeouts.append((query, timeout))
            return []

        with (
            patch("app._movie_with_source_title_aliases", return_value={
                "title": "Alias Heavy",
                "year": "2026",
                "title_aliases": ["Alias Heavy", "Alias One", "Alias Two"],
            }),
            patch("app._prowlarr_search", side_effect=fake_search),
            patch("app.time.monotonic", side_effect=[100, 100, 109, 119]),
        ):
            results = app._prowlarr_search_movie(
                ["1"],
                {"title": "Alias Heavy", "year": "2026"},
                timeout=10,
                deadline_seconds=25,
            )

        self.assertEqual(results, [])
        self.assertEqual(requested_timeouts, [
            ("Alias Heavy 2026", 10),
            ("Alias One 2026", 10),
            ("Alias Two 2026", 6),
        ])

    def test_progressive_source_search_job_keeps_fast_results_when_one_indexer_times_out(self):
        requested = []

        def fake_search(indexer_ids=None, query="", limit=100, categories="2000", timeout=30):
            requested.append((tuple(indexer_ids or []), query, timeout))
            if indexer_ids == ["1"]:
                return [
                    {
                        "title": "Love in the Time of Cholera (2007) 1080p BRRip 5.1 x264 -YTS",
                        "indexer": "YTS",
                        "seeders": 22,
                        "size": 2000,
                        "magnetUrl": "magnet:?xt=urn:btih:69E81483386084CB786D5B9E3E9692DE72A446C5",
                        "downloadUrl": "http://prowlarr.test/download/cholera",
                        "infoUrl": "https://yts.gg/movies/love-in-the-time-of-cholera-2007",
                    }
                ]
            raise socket.timeout("timed out")

        with (
            patch("app._fetch_enabled_prowlarr_indexers", return_value=[
                {"id": "1", "name": "YTS"},
                {"id": "6", "name": "The Pirate Bay"},
            ]),
            patch("app._prowlarr_search", side_effect=fake_search),
        ):
            client = app.app.test_client()
            response = client.post("/api/explore/search/jobs", json={
                "title": "Love in the Time of Cholera",
                "year": "2007",
            })
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            search_id = data["search_id"]
            for _ in range(30):
                status_response = client.get(f"/api/explore/search/jobs/{search_id}")
                data = status_response.get_json()
                if data["status"] == "complete":
                    break
                time.sleep(0.02)

        self.assertEqual(data["status"], "complete")
        self.assertEqual(data["variants"][0]["indexer"], "YTS")
        self.assertEqual(data["variants"][0]["title"], "Love in the Time of Cholera (2007) 1080p BRRip 5.1 x264 -YTS")
        self.assertIn("The Pirate Bay", data["timed_out_indexers"])
        self.assertIn((("1",), "Love in the Time of Cholera 2007", app.SOURCE_SEARCH_INDEXER_TIMEOUT_SECONDS), requested)

    def test_followed_release_queries_trusted_yts_by_imdb_before_title_year(self):
        requested_queries = []

        def fake_urlopen(request, timeout=0):
            url = request.full_url
            if url.endswith("/api/v1/indexer"):
                return FakeResponse([{"id": 1, "name": "YTS", "enable": True}])
            if "/api/v1/search" in url:
                query = parse_qs(urlparse(url).query).get("query", [""])[0]
                requested_queries.append(query)
                if query == "tt37287335":
                    return FakeResponse([
                        {
                            "title": "Obsession (2025) 1080p WEBRip 5.1 x264 -YTS",
                            "indexer": "YTS",
                            "seeders": 0,
                            "size": 2000,
                            "magnetUrl": "magnet:?xt=urn:btih:69E81483386084CB786D5B9E3E9692DE72A446C5",
                            "downloadUrl": "http://prowlarr.test/download/obsession",
                            "infoUrl": "https://yts.gg/movies/obsession-2025",
                        }
                    ])
                return FakeResponse([])
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("app.urllib.request.urlopen", side_effect=fake_urlopen), \
             patch("app._yts_source_imdb_id", return_value="tt37287335"):
            release = app._find_best_followed_release({
                "title": "Obsession",
                "year": "2025",
                "imdb_id": "tt37287335",
            })

        self.assertEqual(requested_queries[0], "tt37287335")
        self.assertEqual(release["title"], "Obsession (2025) 1080p WEBRip 5.1 x264 -YTS")

    def test_yts_source_page_identity_is_cached_and_uses_the_movie_imdb_link(self):
        source_url = "https://yts.mx/movies/the-odyssey-2-2026"
        calls = []

        def fake_urlopen(request, timeout=0):
            calls.append((request.full_url, timeout))
            return FakeResponse(
                '<a href="https://www.imdb.com/title/tt33764258/">IMDb</a>',
                raw=True,
            )

        app._yts_source_identity_cache.clear()
        with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
            first = app._yts_source_imdb_id(source_url)
            second = app._yts_source_imdb_id(source_url)

        self.assertEqual(first, "tt33764258")
        self.assertEqual(second, "tt33764258")
        self.assertEqual(len(calls), 1)

    def test_source_search_rejects_yts_page_that_proves_a_different_movie(self):
        def fake_search(*, query, **_kwargs):
            return [
                {
                    "title": "The Odyssey (2026) 1080p WEBRip 5.1 x264 -YTS",
                    "indexer": "YTS",
                    "infoUrl": "https://yts.gg/movies/the-odyssey-2026",
                    "infoHash": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                },
                {
                    "title": "The Odyssey (2026) 1080p WEBRip 5.1 x264 -YTS",
                    "indexer": "YTS",
                    "infoUrl": "https://yts.gg/movies/the-odyssey-2-2026",
                    "infoHash": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
                },
            ]

        def source_imdb(url, **_kwargs):
            return "tt41605854" if url.endswith("the-odyssey-2026") else "tt33764258"

        with patch("app._prowlarr_search", side_effect=fake_search), \
             patch("app._yts_source_imdb_id", side_effect=source_imdb):
            results = app._prowlarr_search_movie(
                ["1"],
                {"title": "The Odyssey", "year": "2026", "imdb_id": "tt33764258"},
                enriched=True,
            )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["infoUrl"].endswith("the-odyssey-2-2026"))
        self.assertTrue(results[0]["source_identity_verified"])

    def test_followed_rss_requires_verified_yts_identity_when_the_movie_has_imdb(self):
        rows = [{
            "variants": [{
                "title": "The Odyssey (2026) 1080p WEBRip 5.1 x264 -YTS",
                "resolution": "1080p",
                "magnet_url": "magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                "info_url": "https://yts.gg/movies/the-odyssey-2026",
                "indexer": "YTS RSS",
            }, {
                "title": "The Odyssey (2026) 1080p WEBRip 5.1 x264 -YTS",
                "resolution": "1080p",
                "magnet_url": "magnet:?xt=urn:btih:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
                "info_url": "https://yts.gg/movies/the-odyssey-2-2026",
                "indexer": "YTS RSS",
            }],
        }]

        def source_imdb(url, **_kwargs):
            return "tt41605854" if url.endswith("the-odyssey-2026") else "tt33764258"

        with patch("app._yts_source_imdb_id", side_effect=source_imdb):
            release = app._followed_rss_release(
                {"title": "The Odyssey", "year": "2026", "imdb_id": "tt33764258"},
                rows,
            )

        self.assertIsNotNone(release)
        self.assertTrue(release["info_url"].endswith("the-odyssey-2-2026"))

    def test_followed_rss_never_auto_accepts_a_title_only_match(self):
        release = app._followed_rss_release(
            {"title": "The Odyssey", "year": "2026"},
            [{"variants": [{
                "title": "The Odyssey (2026) 1080p WEBRip -YTS",
                "resolution": "1080p",
                "magnet_url": "magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                "info_url": "https://yts.gg/movies/the-odyssey-2026",
            }]}],
        )

        self.assertIsNone(release)

    def test_available_followed_yts_release_is_rechecked_only_when_its_page_proves_a_mismatch(self):
        movie = {
            "imdb_id": "tt33764258",
            "best_release": {
                "indexer": "YTS RSS",
                "info_url": "https://yts.gg/movies/the-odyssey-2026",
            },
        }
        with patch("app._yts_source_imdb_id", return_value="tt41605854"):
            self.assertTrue(app._followed_release_has_mismatched_yts_identity(movie))
        with patch("app._yts_source_imdb_id", return_value=""):
            self.assertFalse(app._followed_release_has_mismatched_yts_identity(movie))

    def test_yts_browse_latest_supplements_prowlarr_with_rss_freshness(self):
        rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
  <item>
    <title><![CDATA[Dos Manzanas (2023) [1080p] [WEBRip] [5.1] [YTS.GG-YTS.BZ]]]></title>
    <description><![CDATA[Dos Manzanas is an RSS metadata fixture.]]></description>
    <link>https://yts.gg/movies/dos-manzanas-2023</link>
    <guid>https://yts.gg/movies/dos-manzanas-2023#1080p.web</guid>
    <pubDate>Mon, 29 Jun 2026 23:52:18 +0200</pubDate>
    <enclosure url="https://yts.gg/torrent/download/69E81483386084CB786D5B9E3E9692DE72A446C5" type="application/x-bittorrent" length="10000" />
  </item>
</channel></rss>"""
        requested_urls = []

        def fake_urlopen(request, timeout=0):
            url = request.full_url if hasattr(request, "full_url") else str(request)
            requested_urls.append(url)
            if url.endswith("/api/v1/indexer"):
                return FakeResponse([{"id": 1, "name": "YTS", "enable": True}])
            if "/api/v1/search" in url:
                return FakeResponse([])
            if url == "https://yts.gg/rss":
                return FakeResponse(rss, raw=True)
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
            response = app.app.test_client().get("/api/explore/browse?latest=1&indexer_id=1")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["results"][0]["parsed_title"], "Dos Manzanas")
        self.assertEqual(data["results"][0]["variants"][0]["indexer"], "YTS RSS")
        self.assertTrue(data["results"][0]["variants"][0]["magnet_url"].startswith("magnet:?xt=urn:btih:"))
        self.assertEqual(
            data["results"][0]["variants"][0]["info_hash"],
            "69e81483386084cb786d5b9e3e9692de72a446c5",
        )
        self.assertIn("Dos Manzanas", data["results"][0]["variants"][0]["rss_description"])
        self.assertEqual(data["results"][0]["variants"][0]["rss_published_at"], "Mon, 29 Jun 2026 23:52:18 +0200")
        self.assertIn("https://yts.gg/rss", requested_urls)


if __name__ == "__main__":
    unittest.main()
