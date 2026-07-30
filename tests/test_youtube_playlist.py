import unittest

from services.youtube_playlist import (
    YouTubePlaylistError,
    YouTubePlaylistFeed,
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


if __name__ == "__main__":
    unittest.main()
