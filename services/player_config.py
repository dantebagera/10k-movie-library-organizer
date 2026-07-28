from copy import deepcopy
import re
import threading


PLAYER_CONFIG_VERSION = 1
PLAYER_MODES = {"built_in", "os_default"}
HARDWARE_DECODING_MODES = {"safe_auto", "off", "advanced"}
HDR_MODES = {"auto", "off", "passthrough"}
TONE_MAPPING_MODES = {"auto", "bt.2446a", "mobius", "reinhard", "hable"}
AUDIO_DOWNMIX_MODES = {"auto", "stereo", "5.1"}
SUBTITLE_STORAGE_MODES = {"cache", "beside_movie"}
SECRET_FIELDS = {
    "opensubtitles": {"username", "api_key", "password"},
    "subdl": {"api_key"},
}

DEFAULT_KEYBOARD_SHORTCUTS = {
    "play_pause": "Space",
    "seek_backward": "Left",
    "seek_forward": "Right",
    "seek_backward_long": "Shift+Left",
    "seek_forward_long": "Shift+Right",
    "volume_up": "Up",
    "volume_down": "Down",
    "mute": "M",
    "fullscreen": "F",
    "audio_tracks": "A",
    "subtitle_tracks": "S",
    "subtitle_search": "D",
    "speed_down": "[",
    "speed_up": "]",
    "subtitle_delay_down": "Z",
    "subtitle_delay_up": "X",
    "audio_delay_down": "Ctrl+Z",
    "audio_delay_up": "Ctrl+X",
    "chapters": "C",
    "statistics": "I",
    "screenshot": "P",
    "ab_repeat": "Ctrl+B",
    "frame_advance": ".",
    "aspect_ratio": "V",
    "crop": "Shift+V",
    "rotate": "Alt+R",
    "zoom_in": "Ctrl++",
    "zoom_out": "Ctrl+-",
    "pan_left": "Alt+Left",
    "pan_right": "Alt+Right",
    "pan_up": "Alt+Up",
    "pan_down": "Alt+Down",
    "always_on_top": "T",
}


def default_player_config():
    return {
        "version": PLAYER_CONFIG_VERSION,
        "mode": "os_default",
        "preferred_audio_languages": ["original", "en"],
        "preferred_subtitle_languages": ["en"],
        "prefer_forced_subtitles": False,
        "prefer_hearing_impaired_subtitles": False,
        "resume_enabled": True,
        "minimum_resume_seconds": 120,
        "completion_threshold": 0.92,
        "auto_mark_completed_watched": True,
        "hardware_decoding": "safe_auto",
        "hdr_handling": "auto",
        "tone_mapping": "auto",
        "audio_output": "auto",
        "audio_downmix": "auto",
        "audio_passthrough": [],
        "subtitle_style": {
            "font": "Segoe UI",
            "size": 46,
            "position": 100,
            "color": "#FFFFFFFF",
            "border_size": 2.0,
            "border_color": "#FF000000",
            "background_color": "#00000000",
        },
        "subtitle_storage": "cache",
        "auto_subtitle_search": False,
        "keyboard_shortcuts": deepcopy(DEFAULT_KEYBOARD_SHORTCUTS),
        "window_state": {
            "width": 1280,
            "height": 720,
            "x": 0,
            "y": 0,
            "screen": "",
            "maximized": False,
            "always_on_top": False,
            "positioned": False,
        },
        "providers": {
            "opensubtitles": {
                "enabled": False,
                "username": "",
                "api_key": "",
                "password": "",
            },
            "subdl": {
                "enabled": False,
                "api_key": "",
            },
        },
    }


class PlayerConfigError(ValueError):
    pass


def _coerce_language_list(value, field):
    if not isinstance(value, list):
        raise PlayerConfigError(f"{field} must be a list")
    result = []
    seen = set()
    for item in value:
        language = str(item or "").strip().lower()
        if not language:
            continue
        if len(language) > 32:
            raise PlayerConfigError(f"{field} contains an invalid language")
        if language not in seen:
            seen.add(language)
            result.append(language)
    return result


