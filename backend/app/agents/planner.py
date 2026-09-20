"""
Planner Agent — keyword-based for now, deliberately (no LLM cost until a
Gemini key is available). Two real bugs fixed here after testing against
the live server, worth noting since they're the kind that don't show up
in unit tests with clean fixture text:

1. Substring matching let "safe**st** route" match the "safe" keyword
   before the query ever reached the "route" check. The actual fix is
   reordering — route is now checked before safety, so a query mentioning
   both hits route first. (A trailing word-boundary on "safe" alone
   wouldn't have been the right fix either: it would have also broken
   "safety" and "sailing", both of which should still match.)
2. This was English-only, so a pure Tamil/Hindi query matched nothing and
   silently fell through to the "conditions" default. Added Tamil/Hindi
   keyword sets per intent — same limitation as before (a keyword list
   can't understand phrasing it wasn't given), but it now at least covers
   the words the sample queries actually use in each language.
"""

import json
import re

import httpx

from app.config import GEMINI_API_KEY, GEMINI_MODEL

INTENT_AGENTS: dict[str, list[str]] = {
    "pfz": ["weather", "ocean", "geospatial", "risk"],
    "safety": ["weather", "geospatial", "risk"],
    "conditions": ["weather", "ocean"],
    "alerts": ["weather", "risk"],
    "chlorophyll": ["ocean"],
    "route": ["weather", "ocean", "geospatial", "route", "risk"],
    "decline": ["ocean"],
    "geofence": ["geospatial", "risk"],
}


# "avoid" is deliberately NOT a generic geofence keyword. A query such as
# "Which fishing zones should be avoided due to hazardous conditions?" is
# PFZ + risk analysis, not merely a boundary/geofence lookup.
KEYWORDS: list[tuple[str, list[str]]] = [
    ("route", ["route", "navigat", "corridor", "பாதை", "வழி", "मार्ग", "रास्ता"]),
    ("alerts", ["cyclone", "lightning", "alert", "warning", "புயல்", "மின்னல்", "எச்சரிக்கை", "चक्रवात", "बिजली", "चेतावनी"]),
    ("chlorophyll", ["chlorophyll", "க்ளோரோஃபில்", "क्लोरोफिल"]),
    ("decline", ["declin", "productivity", "trend", "குறைந்த", "உற்பத்தி", "उत्पादकता", "घट"]),
    ("geofence", [
        "boundary", "geofence", "restriction", "restrictions",
        "restricted area", "restricted zone",
        "protected area", "protected zone", "prohibited area",
        "prohibited zone", "exclusion zone", "marine protected area",
        "எல்லை", "கட்டுப்படுத்தப்பட்ட பகுதி", "பாதுகாக்கப்பட்ட பகுதி",
        "सीमा", "प्रतिबंधित क्षेत्र", "संरक्षित क्षेत्र",
    ]),
    ("pfz", [
        "fishing zone", "fishing zones", "pfz",
        "potential fishing zone", "potential fishing zones",
        "மீன்பிடி மண்டலம்", "மீன்பிடி பகுதிகள்",
        "मछली पकड़ने का क्षेत्र",
    ]),
    ("safety", [
        "safe", "safety", "venture", "sail", "go to sea",
        "பாதுகாப்பான", "பாதுகாப்பு", "செல்வது",
        "सुरक्षित", "सुरक्षा", "जाना",
    ]),
    ("conditions", [
        "weather", "conditions", "sea condition", "sea conditions",
        "forecast", "wave", "wind", "rain",
        "வானிலை", "கடல் நிலை", "அலை", "காற்று",
        "मौसम", "समुद्री स्थिति", "लहर", "हवा",
    ]),
]


FISHING_ZONE_TERMS = [
    "fishing zone", "fishing zones", "potential fishing zone",
    "potential fishing zones", "pfz", "மீன்பிடி மண்டலம்",
    "மீன்பிடி பகுதிகள்", "मछली पकड़ने का क्षेत्र",
]

HAZARD_AVOIDANCE_TERMS = [
    "hazard", "hazardous", "hazardous condition", "hazardous conditions",
    "danger", "dangerous", "unsafe", "risk", "risky",
    "rough sea", "high wave", "strong wind", "storm",
    "ஆபத்து", "அபாய", "பாதுகாப்பற்ற",
    "खतरा", "खतरनाक", "असुरक्षित", "जोखिम",
]


def _word_match(keyword: str, text: str) -> bool:
    if re.fullmatch(r"[a-zA-Z ]+", keyword):
        return re.search(rf"\b{re.escape(keyword)}", text) is not None
    return keyword in text


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(_word_match(term.lower(), text) for term in terms)


def _time_window(text: str) -> str | None:
    if any(term in text for term in ("tomorrow morning", "நாளை காலை", "कल सुबह")):
        return "tomorrow_morning"
    if any(term in text for term in ("tomorrow", "நாளை", "कल")):
        return "tomorrow"
    if any(term in text for term in ("today", "இன்று", "आज")):
        return "today"
    if any(term in text for term in ("tonight", "இன்றிரவு", "आज रात")):
        return "tonight"
    return None


def _requested_hazards(text: str) -> list[str]:
    hazards: list[str] = []
    mapping = [
        ("cyclone", ["cyclone", "புயல்", "चक्रवात"]),
        ("lightning", ["lightning", "மின்னல்", "बिजली"]),
        ("high_wave", ["high wave", "high-wave", "rough sea", "உயர் அலை", "ऊंची लहर"]),
        ("strong_wind", ["strong wind", "high wind", "பலத்த காற்று", "तेज हवा"]),
        ("marine_warning", ["marine warning", "fishermen warning", "கடல் எச்சரிக்கை", "समुद्री चेतावनी"]),
    ]
    for hazard, terms in mapping:
        if _contains_any(text, terms):
            hazards.append(hazard)
    return hazards


