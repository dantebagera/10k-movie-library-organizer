import unittest
import json

from services.youtube_playlist import (
    YouTubePlaylistError,
    YouTubePlaylistFeed,
    YouTubeService,
    merge_balanced_trailers,
    parse_youtube_playlist_feed,
)


PLAYLIST_ID = "PLScC8g4bqD47c-qHlsfhGH3j6Bg7jzFy-"
FEED_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/">
  <yt:playlistId>{PLAYLIST_ID}</yt:playlistId>
  <title>HOT New Trailers &amp; Exclusives</title>
  <entry>
    <yt:videoId>abc_DEF-123</yt:videoId>
    <title>Example Trailer #1</title>
    <published>2026-07-28T12:00:00+00:00</published>
    <media:group>
      <media:community><media:statistics views="12345"/></media:community>
    </media:group>
  </entry>
  <entry>
    <yt:videoId>abc_DEF-123</yt:videoId>
    <title>Duplicate</title>
  </entry>
  <entry>
    <yt:videoId>not valid!</yt:videoId>
    <title>Unsafe</title>
  </entry>
</feed>"""


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.content.encode("utf-8")


class YouTubePlaylistTests(unittest.TestCase):
    def test_parser_returns_only_sanitized_unique_items(self):
        payload = parse_youtube_playlist_feed(FEED_XML, PLAYLIST_ID)

        self.assertEqual(payload["title"], "HOT New Trailers & Exclusives")
        self.assertEqual(payload["source_url"], f"https://www.youtube.com/playlist?list={PLAYLIST_ID}")
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0], {
            "video_id": "abc_DEF-123",
            "title": "Example Trailer #1",
            "url": "https://www.youtube.com/watch?v=abc_DEF-123",
            "thumbnail_url": "https://i.ytimg.com/vi/abc_DEF-123/hqdefault.jpg",
            "published_at": "2026-07-28T12:00:00+00:00",
            "views": 12345,
        })

    def test_parser_rejects_an_unexpected_playlist(self):
        with self.assertRaisesRegex(YouTubePlaylistError, "wrong playlist"):
            parse_youtube_playlist_feed(FEED_XML, "another-playlist")

    def test_feed_caches_success_and_returns_stale_data_after_refresh_failure(self):
        calls = []
        clock = [100.0]

        def opener(_request, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                return FakeResponse(FEED_XML)
            raise OSError("offline")

        feed = YouTubePlaylistFeed(
            PLAYLIST_ID,
            cache_ttl_seconds=10,
            timeout_seconds=4,
            opener=opener,
            clock=lambda: clock[0],
        )

        fresh = feed.get()
        cached = feed.get()
        self.assertFalse(fresh["stale"])
        self.assertFalse(cached["stale"])
        self.assertEqual(calls, [4])

        clock[0] = 111.0
        stale = feed.get()
        self.assertTrue(stale["stale"])
        self.assertEqual(calls, [4, 4])

    def test_feed_reports_failure_when_no_cached_copy_exists(self):
        def opener(_request, timeout):
            raise OSError(f"offline after {timeout}")

        feed = YouTubePlaylistFeed(PLAYLIST_ID, opener=opener)
        with self.assertRaisesRegex(YouTubePlaylistError, "temporarily unavailable"):
            feed.get()

    def test_multi_source_api_fetches_fifty_and_returns_a_cursor(self):
        calls = []
        def opener(request, timeout):
            calls.append(request.full_url)
            source_id = "rt-video" if "playlist-a" in request.full_url else "mts-video"
            return FakeResponse(json.dumps({
                "items": [{
                    "snippet": {
                        "title": f"{source_id} Trailer (2027)",
                        "publishedAt": "2026-08-09T12:00:00Z",
                        "resourceId": {"videoId": f"{source_id}-01"},
                        "thumbnails": {},
                    },
                    "contentDetails": {"videoId": f"{source_id}-01"},
                }],
                "nextPageToken": f"next-{source_id}",
            }))

        service = YouTubeService([
            {"id": "rt", "name": "RT", "playlist_id": "playlist-a", "source_url": "https://youtube.test/rt"},
            {"id": "mts", "name": "MTS", "playlist_id": "playlist-b", "source_url": "https://youtube.test/mts"},
        ], api_key="configured", opener=opener)
        payload = service.get_home_trailers()

        self.assertEqual(len(calls), 2)
        self.assertTrue(all("maxResults=50" in url for url in calls))
        self.assertEqual({item["source_id"] for item in payload["items"]}, {"rt", "mts"})
        self.assertTrue(payload["has_more"])
        self.assertTrue(payload["next_cursor"])
        self.assertFalse(payload["fallback"])

    def test_balancer_prevents_three_same_source_items_when_an_alternative_exists(self):
        groups = {
            "rt": [{"video_id": f"rt-{index:02d}", "title": f"RT {index}", "published_at": f"2026-08-09T12:0{9-index}:00Z"} for index in range(5)],
            "mts": [{"video_id": f"mts-{index:02d}", "title": f"MTS {index}", "published_at": "2026-08-08T12:00:00Z"} for index in range(2)],
        }
        merged = merge_balanced_trailers(groups)
        source_order = [item["video_id"].split("-")[0] for item in merged]
        self.assertNotIn(["rt", "rt", "rt"], [source_order[index:index + 3] for index in range(len(source_order) - 2)])

    def test_search_returns_picker_when_candidates_are_equally_confident(self):
        response = {
            "items": [
                {"id": {"videoId": "candidate001"}, "snippet": {"title": "Example (2027) Official Trailer", "channelTitle": "A", "publishedAt": "2026-08-09T00:00:00Z", "thumbnails": {}}},
                {"id": {"videoId": "candidate002"}, "snippet": {"title": "Example (2027) Official Trailer", "channelTitle": "B", "publishedAt": "2026-08-08T00:00:00Z", "thumbnails": {}}},
            ]
        }
        service = YouTubeService([
            {"id": "rt", "name": "RT", "playlist_id": "playlist-a", "source_url": "https://youtube.test/rt"},
        ], api_key="configured", opener=lambda _request, timeout: FakeResponse(json.dumps(response)))
        result = service.search_trailers("Example", "2027")
        self.assertEqual(result["status"], "choose")
        self.assertEqual(len(result["candidates"]), 2)

    def test_finished_source_is_not_restarted_while_another_source_has_more_pages(self):
        calls = []
        def opener(request, timeout):
            calls.append(request.full_url)
            if "playlist-a" in request.full_url:
                return FakeResponse(json.dumps({"items": []}))
            if "pageToken=next-b" in request.full_url:
                return FakeResponse(json.dumps({"items": []}))
            return FakeResponse(json.dumps({"items": [], "nextPageToken": "next-b"}))

        service = YouTubeService([
            {"id": "a", "name": "A", "playlist_id": "playlist-a", "source_url": "https://youtube.test/a"},
            {"id": "b", "name": "B", "playlist_id": "playlist-b", "source_url": "https://youtube.test/b"},
        ], api_key="configured", opener=opener)
        first = service.get_home_trailers()
        second = service.get_home_trailers(cursor=first["next_cursor"])

        self.assertEqual(sum("playlist-a" in url for url in calls), 1)
        self.assertEqual(sum("playlist-b" in url for url in calls), 2)
        self.assertFalse(second["has_more"])
        self.assertEqual(second["next_cursor"], "")


if __name__ == "__main__":
    unittest.main()
