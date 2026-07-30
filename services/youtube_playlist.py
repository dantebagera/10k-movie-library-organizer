import copy
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET


ATOM_NS = "http://www.w3.org/2005/Atom"
MEDIA_NS = "http://search.yahoo.com/mrss/"
YOUTUBE_NS = "http://www.youtube.com/xml/schemas/2015"
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


class YouTubePlaylistError(RuntimeError):
    pass


def parse_youtube_playlist_feed(xml_text, expected_playlist_id):
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, TypeError, ValueError) as error:
        raise YouTubePlaylistError("YouTube returned an invalid playlist feed") from error

    playlist_id = str(root.findtext(f"{{{YOUTUBE_NS}}}playlistId") or "").strip()
    if playlist_id != expected_playlist_id:
        raise YouTubePlaylistError("YouTube returned the wrong playlist")

    items = []
    seen = set()
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        video_id = str(entry.findtext(f"{{{YOUTUBE_NS}}}videoId") or "").strip()
        title = str(entry.findtext(f"{{{ATOM_NS}}}title") or "").strip()
        if not VIDEO_ID_PATTERN.fullmatch(video_id) or not title or video_id in seen:
            continue
        seen.add(video_id)
        statistics = entry.find(
            f"{{{MEDIA_NS}}}group/{{{MEDIA_NS}}}community/{{{MEDIA_NS}}}statistics"
        )
        try:
            views = max(0, int(statistics.attrib.get("views", "0"))) if statistics is not None else 0
        except (TypeError, ValueError):
            views = 0
        items.append({
            "video_id": video_id,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "published_at": str(entry.findtext(f"{{{ATOM_NS}}}published") or "").strip(),
            "views": views,
        })

    return {
        "playlist_id": playlist_id,
        "title": str(root.findtext(f"{{{ATOM_NS}}}title") or "YouTube playlist").strip(),
        "source_url": f"https://www.youtube.com/playlist?list={playlist_id}",
        "items": items,
        "stale": False,
    }


class YouTubePlaylistFeed:
    def __init__(
        self,
        playlist_id,
        *,
        cache_ttl_seconds=900,
        timeout_seconds=6,
        opener=None,
        clock=None,
    ):
        self.playlist_id = str(playlist_id or "").strip()
        if not self.playlist_id:
            raise ValueError("playlist_id is required")
        self.cache_ttl_seconds = max(1, int(cache_ttl_seconds))
        self.timeout_seconds = max(1, int(timeout_seconds))
        self._opener = opener or urllib.request.urlopen
        self._clock = clock or time.monotonic
        self._cache = None
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    @property
    def feed_url(self):
        return (
            "https://www.youtube.com/feeds/videos.xml?playlist_id="
            f"{self.playlist_id}"
        )

    def _read_feed(self):
        request = urllib.request.Request(
            self.feed_url,
            headers={
                "Accept": "application/atom+xml, application/xml, text/xml",
                "User-Agent": "CinemaParadiso/1.0",
            },
        )
        with self._opener(request, timeout=self.timeout_seconds) as response:
            return response.read().decode("utf-8")

    def get(self):
        now = self._clock()
        with self._lock:
            if self._cache is not None and now - self._fetched_at < self.cache_ttl_seconds:
                return copy.deepcopy(self._cache)

        try:
            payload = parse_youtube_playlist_feed(self._read_feed(), self.playlist_id)
        except Exception as error:
            with self._lock:
                if self._cache is not None:
                    stale = copy.deepcopy(self._cache)
                    stale["stale"] = True
                    return stale
            if isinstance(error, YouTubePlaylistError):
                raise
            raise YouTubePlaylistError("YouTube playlist is temporarily unavailable") from error

        with self._lock:
            self._cache = copy.deepcopy(payload)
            self._fetched_at = now
        return payload