def _deterministic_plan(query: str) -> dict:
    text = query.lower()
    requested_hazards = _requested_hazards(text)
    query_focus: str | None = None

    # Special semantic rule: fishing-zone + explicit hazard language means
    # PFZ hazard analysis, not geofence-only analysis.
    #
    # "Avoid due to restrictions" is different: restriction language is handled
    # by the geofence intent because the user is asking about regulatory or
    # boundary constraints rather than environmental hazard conditions.
    if (
        _contains_any(text, FISHING_ZONE_TERMS)
        and _contains_any(text, HAZARD_AVOIDANCE_TERMS)
    ):
        intent = "pfz"
        matched = True
        query_focus = "hazard_avoidance"
    else:
        intent = "conditions"
        matched = False
        for candidate_intent, keywords in KEYWORDS:
            if _contains_any(text, keywords):
                intent = candidate_intent
                matched = True
                break

    if intent == "alerts" and requested_hazards:
        query_focus = "specific_hazard_status"

    return {
        "intent": intent,
        "required_agents": INTENT_AGENTS[intent],
        "confidence": 0.95 if query_focus else (0.9 if matched else 0.25),
        "needs_clarification": not matched,
        "time_window": _time_window(text),
        "query_focus": query_focus,
        "requested_hazards": requested_hazards,
        "clarification": (
            None if matched else
            "Do you want weather conditions, safety advice, PFZ discovery, "
            "alerts, route planning, or geofence information?"
        ),
    }


def _llm_prompt(query: str, history: list[dict]) -> str:
    return f"""
You are TARANG, a marine intelligence query planner. Return JSON only.
Never give safety advice and never invent marine data. Extract user intent
and entities so deterministic backend agents can calculate the answer.

Planning rules:
- "Which fishing zones should be avoided due to hazardous conditions?" is PFZ
  analysis with query_focus="hazard_avoidance", not a geofence-only query.
- "Which fishing zones should be avoided due to restrictions?" is a geofence /
  restriction query because the user is asking about regulatory/boundary limits.
- Preserve specifically requested hazard classes such as cyclone or lightning
  in requested_hazards.
- Use geofence only for actual protected/restricted/boundary-zone questions.

Allowed intents: {", ".join(INTENT_AGENTS)}.
Allowed languages: en, ta, hi.
JSON shape:
{{
  "intent": "one allowed intent",
  "language": "en",
  "time_window": "today|tomorrow|tomorrow_morning|tonight|null",
  "location_name": "string|null",
  "vessel_type": "traditional|motorized|mechanized|null",
  "query_focus": "hazard_avoidance|specific_hazard_status|null",
  "requested_hazards": ["cyclone|lightning|high_wave|strong_wind|marine_warning"],
  "requires_clarification": true,
  "clarification": "short question or null",
  "confidence": 0.0
}}

Previous conversation:
{history[-8:]}

Current query:
{query}
""".strip()


def _validate_llm_plan(candidate: object, fallback: dict) -> dict | None:
    if not isinstance(candidate, dict):
        return None
    intent = candidate.get("intent")
    if intent not in INTENT_AGENTS:
        return None

    confidence = candidate.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)):
        return None

    result = {
        "intent": intent,
        "required_agents": INTENT_AGENTS[intent],
        "confidence": max(0.0, min(float(confidence), 1.0)),
        "needs_clarification": bool(candidate.get("requires_clarification")),
        "clarification": candidate.get("clarification"),
        "time_window": candidate.get("time_window"),
        "query_focus": candidate.get("query_focus"),
        "requested_hazards": candidate.get("requested_hazards") or [],
        "language": candidate.get("language", "en"),
        "entities": {
            "location_name": candidate.get("location_name"),
            "vessel_type": candidate.get("vessel_type"),
        },
        "planner": "gemini",
    }
    if result["language"] not in {"en", "ta", "hi"}:
        result["language"] = "en"
    if result["time_window"] not in {
        None,
        "today",
        "tomorrow",
        "tomorrow_morning",
        "tonight",
    }:
        result["time_window"] = None
    if not isinstance(result["clarification"], (str, type(None))):
        result["clarification"] = None

    if result["query_focus"] not in {
        None,
        "hazard_avoidance",
        "specific_hazard_status",
    }:
        result["query_focus"] = None

    allowed_hazards = {
        "cyclone", "lightning", "high_wave", "strong_wind", "marine_warning",
    }
    if not isinstance(result["requested_hazards"], list):
        result["requested_hazards"] = []
    result["requested_hazards"] = [
        item for item in result["requested_hazards"]
        if item in allowed_hazards
    ]
    return result


async def plan_query(query: str, history: list[dict] | None = None) -> dict:
    """Use Gemini when configured, otherwise retain the deterministic plan."""
    fallback = _deterministic_plan(query)
    fallback["planner"] = "deterministic"
    fallback["entities"] = {
        "location_name": None,
        "vessel_type": None,
    }
    if not GEMINI_API_KEY:
        return fallback

    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )
    payload = {
        "contents": [{"parts": [{"text": _llm_prompt(query, history or [])}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(
                endpoint,
                params={"key": GEMINI_API_KEY},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            plan = _validate_llm_plan(json.loads(text), fallback)
            if plan is not None:
                return plan
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        # The deterministic planner is an intentional safety fallback when
        # the optional intelligence service is unavailable or malformed.
        pass

    fallback["planner_status"] = "gemini_unavailable_or_invalid"
    return fallback


def planner_agent(query: str) -> dict:
    """Synchronous compatibility entry point used by existing callers/tests."""
    return _deterministic_plan(query)
