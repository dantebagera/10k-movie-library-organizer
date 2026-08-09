import base64
import copy
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


ATOM_NS = "http://www.w3.org/2005/Atom"
MEDIA_NS = "http://search.yahoo.com/mrss/"
YOUTUBE_NS = "http://www.youtube.com/xml/schemas/2015"
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
YOUTUBE_API_ROOT = "https://www.googleapis.com/youtube/v3"


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
        if (
            not VIDEO_ID_PATTERN.fullmatch(video_id)
            or not title
            or title.casefold() in {"private video", "deleted video"}
            or video_id in seen
        ):
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


def _published_sort_key(item):
    return str(item.get("published_at") or "")


def _narrow_trailer_key(item):
    title = re.sub(r"\s+", " ", str(item.get("title") or "").casefold()).strip()
    published_day = str(item.get("published_at") or "")[:10]
    return title, published_day


def merge_balanced_trailers(groups):
    """Merge newest-first source groups without long same-channel runs."""
    buckets = {
        source_id: sorted(items, key=_published_sort_key, reverse=True)
        for source_id, items in groups.items()
    }
    merged = []
    seen_video_ids = set()
    seen_exact_reposts = set()
    recent_sources = []

    while any(buckets.values()):
        available = [source_id for source_id, items in buckets.items() if items]
        blocked = recent_sources[-1] if len(recent_sources) >= 2 and recent_sources[-2:] == [recent_sources[-1]] * 2 else ""
        eligible = [source_id for source_id in available if source_id != blocked] or available
        selected_source = max(eligible, key=lambda source_id: _published_sort_key(buckets[source_id][0]))
        item = buckets[selected_source].pop(0)
        video_id = str(item.get("video_id") or "")
        repost_key = _narrow_trailer_key(item)
        if video_id in seen_video_ids or repost_key in seen_exact_reposts:
            continue
        seen_video_ids.add(video_id)
        seen_exact_reposts.add(repost_key)
        merged.append(item)
        recent_sources.append(selected_source)
    return merged


