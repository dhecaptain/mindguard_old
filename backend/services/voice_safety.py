"""Ephemeral, server-side voice transcript triage (not clinical risk scoring)."""

import re

import httpx

NORMAL = "normal"
DISTRESS = "distress"
HEIGHTENED_CONCERN = "heightened_concern"
POTENTIAL_IMMEDIATE_DANGER = "potential_immediate_danger"

_DISTRESS = re.compile(
    r"\b(overwhelmed|panicking|panic attack|hopeless|can't cope|cannot cope|"
    r"can't go on|cannot go on|feel unsafe|feeling unsafe|sad|anxious|stressed|"
    r"lonely|exhausted|scared|afraid)\b",
    re.IGNORECASE,
)
_SELF_HARM_CONTEXT = re.compile(
    r"\b(suicid\w*|end my life|kill myself|hurt myself|harm myself|self[- ]harm)\b",
    re.IGNORECASE,
)
_FIRST_PERSON = re.compile(r"\b(i|i'm|i am|i have|i've|my)\b", re.IGNORECASE)
_IMMEDIATE = re.compile(
    r"\b(now|tonight|today|right away|about to|already|this evening|have a plan)\b",
    re.IGNORECASE,
)
_IMMEDIATE_DANGER_CONTEXT = re.compile(
    r"\b(i am in immediate danger|i'm in immediate danger|i can't stay safe|"
    r"i cannot stay safe|someone is hurting me|someone is going to hurt me|"
    r"i am about to hurt myself|i'm about to hurt myself)\b",
    re.IGNORECASE,
)


async def classify_voice_text(text: str, api_key: str) -> str:
    """Return a conservative operational state; never store or log the text.

    The Moderation API supplies contextual signals. A contextual first-person
    and immediacy check is also required before the highest state is returned.
    This is not a validated clinical classifier or diagnosis.
    """
    candidate = bool(_SELF_HARM_CONTEXT.search(text) or _IMMEDIATE_DANGER_CONTEXT.search(text))
    if not candidate:
        return DISTRESS if _DISTRESS.search(text) else NORMAL

    categories: dict[str, bool] = {}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                "https://api.openai.com/v1/moderations",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": "omni-moderation-latest", "input": text[:4000]},
            )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") or []
        if results:
            categories = results[0].get("categories") or {}
    except (httpx.HTTPError, ValueError, TypeError):
        # Do not silently treat an unreviewable candidate as normal. The
        # fallback only prompts a supportive check-in; it does not alert care.
        return HEIGHTENED_CONCERN

    intent = bool(categories.get("self-harm/intent"))
    self_harm = bool(categories.get("self-harm"))
    violence = bool(categories.get("violence"))
    current_personal_intent = bool(
        intent
        and _FIRST_PERSON.search(text)
        and _IMMEDIATE.search(text)
        and _SELF_HARM_CONTEXT.search(text)
    )
    explicit_immediate_danger = bool(
        _IMMEDIATE_DANGER_CONTEXT.search(text)
        and _FIRST_PERSON.search(text)
        and (violence or intent or self_harm)
    )
    if current_personal_intent or explicit_immediate_danger:
        return POTENTIAL_IMMEDIATE_DANGER
    if intent or bool(categories.get("self-harm/instructions")):
        return HEIGHTENED_CONCERN
    return DISTRESS if self_harm or _DISTRESS.search(text) else NORMAL
