"""Self-analysis orchestration for adult users (account connect → verify → analyze).

Each step is honest about what could and could not be retrieved:

* ``GET status``       — based on DB state only.
* ``verify``           — performs real public checks (RSS feed exists, Bluesky
                         login, Mastodon lookup, YouTube channel resolve).
* ``analyze``          — fetches genuinely, scores with the ML predictor, and
                         only then writes a *completed* session. Zero retrieved
                         posts produce ``no_data``, never a fake score.

Credential secrets only ever flow server-side between the DB ciphertext and
the platform APIs inside these functions.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend.database import (
    get_social_account_credentials,
    get_social_accounts,
    set_social_account_analysis_status,
    set_social_account_verification,
)
from backend.services import insights
from backend.services.platform_registry import get_platform
from backend.services.predictor import InferenceUnavailableError, predict_batch
from backend.utils import calibrate_risk_score, clean_text, risk_label

logger = logging.getLogger(__name__)

ANALYSIS_WINDOW_DAYS = 90
YOUTUBE_MAX_RESULTS = 25


class SelfAnalysisError(Exception):
    pass


def _main():
    """Lazily import main so this module never triggers its top-level import
    order (main imports this service, so importing main eagerly would create a
    circular import)."""
    import backend.main as main_mod

    return main_mod


def _connected_accounts_for(user_id: str) -> dict[str, dict[str, Any]]:
    accounts: dict[str, dict[str, Any]] = {}
    for row in get_social_accounts(user_id):
        slug = str(row.get("platform") or "").strip().lower()
        if slug:
            accounts[slug] = row
    return accounts


def _creds(user_id: str, slug: str, account: dict[str, Any] | None = None) -> dict[str, Any]:
    """Credentials dict, backfilled from the account row for the public handle fields."""
    creds = dict(get_social_account_credentials(user_id, slug) or {})
    account = account or _connected_accounts_for(user_id).get(slug) or {}
    for key in ("handle", "channel", "profile_url"):
        if not creds.get(key) and account.get(key):
            creds[key] = account[key]
    return creds


async def _score_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not posts:
        return []
    texts = [clean_text(p["text"] or "") for p in posts]
    try:
        scores = await predict_batch(texts)
    except InferenceUnavailableError as exc:
        raise SelfAnalysisError(f"The risk model is not available right now: {exc}") from exc
    for i, post in enumerate(posts):
        post.update(calibrate_risk_score(post.get("text") or "", float(scores[i])))
    return posts


def _posts_blob(posts: list[dict[str, Any]], platform: str, limit: int = 60) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in (posts or [])[:limit]:
        score = float(p.get("risk_score") or 0.0)
        out.append(
            {
                "platform": platform,
                "text": (p.get("text") or "")[:700],
                "risk_score": score,
                "level": risk_label(score)[2],
                "date": p.get("date"),
                "url": p.get("url"),
            }
        )
    return out


# ── Per-platform fetchers ─────────────────────────────────────────────

async def _analyze_reddit(user_id: str) -> dict[str, Any]:
    creds = _creds(user_id, "reddit")
    handle = (creds.get("handle") or "").strip().lstrip("u/")
    if not handle:
        return {"platform": "reddit", "status": "error", "message": "No username stored for this Reddit account."}
    try:
        posts = _main()._fetch_reddit_rss_posts(handle)
        posts = [p for p in posts if _within_window(p.get("date"))]
        if not posts:
            return {"platform": "reddit", "status": "no_data", "message": f"No public posts found for u/{handle} in the last 90 days."}
        scored = await _score_posts(posts)
        return {"platform": "reddit", "status": "ok", "message": "OK", "posts": _posts_blob(scored, "reddit")}
    except Exception as exc:  # noqa: BLE001
        return {"platform": "reddit", "status": "error", "message": f"Could not retrieve Reddit activity: {exc}"}


async def _analyze_bluesky(user_id: str) -> dict[str, Any]:
    creds = _creds(user_id, "bluesky")
    handle = (creds.get("handle") or "").strip()
    app_password = (creds.get("app_password") or "").strip()
    if not handle or not app_password:
        return {"platform": "bluesky", "status": "error", "message": "Bluesky handle and app password are required."}
    try:
        token = _main()._login_bluesky(handle, app_password)
        posts = _main()._fetch_bluesky_posts(handle, token)
        posts = [p for p in posts if _within_window(p.get("date"))]
        if not posts:
            return {"platform": "bluesky", "status": "no_data", "message": f"No recent posts found for {handle} in the last 90 days."}
        scored = await _score_posts(posts)
        return {"platform": "bluesky", "status": "ok", "message": "OK", "posts": _posts_blob(scored, "bluesky")}
    except Exception as exc:  # noqa: BLE001
        return {"platform": "bluesky", "status": "error", "message": f"Could not retrieve Bluesky activity: {exc}"}


async def _analyze_mastodon(user_id: str) -> dict[str, Any]:
    creds = _creds(user_id, "mastodon")
    handle = (creds.get("handle") or "").strip().lstrip("@")
    if not handle or "@" not in handle:
        return {"platform": "mastodon", "status": "error", "message": "Mastodon handle must look like username@instance.social."}
    username, _, instance = handle.partition("@")
    if not username or not instance:
        return {"platform": "mastodon", "status": "error", "message": "Mastodon handle must look like username@instance.social."}
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=ANALYSIS_WINDOW_DAYS)
        raw_posts: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"https://{instance}/api/v1/accounts/lookup", params={"acct": username})
            if r.status_code == 404:
                return {"platform": "mastodon", "status": "error", "message": f"Could not find Mastodon account {username}@{instance}."}
            r.raise_for_status()
            acct = r.json()
            max_id: str | None = None
            for _ in range(8):
                params: dict[str, Any] = {"limit": 40, "exclude_replies": False}
                if max_id:
                    params["max_id"] = max_id
                r = await client.get(f"https://{instance}/api/v1/accounts/{acct['id']}/statuses", params=params)
                if r.status_code in {401, 403, 404}:
                    return {
                        "platform": "mastodon",
                        "status": "error",
                        "message": "Could not fetch Mastodon posts. The account may be private or restricted.",
                    }
                r.raise_for_status()
                statuses = r.json()
                if not statuses:
                    break
                for s in statuses:
                    try:
                        created = datetime.fromisoformat(str(s.get("created_at", "")).replace("Z", "+00:00"))
                    except ValueError:
                        created = datetime.now(timezone.utc)
                    if created < cutoff:
                        break
                    text = re.sub(r"<[^>]+>", "", s.get("content", "") or "").strip()
                    if len(text) <= 5:
                        continue
                    raw_posts.append({"text": text, "date": s.get("created_at", ""), "url": s.get("url", "")})
                max_id = statuses[-1]["id"]
        if not raw_posts:
            return {"platform": "mastodon", "status": "no_data", "message": f"No public posts found for {username}@{instance} in the last 90 days."}
        scored = await _score_posts(raw_posts)
        return {"platform": "mastodon", "status": "ok", "message": "OK", "posts": _posts_blob(scored, "mastodon")}
    except SelfAnalysisError:
        raise
    except Exception as exc:  # noqa: BLE001
        return {"platform": "mastodon", "status": "error", "message": f"Could not retrieve Mastodon activity: {exc}"}


def _youtube_api_key() -> str:
    from backend.secrets_manager import get_secret

    key = get_secret("YOUTUBE_API_KEY") or ""
    if not key:
        raise SelfAnalysisError("YouTube analysis needs a server-configured YOUTUBE_API_KEY.")
    return key


async def _analyze_youtube(user_id: str) -> dict[str, Any]:
    creds = _creds(user_id, "youtube")
    channel_input = (creds.get("channel") or creds.get("handle") or "").strip()
    if not channel_input:
        return {"platform": "youtube", "status": "error", "message": "A YouTube channel URL, handle, or ID is required."}
    try:
        api_key = _youtube_api_key()
        channel_id = channel_input
        if "youtube.com/channel/" in channel_input:
            channel_id = channel_input.split("youtube.com/channel/")[-1].split("/")[0].split("?")[0]
        else:
            handle_match = re.search(r"youtube\.com/@([^/]+)", channel_input)
            if handle_match:
                base = "https://www.googleapis.com/youtube/v3/channels"
                params = {"part": "snippet", "forHandle": handle_match.group(1), "key": api_key}
            elif re.fullmatch(r"UC[0-9A-Za-z_-]{22}", channel_input or ""):
                base = "https://www.googleapis.com/youtube/v3/channels"
                params = {"part": "snippet", "id": channel_input, "key": api_key}
            else:
                base = "https://www.googleapis.com/youtube/v3/search"
                params = {"part": "snippet", "q": channel_input, "type": "channel", "maxResults": 1, "key": api_key}
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(base, params=params)
                r.raise_for_status()
                items = r.json().get("items") or []
                if not items:
                    return {"platform": "youtube", "status": "error", "message": "Could not resolve that YouTube channel."}
                channel_id = items[0]["id"]

        posts: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            search_resp = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "channelId": channel_id,
                    "maxResults": YOUTUBE_MAX_RESULTS,
                    "order": "date",
                    "type": "video",
                    "key": api_key,
                },
            )
            search_resp.raise_for_status()
            for it in search_resp.json().get("items") or []:
                pub = it["snippet"].get("publishedAt", "")
                try:
                    created = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
                except ValueError:
                    created = datetime.now(timezone.utc)
                if created < datetime.now(timezone.utc) - timedelta(days=ANALYSIS_WINDOW_DAYS):
                    continue
                vid = it["id"]["videoId"]
                posts.append(
                    {
                        "text": (it["snippet"].get("title") or "").strip(),
                        "date": pub,
                        "url": f"https://youtube.com/watch?v={vid}",
                        "video_id": vid,
                    }
                )

        if not posts:
            return {"platform": "youtube", "status": "no_data", "message": "No recent public videos found for that channel in the last 90 days."}
        scored = await _score_posts(posts)
        return {"platform": "youtube", "status": "ok", "message": "OK", "posts": _posts_blob(scored, "youtube")}
    except SelfAnalysisError as exc:
        return {"platform": "youtube", "status": "error", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"platform": "youtube", "status": "error", "message": f"Could not retrieve YouTube activity: {exc}"}


def make_not_retrievable(platform: str):
    async def _analyzer(user_id: str) -> dict[str, Any]:
        spec = get_platform(platform)
        name = (spec or {}).get("display_name") or platform.title()
        return {
            "platform": platform,
            "status": "error",
            "message": f"{name} cannot be analyzed from the self-service account connection yet — the platform requires manual export or an institutional subscription.",
        }
    return _analyzer


_ANALYZERS = {
    "reddit": _analyze_reddit,
    "bluesky": _analyze_bluesky,
    "mastodon": _analyze_mastodon,
    "youtube": _analyze_youtube,
    "instagram": make_not_retrievable("instagram"),
    "linkedin": make_not_retrievable("linkedin"),
    "tiktok": make_not_retrievable("tiktok"),
    "facebook": make_not_retrievable("facebook"),
    "twitter": make_not_retrievable("twitter"),
}


def _within_window(date_str: str | None) -> bool:
    if not date_str:
        return True
    try:
        created = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created >= datetime.now(timezone.utc) - timedelta(days=ANALYSIS_WINDOW_DAYS)


async def run_self_analysis(user_id: str, platform_slugs: list[str]) -> dict[str, Any]:
    """Analyze the requested (already-connected) platforms and record a session.

    Returns the created session row. Callers must write the audit event.
    """
    accounts = _connected_accounts_for(user_id)
    requested = list(dict.fromkeys(platform_slugs)) if platform_slugs and accounts else list(accounts.keys())
    missing = [slug for slug in requested if slug not in accounts]
    if missing:
        raise SelfAnalysisError(
            f"These platforms are not connected to your account: {', '.join(sorted(missing))}."
        )

    platform_results: dict[str, dict[str, Any]] = {}
    progress: dict[str, Any] = {"requested": requested, "platforms": {}}
    for slug in requested:
        analyzer = _ANALYZERS.get(slug)
        if analyzer is None:
            progress["platforms"][slug] = {"status": "error", "message": "Unsupported platform."}
            continue
        result = await analyzer(user_id)
        platform_results[slug] = result
        progress["platforms"][slug] = {"status": result.get("status"), "message": result.get("message", "")}
        if result.get("status") == "ok":
            set_social_account_analysis_status(user_id, slug, "completed")
        elif result.get("status") == "error":
            set_social_account_analysis_status(user_id, slug, "error")

    return _finalize_session(user_id, platform_results, progress, analysis_type="self")


def _finalize_session(
    user_id: str,
    platform_results: dict[str, dict[str, Any]],
    progress: dict[str, Any],
    analysis_type: str,
) -> dict[str, Any]:
    from backend.database import (
        create_analysis_session,
        set_analysis_session_completed,
        update_analysis_session_progress,
    )

    session = create_analysis_session(
        student_id=user_id,
        counsellor_id=None,
        institution_id=None,
        consent_id=None,
        analysis_type=analysis_type,
        platforms=sorted(platform_results.keys()),
        status="running",
        progress_json=progress,
    )
    sid = session["id"]

    ok_results = {
        slug: result
        for slug, result in platform_results.items()
        if result.get("status") == "ok" and (result.get("posts") or [])
    }
    any_had_data = bool(ok_results)
    findings = insights.build_findings({
        slug: {"posts": result.get("posts") or []} for slug, result in ok_results.items()
    })

    connected = sorted(_connected_accounts_for(user_id).keys())
    insight_text = insights.build_insights(findings, {slug: {"posts": r.get("posts") or []} for slug, r in ok_results.items()})
    rec_text = insights.build_recommendations(
        findings,
        {slug: {"posts": r.get("posts") or []} for slug, r in ok_results.items()},
        connected_platforms=connected,
    )
    summary = insights.build_summary_text(findings)

    has_platform_failures = any(
        result.get("status") != "ok" for result in platform_results.values()
    )

    if any_had_data:
        terminal_status = "partial" if has_platform_failures else "completed"
        set_analysis_session_completed(
            sid,
            findings=findings,
            risk_score=float(findings["overall_risk"] or 0.0),
            insights=json.dumps(insight_text, ensure_ascii=False),
            recommendations=json.dumps(rec_text, ensure_ascii=False),
            status=terminal_status,
        )
        update_analysis_session_progress(sid, terminal_status, progress=progress)
    else:
        terminal_status = "failed" if any(
            result.get("status") == "error" for result in platform_results.values()
        ) else "no_data"
        update_analysis_session_progress(
            sid,
            terminal_status,
            progress=progress,
            error={"summary": summary, "platforms": progress.get("platforms")},
        )
        from backend.database import set_analysis_session_content

        set_analysis_session_content(
            sid,
            findings=findings,
            insights=json.dumps(insight_text, ensure_ascii=False),
            recommendations=json.dumps(rec_text, ensure_ascii=False),
        )

    row = _read_session(sid)
    return row


def _read_session(sid: str) -> dict[str, Any]:
    from backend.database import get_analysis_session

    return get_analysis_session(sid)


# ── Verification ──────────────────────────────────────────────────────

async def verify_platform_connection(user_id: str, slug: str) -> dict[str, Any]:
    """Run the real public verification check for a connected platform."""
    account = _connected_accounts_for(user_id).get(slug)
    if not account:
        return {"platform": slug, "verified": False, "message": "Account is not connected."}

    creds = _creds(user_id, slug, account)
    verified_handle: str | None = None
    verified_url: str | None = None

    if slug == "reddit":
        handle = (creds.get("handle") or "").strip().lstrip("u/")
        if not handle:
            return {"platform": slug, "verified": False, "message": "No username stored."}
        try:
            posts = _main()._fetch_reddit_rss_posts(handle)
            if posts:
                verified_handle = handle
                verified_url = f"https://reddit.com/user/{handle}"
            else:
                return {"platform": slug, "verified": False, "message": f"No public activity found for u/{handle}."}
        except Exception as exc:  # noqa: BLE001
            return {"platform": slug, "verified": False, "message": f"Could not confirm u/{handle}: {exc}"}

    elif slug == "bluesky":
        handle = (creds.get("handle") or "").strip()
        password = (creds.get("app_password") or "").strip()
        if not handle or not password:
            return {"platform": slug, "verified": False, "message": "Handle and app password are required."}
        try:
            _main()._login_bluesky(handle, password)
            verified_handle = handle
            verified_url = f"https://bsky.app/profile/{handle}"
        except Exception as exc:  # noqa: BLE001
            return {"platform": slug, "verified": False, "message": f"Login failed: {exc}"}

    elif slug == "mastodon":
        handle = (creds.get("handle") or "").strip().lstrip("@")
        if not handle or "@" not in handle:
            return {"platform": slug, "verified": False, "message": "Handle must look like username@instance.social."}
        username, _, instance = handle.partition("@")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(f"https://{instance}/api/v1/accounts/lookup", params={"acct": username})
            if r.status_code == 404:
                return {"platform": slug, "verified": False, "message": f"No public account found for {username}@{instance}."}
            r.raise_for_status()
            verified_handle = handle
            verified_url = f"https://{instance}/@{username}"
        except Exception as exc:  # noqa: BLE001
            return {"platform": slug, "verified": False, "message": f"Could not reach {instance}: {exc}"}

    elif slug == "youtube":
        channel_input = (creds.get("channel") or creds.get("handle") or "").strip()
        if not channel_input:
            return {"platform": slug, "verified": False, "message": "A channel URL, handle, or ID is required."}
        try:
            api_key = _youtube_api_key()
            if "youtube.com/channel/" in channel_input:
                cid = channel_input.split("youtube.com/channel/")[-1].split("/")[0].split("?")[0]
                params = {"part": "snippet", "id": cid, "key": api_key}
            else:
                handle_match = re.search(r"youtube\.com/@([^/]+)", channel_input)
                if handle_match:
                    params = {"part": "snippet", "forHandle": handle_match.group(1), "key": api_key}
                else:
                    return {"platform": slug, "verified": False, "message": "Enter a channel URL or @handle so we can verify it."}
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get("https://www.googleapis.com/youtube/v3/channels", params=params)
                r.raise_for_status()
                items = r.json().get("items") or []
            if not items:
                return {"platform": slug, "verified": False, "message": "No such public YouTube channel was found."}
            verified_handle = items[0]["snippet"].get("title") or channel_input
            verified_url = f"https://www.youtube.com/channel/{items[0]['id']}"
        except Exception as exc:  # noqa: BLE001
            return {"platform": slug, "verified": False, "message": f"Could not verify YouTube channel: {exc}"}

    else:
        return {
            "platform": slug,
            "verified": False,
            "message": "This platform cannot be verified automatically in the self-service flow.",
        }

    status = "verified" if verified_handle else "pending"
    set_social_account_verification(
        user_id,
        slug,
        verification_status=status,
        verified_handle=verified_handle,
        verified_profile_url=verified_url,
    )
    return {
        "platform": slug,
        "verified": status == "verified",
        "verification_status": status,
        "verified_handle": verified_handle,
        "verified_profile_url": verified_url,
        "message": "Verified" if verified_handle else "Not verified",
    }


# Drop unused helper to keep module surface minimal.
__all__ = ["run_self_analysis", "verify_platform_connection", "SelfAnalysisError"]