class YouTubeService:
    """Authoritative owner for channel playlists and on-demand trailer search."""

    def __init__(
        self,
        sources,
        *,
        api_key="",
        cache_ttl_seconds=1800,
        timeout_seconds=8,
        opener=None,
        clock=None,
    ):
        self.sources = {
            str(source["id"]): dict(source)
            for source in sources
            if source.get("id") and source.get("playlist_id")
        }
        if not self.sources:
            raise ValueError("at least one YouTube source is required")
        self.api_key = str(api_key or "").strip()
        self.cache_ttl_seconds = max(1, int(cache_ttl_seconds))
        self.timeout_seconds = max(1, int(timeout_seconds))
        self._opener = opener or urllib.request.urlopen
        self._clock = clock or time.monotonic
        self._cache = {}
        self._search_cache = {}
        self._lock = threading.Lock()

    def set_api_key(self, api_key):
        api_key = str(api_key or "").strip()
        with self._lock:
            if api_key != self.api_key:
                self.api_key = api_key
                self._cache = {}
                self._search_cache = {}

    def _request_json(self, path, params, *, api_key=None):
        request_params = dict(params)
        request_params["key"] = str(self.api_key if api_key is None else api_key).strip()
        url = f"{YOUTUBE_API_ROOT}/{path}?{urllib.parse.urlencode(request_params)}"
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "CinemaParadiso/1.0"})
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:
            raise YouTubePlaylistError("YouTube Data API is temporarily unavailable") from error

    @staticmethod
    def _decorate_item(item, source):
        decorated = dict(item)
        decorated.update({
            "source_id": source["id"],
            "source_name": source["name"],
            "source_url": source["source_url"],
            "playlist_id": source["playlist_id"],
        })
        return decorated

    def _api_playlist_page(self, source, page_token=""):
        params = {
            "part": "snippet,contentDetails",
            "playlistId": source["playlist_id"],
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token
        data = self._request_json("playlistItems", params)
        items = []
        seen = set()
        for raw in data.get("items", []) or []:
            snippet = raw.get("snippet") or {}
            video_id = str((raw.get("contentDetails") or {}).get("videoId") or snippet.get("resourceId", {}).get("videoId") or "").strip()
            title = str(snippet.get("title") or "").strip()
            if (
                not VIDEO_ID_PATTERN.fullmatch(video_id)
                or not title
                or title.casefold() in {"private video", "deleted video"}
                or video_id in seen
            ):
                continue
            seen.add(video_id)
            thumbnails = snippet.get("thumbnails") or {}
            thumbnail = next((thumbnails.get(size, {}).get("url") for size in ("high", "medium", "default") if thumbnails.get(size, {}).get("url")), "")
            items.append(self._decorate_item({
                "video_id": video_id,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail_url": thumbnail or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "published_at": str(snippet.get("publishedAt") or "").strip(),
                "views": 0,
            }, source))
        return {
            "items": items,
            "next_page_token": str(data.get("nextPageToken") or ""),
            "stale": False,
            "fallback": False,
        }

    def _xml_fallback_page(self, source):
        feed = YouTubePlaylistFeed(
            source["playlist_id"],
            cache_ttl_seconds=self.cache_ttl_seconds,
            timeout_seconds=self.timeout_seconds,
            opener=self._opener,
            clock=self._clock,
        )
        payload = feed.get()
        return {
            "items": [self._decorate_item(item, source) for item in payload.get("items", [])],
            "next_page_token": "",
            "stale": bool(payload.get("stale")),
            "fallback": True,
        }

    def _source_page(self, source, page_token=""):
        mode = "api" if self.api_key else "feed"
        cache_key = (source["id"], page_token, mode)
        now = self._clock()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self.cache_ttl_seconds:
                return copy.deepcopy(cached[1])
        try:
            payload = self._api_playlist_page(source, page_token) if self.api_key else self._xml_fallback_page(source)
        except YouTubePlaylistError:
            with self._lock:
                stale = self._cache.get(cache_key)
                if stale:
                    payload = copy.deepcopy(stale[1])
                    payload["stale"] = True
                    return payload
            if page_token:
                raise
            payload = self._xml_fallback_page(source)
        with self._lock:
            self._cache[cache_key] = (now, copy.deepcopy(payload))
        return payload

    @staticmethod
    def _decode_cursor(cursor):
        if not cursor:
            return {}
        try:
            padding = "=" * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii")).decode("utf-8")
            data = json.loads(raw)
            return {str(key): str(value) for key, value in data.items() if value}
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise YouTubePlaylistError("Invalid YouTube page cursor") from error

    @staticmethod
    def _encode_cursor(tokens):
        filtered = {key: value for key, value in tokens.items() if value}
        if not filtered:
            return ""
        raw = json.dumps(filtered, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def get_home_trailers(self, *, cursor="", source_filter="all"):
        if source_filter != "all" and source_filter not in self.sources:
            raise YouTubePlaylistError("Unknown YouTube trailer source")
        selected = self.sources.values() if source_filter == "all" else [self.sources[source_filter]]
        tokens = self._decode_cursor(cursor)
        groups = {}
        next_tokens = {}
        stale = False
        fallback = False
        for source in selected:
            if tokens.get(source["id"]) == "__done__":
                groups[source["id"]] = []
                next_tokens[source["id"]] = "__done__"
                continue
            page = self._source_page(source, tokens.get(source["id"], ""))
            groups[source["id"]] = page["items"]
            next_tokens[source["id"]] = page.get("next_page_token") or "__done__"
            stale = stale or bool(page.get("stale"))
            fallback = fallback or bool(page.get("fallback"))
        source_payload = [{key: value for key, value in source.items() if key != "playlist_id"} for source in selected]
        has_more = any(token != "__done__" for token in next_tokens.values())
        return {
            "title": "New Trailers",
            "sources": source_payload,
            "items": merge_balanced_trailers(groups),
            "next_cursor": self._encode_cursor(next_tokens) if has_more else "",
            "has_more": has_more,
            "stale": stale,
            "fallback": fallback,
        }

    def test_api_key(self, api_key=""):
        key = str(api_key or self.api_key or "").strip()
        if not key:
            raise YouTubePlaylistError("No YouTube API key is configured")
        source = next(iter(self.sources.values()))
        data = self._request_json("playlistItems", {
            "part": "id",
            "playlistId": source["playlist_id"],
            "maxResults": 1,
        }, api_key=key)
        return {"success": True, "items_checked": len(data.get("items", []) or [])}

    @staticmethod
    def _search_score(movie_title, year, video_title):
        normalized_movie = re.sub(r"[^a-z0-9]+", " ", str(movie_title or "").casefold()).strip()
        normalized_video = re.sub(r"[^a-z0-9]+", " ", str(video_title or "").casefold()).strip()
        if not normalized_movie or normalized_movie not in normalized_video:
            return 0
        score = 45
        if "trailer" in normalized_video:
            score += 25
        if "official" in normalized_video:
            score += 10
        if year and str(year) in normalized_video:
            score += 20
        return score

    def search_trailers(self, title, year=""):
        title = str(title or "").strip()
        year = str(year or "").strip()[:4]
        if not title:
            raise YouTubePlaylistError("Movie title is required")
        if not self.api_key:
            raise YouTubePlaylistError("Configure a YouTube API key in Settings to search for missing trailers")
        search_key = (title.casefold(), year)
        now = self._clock()
        with self._lock:
            cached = self._search_cache.get(search_key)
            if cached and now - cached[0] < self.cache_ttl_seconds:
                return copy.deepcopy(cached[1])
        data = self._request_json("search", {
            "part": "snippet",
            "q": " ".join(part for part in (title, year, "official trailer") if part),
            "type": "video",
            "videoEmbeddable": "true",
            "videoSyndicated": "true",
            "maxResults": 5,
        })
        candidates = []
        for raw in data.get("items", []) or []:
            video_id = str((raw.get("id") or {}).get("videoId") or "").strip()
            snippet = raw.get("snippet") or {}
            video_title = str(snippet.get("title") or "").strip()
            if not VIDEO_ID_PATTERN.fullmatch(video_id) or not video_title:
                continue
            candidates.append({
                "video_id": video_id,
                "title": video_title,
                "channel_title": str(snippet.get("channelTitle") or "").strip(),
                "published_at": str(snippet.get("publishedAt") or "").strip(),
                "thumbnail_url": str((snippet.get("thumbnails") or {}).get("high", {}).get("url") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "score": self._search_score(title, year, video_title),
            })
        candidates.sort(key=lambda item: (item["score"], item["published_at"]), reverse=True)
        confident = bool(candidates and candidates[0]["score"] >= 70 and (len(candidates) == 1 or candidates[0]["score"] - candidates[1]["score"] >= 15))
        result = {
            "status": "matched" if confident else "choose" if candidates else "unmatched",
            "movie": {"title": title, "year": year},
            "video": candidates[0] if confident else None,
            "candidates": candidates,
        }
        with self._lock:
            self._search_cache[search_key] = (now, copy.deepcopy(result))
        return result
