"""Static asset path classification for DSpace repositories.

Theme path heuristics (``/static/``, ``/handle/static/``, ``loadJQuery.js``,
etc.) target **DSpace 5.x** URL layouts such as those used by DUGi Fons
Especials and DUGi-Doc. DSpace 7.x–10.x use different theme and asset paths;
support for those versions is future work.
"""

from __future__ import annotations

from bitstream_paths import normalize_request_path, parse_bitstream_ref

STATIC_CATEGORIES = ("theme", "bitstream_image", "other")

# Path rules below are tuned for DSpace 5.x (not 7.x–10.x).
DSPACE_STATIC_PATH_VERSION = "5.x"

THEME_PREFIXES = (
    "/static/",
    "/assets/",
    "/themes/",
    "/dspace/",
    "/jquery/",
    "/handle/static/",
)

THEME_SUFFIXES = (
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".svg",
    ".ico",
)


def file_extension(path: str) -> str:
    filename = path.rsplit("/", 1)[-1]
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def classify_static_path(raw_path: str) -> tuple[str, str]:
    """
    Classify a static-asset request path.

    Theme detection uses DSpace 5.x conventions; see module docstring.

    Returns (normalized_path, category) where category is one of:
    theme, bitstream_image, other.
    """
    bitstream = parse_bitstream_ref(raw_path)
    if bitstream is not None:
        return bitstream.canonical_path, "bitstream_image"

    path = normalize_request_path(raw_path)
    lowered = path.lower()
    if lowered.startswith(THEME_PREFIXES) or "/bootstrap/" in lowered:
        return path, "theme"
    if lowered.endswith(THEME_SUFFIXES):
        return path, "theme"
    if "/bitstream/" in lowered:
        return path, "bitstream_image"
    return path, "other"


def category_label(category: str) -> str:
    labels = {
        "theme": "Theme — DSpace 5.x (/static/, assets)",
        "bitstream_image": "Bitstream images (covers, thumbnails)",
        "other": "Other static",
    }
    return labels.get(category, category)


def static_path_version_note() -> str:
    return (
        f"Theme path rules target DSpace {DSPACE_STATIC_PATH_VERSION}. "
        "DSpace 7.x–10.x asset paths are not classified yet."
    )
