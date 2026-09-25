"""Canonical platform metadata for the adult self-analysis experience.

Single source of truth describing every platform a user can connect. Drives:

- the guided "Add account" UI (format / example / credentials / why / where)
- backend normalization & validation on ``POST /api/self/social-accounts``
- per-platform capability truth so the UI never claims data exists that the
  backend cannot actually retrieve.

If a platform cannot feed the analysis pipeline, ``analyzable`` is False and
the status helpers surface that honestly instead of faking a result.
"""

from __future__ import annotations

from typing import Any, Literal

PlatformKey = Literal[
    "reddit", "bluesky", "mastodon", "youtube",
    "instagram", "twitter", "facebook", "linkedin", "tiktok",
]

# Canonical lowercase slug -> display-name aliases users may submit.
PLATFORM_ALIASES: dict[str, str] = {
    "reddit": "reddit",
    "bluesky": "bluesky",
    "bsky": "bluesky",
    "mastodon": "mastodon",
    "youtube": "youtube",
    "instagram": "instagram",
    "ig": "instagram",
    "twitter": "twitter",
    "x": "twitter",
    "facebook": "facebook",
    "fb": "facebook",
    "linkedin": "linkedin",
    "tiktok": "tiktok",
}


def normalize_platform(value: str) -> str | None:
    """Return the canonical lowercase slug for a platform name/alias, else None."""
    if not value:
        return None
    return PLATFORM_ALIASES.get(value.strip().lower())


