import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "design" / "player-theme.json"
CSS_OUTPUT = PROJECT_ROOT / "src" / "styles" / "playerTheme.css"
QML_OUTPUT = PROJECT_ROOT / "native" / "player" / "qml" / "PlayerTheme.qml"


def load_theme(path=SOURCE):
    theme = json.loads(Path(path).read_text(encoding="utf-8"))
    if theme.get("schema") != "cinema-paradiso-player-theme-v1":
        raise ValueError("Player theme schema is invalid")
    return theme


def css_name(name):
    result = []
    for character in name:
        if character.isupper():
            result.extend(("-", character.lower()))
        else:
            result.append(character)
    return "".join(result)


def render_css(theme):
    lines = [
        "/* Generated from design/player-theme.json. Do not edit by hand. */",
        ":root {",
    ]
    for name, value in theme["colors"].items():
        lines.append(f"  --{css_name(name)}: {value};")
    for name, value in theme.get("opacity", {}).items():
        lines.append(f"  --{css_name(name)}-opacity: {float(value):g};")
    for name, value in theme["radii"].items():
        lines.append(f"  --radius-{css_name(name)}: {value}px;")
    for name, value in theme["shadows"].items():
        lines.append(f"  --shadow-{css_name(name)}: {value};")
    lines.extend(("}", ""))
    return "\n".join(lines)


def render_qml(theme):
    lines = [
        "// Generated from design/player-theme.json. Do not edit by hand.",
        "pragma Singleton",
        "import QtQuick",
        "",
        "QtObject {",
    ]
    for name, value in theme["colors"].items():
        lines.append(f'    readonly property color {name}: "{value}"')
    for name, value in theme.get("opacity", {}).items():
        lines.append(
            f"    readonly property real {name}Opacity: {float(value):g}"
        )
    for name, value in theme["radii"].items():
        lines.append(f"    readonly property int radius{name[0].upper() + name[1:]}: {value}")
    lines.append(
        f'    readonly property int controlsHideMs: {int(theme["timing"]["controlsHideMs"])}'
    )
    lines.extend(("}", ""))
    return "\n".join(lines)


def expected_outputs():
    theme = load_theme()
    return {
        CSS_OUTPUT: render_css(theme),
        QML_OUTPUT: render_qml(theme),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate shared CP player theme outputs.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mismatches = []
    for path, expected in expected_outputs().items():
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if current != expected:
            mismatches.append(path)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8")
    if args.check and mismatches:
        raise SystemExit(
            "Generated player theme is stale: "
            + ", ".join(str(path.relative_to(PROJECT_ROOT)) for path in mismatches)
        )


if __name__ == "__main__":
    main()