def _coerce_string_list(value, field, maximum=32):
    if not isinstance(value, list):
        raise PlayerConfigError(f"{field} must be a list")
    result = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > maximum:
            raise PlayerConfigError(f"{field} contains an invalid value")
        if text not in result:
            result.append(text)
    return result


def _coerce_bool(value, field):
    if not isinstance(value, bool):
        raise PlayerConfigError(f"{field} must be true or false")
    return value


def _coerce_number(value, field, minimum, maximum):
    if isinstance(value, bool):
        raise PlayerConfigError(f"{field} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise PlayerConfigError(f"{field} must be a number") from error
    if not minimum <= number <= maximum:
        raise PlayerConfigError(f"{field} must be between {minimum} and {maximum}")
    return number


class PlayerConfig:
    """Authoritative validation and redaction owner for native-player preferences."""

    def __init__(self, stored=None):
        self._lock = threading.RLock()
        self._config = default_player_config()
        if isinstance(stored, dict):
            try:
                self._apply(stored, initial_load=True)
            except PlayerConfigError:
                self._config = default_player_config()

    def storage_payload(self):
        with self._lock:
            return deepcopy(self._config)

    def public_payload(self):
        with self._lock:
            payload = deepcopy(self._config)
        for provider_name, secret_fields in SECRET_FIELDS.items():
            provider = payload["providers"][provider_name]
            for field in secret_fields:
                secret = provider.pop(field, "")
                provider[f"{field}_configured"] = bool(secret)
        return payload

    def reset(self):
        with self._lock:
            self._config = default_player_config()
            return self.public_payload()

    def update(self, changes):
        if not isinstance(changes, dict):
            raise PlayerConfigError("Player configuration must be an object")
        with self._lock:
            previous = deepcopy(self._config)
            try:
                self._apply(changes, initial_load=False)
            except PlayerConfigError:
                self._config = previous
                raise
            return self.public_payload()

    def _apply(self, changes, initial_load):
        config = self._config
        enum_fields = {
            "mode": PLAYER_MODES,
            "hardware_decoding": HARDWARE_DECODING_MODES,
            "hdr_handling": HDR_MODES,
            "tone_mapping": TONE_MAPPING_MODES,
            "audio_downmix": AUDIO_DOWNMIX_MODES,
            "subtitle_storage": SUBTITLE_STORAGE_MODES,
        }
        bool_fields = {
            "prefer_forced_subtitles",
            "prefer_hearing_impaired_subtitles",
            "resume_enabled",
            "auto_mark_completed_watched",
            "auto_subtitle_search",
        }

        for field, allowed in enum_fields.items():
            if field in changes:
                value = str(changes[field] or "").strip()
                if value not in allowed:
                    raise PlayerConfigError(f"{field} is not supported")
                config[field] = value
        for field in bool_fields:
            if field in changes:
                config[field] = _coerce_bool(changes[field], field)
        if "preferred_audio_languages" in changes:
            config["preferred_audio_languages"] = _coerce_language_list(
                changes["preferred_audio_languages"], "preferred_audio_languages"
            )
        if "preferred_subtitle_languages" in changes:
            config["preferred_subtitle_languages"] = _coerce_language_list(
                changes["preferred_subtitle_languages"], "preferred_subtitle_languages"
            )
        if "minimum_resume_seconds" in changes:
            config["minimum_resume_seconds"] = int(
                _coerce_number(changes["minimum_resume_seconds"], "minimum_resume_seconds", 0, 3600)
            )
        if "completion_threshold" in changes:
            config["completion_threshold"] = round(
                _coerce_number(changes["completion_threshold"], "completion_threshold", 0.5, 1.0),
                4,
            )
        if "audio_output" in changes:
            audio_output = str(changes["audio_output"] or "").strip()
            if not audio_output or len(audio_output) > 128:
                raise PlayerConfigError("audio_output is invalid")
            config["audio_output"] = audio_output
        if "audio_passthrough" in changes:
            config["audio_passthrough"] = _coerce_string_list(
                changes["audio_passthrough"], "audio_passthrough"
            )
        if "subtitle_style" in changes:
            style_changes = changes["subtitle_style"]
            if not isinstance(style_changes, dict):
                raise PlayerConfigError("subtitle_style must be an object")
            style = deepcopy(config["subtitle_style"])
            if "font" in style_changes:
                font = str(style_changes["font"] or "").strip()
                if not font or len(font) > 128 or any(value in font for value in "\r\n\x00"):
                    raise PlayerConfigError("subtitle_style font is invalid")
                style["font"] = font
            for field, minimum, maximum in (
                ("size", 12, 120),
                ("position", 0, 150),
                ("border_size", 0, 10),
            ):
                if field in style_changes:
                    style[field] = _coerce_number(
                        style_changes[field],
                        f"subtitle_style.{field}",
                        minimum,
                        maximum,
                    )
            for field in ("color", "border_color", "background_color"):
                if field in style_changes:
                    color = str(style_changes[field] or "").strip().upper()
                    if not re.fullmatch(r"#[0-9A-F]{8}", color):
                        raise PlayerConfigError(f"subtitle_style.{field} is invalid")
                    style[field] = color
            config["subtitle_style"] = style
        if "keyboard_shortcuts" in changes:
            shortcuts = changes["keyboard_shortcuts"]
            if not isinstance(shortcuts, dict):
                raise PlayerConfigError("keyboard_shortcuts must be an object")
            merged = deepcopy(config["keyboard_shortcuts"])
            for action, shortcut in shortcuts.items():
                if action not in DEFAULT_KEYBOARD_SHORTCUTS:
                    raise PlayerConfigError("keyboard_shortcuts contains an unknown action")
                normalized = str(shortcut or "").strip()
                if not normalized or len(normalized) > 64:
                    raise PlayerConfigError("keyboard_shortcuts contains an invalid shortcut")
                merged[action] = normalized
            config["keyboard_shortcuts"] = merged
        if "window_state" in changes:
            state_changes = changes["window_state"]
            if not isinstance(state_changes, dict):
                raise PlayerConfigError("window_state must be an object")
            state = deepcopy(config["window_state"])
            for field, minimum, maximum in (
                ("width", 640, 7680),
                ("height", 360, 4320),
                ("x", -32768, 32768),
                ("y", -32768, 32768),
            ):
                if field in state_changes:
                    state[field] = int(_coerce_number(
                        state_changes[field],
                        f"window_state.{field}",
                        minimum,
                        maximum,
                    ))
            if "screen" in state_changes:
                screen = str(state_changes["screen"] or "").strip()
                if len(screen) > 256 or any(value in screen for value in "\r\n\x00"):
                    raise PlayerConfigError("window_state.screen is invalid")
                state["screen"] = screen
            for field in ("maximized", "always_on_top", "positioned"):
                if field in state_changes:
                    state[field] = _coerce_bool(
                        state_changes[field], f"window_state.{field}"
                    )
            config["window_state"] = state
        if "providers" in changes:
            self._apply_providers(changes["providers"], initial_load)
        config["version"] = PLAYER_CONFIG_VERSION

    def _apply_providers(self, changes, initial_load):
        if not isinstance(changes, dict):
            raise PlayerConfigError("providers must be an object")
        for provider_name, provider_changes in changes.items():
            if provider_name not in SECRET_FIELDS:
                raise PlayerConfigError("providers contains an unknown provider")
            if not isinstance(provider_changes, dict):
                raise PlayerConfigError("provider configuration must be an object")
            provider = self._config["providers"][provider_name]
            if "enabled" in provider_changes:
                provider["enabled"] = _coerce_bool(
                    provider_changes["enabled"], f"{provider_name}.enabled"
                )
            for secret_field in SECRET_FIELDS[provider_name]:
                if secret_field not in provider_changes:
                    continue
                secret = str(provider_changes[secret_field] or "").strip()
                if len(secret) > 4096:
                    raise PlayerConfigError("Provider credential is invalid")
                if initial_load or secret:
                    provider[secret_field] = secret
            clear_fields = provider_changes.get("clear_secrets", [])
            if clear_fields:
                if not isinstance(clear_fields, list):
                    raise PlayerConfigError("clear_secrets must be a list")
                for secret_field in clear_fields:
                    if secret_field not in SECRET_FIELDS[provider_name]:
                        raise PlayerConfigError("clear_secrets contains an unknown credential")
                    provider[secret_field] = ""