PLATFORM_SPECS: dict[PlatformKey, dict[str, Any]] = {
    "reddit": {
        "display_name": "Reddit",
        "icon": "ti ti-brand-reddit",
        "blurb": "Reddit account recording is available, but content analysis is paused pending Reddit approval.",
        "required_input": "username",
        "handle_label": "Reddit username",
        "handle_format": "Your Reddit username without 'u/' — e.g. \"sneaky_snack\". A profile URL such as https://www.reddit.com/user/sneaky_snack is also accepted.",
        "handle_example": "sneaky_snack",
        "accepts_url": True,
        "credentials": {
            "required": False,
            "label": "No credentials",
            "why": "Reddit publishes public RSS feeds for every user; no login or API key is needed.",
        },
        "requires_public": "Yes — only publicly visible posts and comments can be read.",
        "privacy_note": "No Reddit content is fetched or analysed while this platform is restricted.",
        "capabilities": "Account recording and future eligibility review only.",
        "limitations": "Content analysis is disabled pending written approval for MindGuard's commercial wellbeing use case.",
        "analyzable": False,
        "data_source": "restricted",
        "server_config_required": True,
        "server_config_note": "Reddit content analysis is disabled until Reddit grants written approval.",
        "analyze_step_label": "Reddit analysis is currently unavailable.",
    },
    "bluesky": {
        "display_name": "Bluesky",
        "icon": "ti ti-brand-bluesky",
        "blurb": "Public posts from any Bluesky handle over the last 3 months, retrieved through an authenticated session.",
        "required_input": "handle",
        "handle_label": "Bluesky handle",
        "handle_format": "Your handle, e.g. \"your.handle.bsky.social\". If you type just \"yourhandle\", we append \".bsky.social\" for you.",
        "handle_example": "your.handle.bsky.social",
        "accepts_url": True,
        "credentials": {
            "required": True,
            "type": "app_password",
            "label": "Bluesky App Password",
            "why": "Bluesky requires an authenticated session to read an author feed. An App Password is a limited token — never use your main password.",
            "where": "Bluesky app → Settings → Privacy & security → App passwords → \"Add App Password\".",
            "hint": "Create an app password named \"mindguard\" (App password format: xxxx-xxxx-xxxx-xxxx).",
            "secret_fields": ["app_password"],
            "steps": [
                "Open the Bluesky app or bsky.app.",
                "Go to Settings → Privacy & security.",
                "Open \"App passwords\".",
                "Tap \"Add App Password\", name it mindguard, and create it.",
                "Paste the generated App Password here.",
            ],
        },
        "requires_public": "Only content you can already see publicly is retrieved.",
        "privacy_note": "Your App Password is encrypted at rest, never shown again after saving, and never logged. We use it only to open a read-only session.",
        "capabilities": "Up to ~3 months of posts from a public handle.",
        "limitations": "Posts with <6 characters and posts that are not publicly reachable are skipped.",
        "analyzable": True,
        "data_source": "atproto",
        "server_config_required": False,
        "server_config_note": "",
        "analyze_step_label": "Connecting to Bluesky and fetching posts…",
    },
    "mastodon": {
        "display_name": "Mastodon",
        "icon": "ti ti-brand-mastodon",
        "blurb": "Public toots from a Mastodon account (last ~3 months) via the account's instance API.",
        "required_input": "handle",
        "handle_label": "Mastodon handle",
        "handle_format": "Use the full federated form @username@instance.social, or paste a profile URL like https://instance.social/@username.",
        "handle_example": "@ned@beige.party",
        "accepts_url": True,
        "credentials": {
            "required": False,
            "label": "No credentials",
            "why": "For public accounts, the instance API exposes toots without login.",
        },
        "requires_public": "Yes — private or followers-only accounts can't be read without authenticating as the account owner.",
        "privacy_note": "We only read toots that are already public on the instance; nothing is posted.",
        "capabilities": "Public statuses from the account (last ~3 months).",
        "limitations": "Private, followers-only, and blocked-silence posts are unavailable. Some instances rate-limit anonymous access.",
        "analyzable": True,
        "data_source": "mastodon_api",
        "server_config_required": False,
        "server_config_note": "",
        "analyze_step_label": "Looking up the Mastodon account and fetching toots…",
    },
    "youtube": {
        "display_name": "YouTube",
        "icon": "ti ti-brand-youtube",
        "blurb": "Channel content — recent video titles, descriptions and comments (last ~3 months) — retrieved through the YouTube Data API.",
        "required_input": "url_or_handle",
        "handle_label": "YouTube channel handle or URL",
        "handle_format": "A channel handle like @mindguard, or a channel URL (https://www.youtube.com/@mindguard or https://www.youtube.com/channel/UC...).",
        "handle_example": "https://www.youtube.com/@mindguard",
        "accepts_url": True,
        "credentials": {
            "required": True,
            "type": "server_key",
            "label": "MindGuard's YouTube API key",
            "why": "YouTube analysis uses MindGuard's own YouTube Data API key — you don't need to paste your own. We show status below based on server-side configuration.",
            "where": "No user action required. YouTube is configured at the application level.",
            "hint": "",
            "secret_fields": [],
        },
        "requires_public": "Only publicly listed videos and comments.",
        "privacy_note": "Content is fetched with the platform API in server-side mode (YOUTUBE_API_KEY env). No personal credentials are stored.",
        "capabilities": "Recent video titles, descriptions and top comments from a channel.",
        "limitations": "If the server's YouTube API key is not configured, channel analysis isn't available. Direct video transcripts are a separate counsellor tool.",
        "analyzable": True,
        "data_source": "youtube_data_api",
        "server_config_required": True,
        "server_config_note": "Requires YOUTUBE_API_KEY set on the server. If missing, accounts show as \"server configuration required\" and are skipped by \"Analyze all\".",
        "analyze_step_label": "Fetching recent YouTube channel content…",
    },
    "instagram": {
        "display_name": "Instagram",
        "icon": "ti ti-brand-instagram",
        "blurb": "Instagram profiles cannot currently be content-analysed by MindGuard in the self flow.",
        "required_input": "handle_or_url",
        "handle_label": "Instagram handle or profile URL",
        "handle_format": "A handle like \"@yourname\" or a profile URL (https://www.instagram.com/yourname/).",
        "handle_example": "@yourname",
        "accepts_url": True,
        "credentials": {
            "required": False,
            "label": "No credentials",
            "why": "Instagram's graph media endpoints aren't available in this deployment, so no credential would change the outcome.",
        },
        "requires_public": "n/a",
        "privacy_note": "Nothing is fetched or stored except the handle you enter.",
        "capabilities": "Handle recording only — no post retrieval is currently implemented for the self flow.",
        "limitations": "Instagram data retrieval is not available. The account can be connected but it will be reported as \"no data\" rather than analysed.",
        "analyzable": False,
        "data_source": "unsupported",
        "server_config_required": True,
        "server_config_note": "Requires a server-side Instagram access token that is not configured. Until then the platform is unsupported.",
        "analyze_step_label": "",
    },
    "twitter": {
        "display_name": "X (Twitter)",
        "icon": "ti ti-brand-x",
        "blurb": "Public posts from an X/Twitter account.",
        "required_input": "url_or_handle",
        "handle_label": "X handle or profile URL",
        "handle_format": "A handle like \"@yourname\" or a profile URL (https://x.com/yourname).",
        "handle_example": "https://x.com/yourname",
        "accepts_url": True,
        "credentials": {
            "required": True,
            "type": "server_key",
            "label": "Server-side X API access",
            "why": "X removed anonymous public JSON. Reading a user timeline requires a server-side bearer token or Composio.\n\nOpen Playwright scraping is unreliable and frequently blocked by X's login wall.",
            "where": "No user action required. Server service account (TWITTER_BEARER_TOKEN / COMPOSIO_API_KEY).",
            "hint": "",
            "secret_fields": [],
        },
        "requires_public": "Yes — public timeline only.",
        "privacy_note": "Content is fetched server-side. No personal credentials are collected.",
        "capabilities": "Recent public tweets if the server X credential is configured.",
        "limitations": "Often unavailable: X requires authenticated API access. If the server credential is missing, analysis is reported as unavailable rather than faked.",
        "analyzable": True,
        "data_source": "twitter_api",
        "server_config_required": True,
        "server_config_note": "Requires TWITTER_BEARER_TOKEN or COMPOSIO_API_KEY on the server. Until then X shows as unavailable.",
        "analyze_step_label": "Fetching recent posts from X…",
    },
    "facebook": {
        "display_name": "Facebook",
        "icon": "ti ti-brand-facebook",
        "blurb": "Public posts from a Facebook profile.",
        "required_input": "url",
        "handle_label": "Facebook profile URL",
        "handle_format": "The public profile URL, e.g. https://www.facebook.com/yourname",
        "handle_example": "https://www.facebook.com/yourname",
        "accepts_url": True,
        "credentials": {
            "required": False,
            "label": "No credentials",
            "why": "Public pages are scraped in a headless browser where possible; no user login is collected.",
        },
        "requires_public": "Yes — the profile and its posts must be publicly visible.",
        "privacy_note": "A public page is opened in a headless browser by the server. Only publicly visible post text is kept.",
        "capabilities": "Recently visible public post text when the profile allows anonymous viewing.",
        "limitations": "Facebook frequently blocks automated access with a login wall. When that happens the platform reports a retrieval failure instead of a fake success.",
        "analyzable": True,
        "data_source": "playwright",
        "server_config_required": False,
        "server_config_note": "",
        "analyze_step_label": "Opening the public profile and collecting posts…",
    },
    "linkedin": {
        "display_name": "LinkedIn",
        "icon": "ti ti-brand-linkedin",
        "blurb": "LinkedIn profiles are not supported for analysis.",
        "required_input": "url",
        "handle_label": "LinkedIn profile URL",
        "handle_format": "A public profile URL (https://www.linkedin.com/in/name/).",
        "handle_example": "https://www.linkedin.com/in/name",
        "accepts_url": True,
        "credentials": {"required": False, "label": "No credentials"},
        "requires_public": "n/a",
        "privacy_note": "Nothing is fetched; only the URL you provide is stored.",
        "capabilities": "None — LinkedIn has no supported ingestion path in the self flow.",
        "limitations": "Not supported. Connect the account if you like, but it will be reported as not supported and never show a fake analysis.",
        "analyzable": False,
        "data_source": "unsupported",
        "server_config_required": False,
        "server_config_note": "",
        "analyze_step_label": "",
    },
    "tiktok": {
        "display_name": "TikTok",
        "icon": "ti ti-brand-tiktok",
        "blurb": "TikTok profiles are not supported for analysis.",
        "required_input": "handle_or_url",
        "handle_label": "TikTok handle or profile URL",
        "handle_format": "A handle like \"@yourname\" or a profile URL (https://www.tiktok.com/@yourname).",
        "handle_example": "@yourname",
        "accepts_url": True,
        "credentials": {"required": False, "label": "No credentials"},
        "requires_public": "n/a",
        "privacy_note": "Nothing is fetched; only the handle you provide is stored.",
        "capabilities": "None — TikTok has no supported ingestion path in the self flow.",
        "limitations": "Not supported. The account will be reported as not supported and never show a fake analysis.",
        "analyzable": False,
        "data_source": "unsupported",
        "server_config_required": False,
        "server_config_note": "",
        "analyze_step_label": "",
    },
}

# Keys in a stable order for the UI.
SUPPORTED_PLATFORM_ORDER: list[str] = [
    "reddit", "bluesky", "mastodon", "youtube",
    "instagram", "twitter", "facebook", "linkedin", "tiktok",
]


def get_platform(key: str | None) -> dict[str, Any] | None:
    slug = normalize_platform(key or "")
    if not slug or slug not in PLATFORM_SPECS:
        return None
    spec = dict(PLATFORM_SPECS[slug])
    spec["key"] = slug
    return spec


def all_platforms() -> list[dict[str, Any]]:
    platforms: list[dict[str, Any]] = []
    for key in SUPPORTED_PLATFORM_ORDER:
        spec = get_platform(key)
        if spec is not None:
            platforms.append(spec)
    return platforms


def is_supported(key: str) -> bool:
    return normalize_platform(key) in PLATFORM_SPECS
