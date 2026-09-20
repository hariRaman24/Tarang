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


def _history_for_prompt(history: list[dict]) -> str:
    """
    Keep only the small amount of conversational context the planner needs.
    This supports follow-ups such as:
      - "what about tomorrow?"
      - "show the second one"
      - "is that safe for my boat?"
    without sending large telemetry/evidence payloads to Gemini.
    """
    compact: list[dict] = []

    for message in (history or [])[-8:]:
        item = {
            "role": message.get("role"),
            "content": message.get("content"),
        }

        payload = message.get("payload") or {}
        if payload:
            context: dict = {}

            if payload.get("location"):
                context["location"] = payload.get("location")

            if payload.get("vessel"):
                context["vessel"] = payload.get("vessel")

            old_plan = payload.get("plan") or {}
            if old_plan:
                context["previous_intent"] = old_plan.get("intent")
                context["previous_time_window"] = old_plan.get("time_window")
                context["previous_query_focus"] = old_plan.get("query_focus")

            if context:
                item["context"] = context

        compact.append(item)

    return json.dumps(
        compact,
        ensure_ascii=False,
        separators=(",", ":"),
    )


PLANNER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": list(INTENT_AGENTS.keys()),
        },
        "language": {
            "type": "string",
            "enum": ["en", "ta", "hi"],
        },
        "time_window": {
            "anyOf": [
                {
                    "type": "string",
                    "enum": [
                        "today",
                        "tomorrow",
                        "tomorrow_morning",
                        "tonight",
                    ],
                },
                {"type": "null"},
            ],
        },
        "location_name": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"},
            ],
        },
        "vessel_type": {
            "anyOf": [
                {
                    "type": "string",
                    "enum": [
                        "traditional",
                        "motorized",
                        "mechanized",
                    ],
                },
                {"type": "null"},
            ],
        },
        "query_focus": {
            "anyOf": [
                {
                    "type": "string",
                    "enum": [
                        "hazard_avoidance",
                        "specific_hazard_status",
                    ],
                },
                {"type": "null"},
            ],
        },
        "requested_hazards": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "cyclone",
                    "lightning",
                    "high_wave",
                    "strong_wind",
                    "marine_warning",
                ],
            },
        },
        "requires_clarification": {
            "type": "boolean",
        },
        "clarification": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"},
            ],
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "planning_summary": {
            "type": "string",
            "description": (
                "One short sentence describing the resolved intent/context. "
                "Do not reveal hidden chain-of-thought."
            ),
        },
    },
    "required": [
        "intent",
        "language",
        "time_window",
        "location_name",
        "vessel_type",
        "query_focus",
        "requested_hazards",
        "requires_clarification",
        "clarification",
        "confidence",
        "planning_summary",
    ],
}


def _llm_prompt(query: str, history: list[dict]) -> str:
    return f"""
You are the Planner Agent for TARANG, an agentic marine-intelligence
decision-support platform for fishermen.

Your job is PLANNING ONLY:
- understand the current user's intent,
- use recent conversation context when the query is a follow-up,
- detect English, Tamil, or Hindi,
- resolve the requested time window,
- identify specifically requested hazard classes,
- identify a location or vessel type only when the user actually states it,
- select exactly one intent from the allowed list.

Never invent weather, waves, PFZs, cyclone status, lightning status,
chlorophyll, SST, boundaries, routes, or safety conclusions.
Those facts must come from TARANG's deterministic tools and official/live
data connectors.

IMPORTANT SEMANTIC RULES:
1. "Which fishing zones should be avoided due to hazardous conditions?"
   => intent="pfz", query_focus="hazard_avoidance".
2. "Which fishing zones should be avoided due to restrictions/boundaries?"
   => intent="geofence".
3. A question specifically asking about cyclone/lightning/warnings
   => intent="alerts", query_focus="specific_hazard_status", and preserve
      each requested class in requested_hazards.
4. A safest-route/navigation/corridor question => intent="route".
5. "Why has fish productivity declined..." => intent="decline".
6. A follow-up such as "what about tomorrow?" should inherit the relevant
   previous intent/location/vessel context when it is unambiguous.
7. The current explicit user message always overrides older context.
8. If the request is genuinely ambiguous, set requires_clarification=true.

Allowed intents:
{", ".join(INTENT_AGENTS.keys())}

Recent conversation context:
{_history_for_prompt(history)}

Current user query:
{query}

Return only the structured response required by the JSON schema.
""".strip()


def _extract_interaction_text(body: dict) -> str:
    """
    Extract final text from the REST Interactions API response.

    The REST response contains steps. We accept the final model_output text
    and also tolerate a top-level output_text field if Google adds/provides it.
    """
    top_level = body.get("output_text")
    if isinstance(top_level, str) and top_level.strip():
        return top_level.strip()

    steps = body.get("steps") or []

    for step in reversed(steps):
        if step.get("type") != "model_output":
            continue

        content = step.get("content") or []
        for part in reversed(content):
            if (
                isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
                and part["text"].strip()
            ):
                return part["text"].strip()

    raise KeyError("No model_output text found in Gemini interaction response")


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
        # Required agents are assigned by TARANG, never trusted from the LLM.
        "required_agents": INTENT_AGENTS[intent],
        "confidence": max(0.0, min(float(confidence), 1.0)),
        "needs_clarification": bool(
            candidate.get("requires_clarification")
        ),
        "clarification": candidate.get("clarification"),
        "time_window": candidate.get("time_window"),
        "query_focus": candidate.get("query_focus"),
        "requested_hazards": candidate.get("requested_hazards") or [],
        "language": candidate.get("language", "en"),
        "entities": {
            "location_name": candidate.get("location_name"),
            "vessel_type": candidate.get("vessel_type"),
        },
        "planning_summary": candidate.get("planning_summary"),
        "planner": "gemini",
        "planner_model": GEMINI_MODEL,
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

    if not isinstance(
        result["clarification"],
        (str, type(None)),
    ):
        result["clarification"] = None

    if result["query_focus"] not in {
        None,
        "hazard_avoidance",
        "specific_hazard_status",
    }:
        result["query_focus"] = None

    allowed_hazards = {
        "cyclone",
        "lightning",
        "high_wave",
        "strong_wind",
        "marine_warning",
    }

    if not isinstance(
        result["requested_hazards"],
        list,
    ):
        result["requested_hazards"] = []

    result["requested_hazards"] = [
        item
        for item in result["requested_hazards"]
        if item in allowed_hazards
    ]

    # Keep deterministic safety-sensitive extraction as a guardrail.
    #
    # Gemini is used for richer language/context understanding, but explicit
    # hazard words and explicit supported time windows in the current query
    # must not disappear because of a model formatting/classification error.
    if fallback.get("query_focus") == "hazard_avoidance":
        result["intent"] = "pfz"
        result["required_agents"] = INTENT_AGENTS["pfz"]
        result["query_focus"] = "hazard_avoidance"

    if fallback.get("requested_hazards"):
        result["requested_hazards"] = list(
            dict.fromkeys(
                result["requested_hazards"]
                + fallback["requested_hazards"]
            )
        )

    if fallback.get("time_window") is not None:
        result["time_window"] = fallback["time_window"]

    if not isinstance(
        result.get("planning_summary"),
        str,
    ):
        result["planning_summary"] = (
            f"Resolved intent: {result['intent']}."
        )

    return result


async def plan_query(
    query: str,
    history: list[dict] | None = None,
) -> dict:
    """
    Gemini-first planner with deterministic safety fallback.

    Uses the current Gemini Interactions REST API with JSON-schema structured
    output. If Gemini is not configured, times out, returns malformed output,
    or is rejected by the API, TARANG continues with the deterministic planner.
    """
    fallback = _deterministic_plan(query)
    fallback["planner"] = "deterministic"
    fallback["entities"] = {
        "location_name": None,
        "vessel_type": None,
    }
    fallback["planning_summary"] = (
        f"Deterministic fallback resolved intent: {fallback['intent']}."
    )

    if not GEMINI_API_KEY:
        return fallback

    endpoint = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/interactions"
    )

    payload = {
        "model": GEMINI_MODEL,
        "input": _llm_prompt(
            query,
            history or [],
        ),
        # TARANG already stores its own conversation history in SQLite.
        # Avoid depending on provider-side conversation storage.
        "store": False,
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": PLANNER_RESPONSE_SCHEMA,
        },
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                15.0,
                connect=6.0,
            )
        ) as client:
            response = await client.post(
                endpoint,
                headers={
                    "x-goog-api-key": GEMINI_API_KEY,
                    "Content-Type": "application/json",
                    "x-goog-api-client": (
                        "tarang-marine-intelligence/1.0"
                    ),
                },
                json=payload,
            )
            response.raise_for_status()

            body = response.json()
            raw_text = _extract_interaction_text(body)
            candidate = json.loads(raw_text)

            plan = _validate_llm_plan(
                candidate,
                fallback,
            )

            if plan is not None:
                plan["planner_interaction_id"] = body.get("id")
                return plan

    except (
        httpx.HTTPError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        # Never take the whole TARANG system down because the optional LLM
        # planner is unavailable. The deterministic planner is the fallback.
        fallback["planner_status"] = (
            "gemini_unavailable_or_invalid"
        )
        fallback["planner_error_type"] = (
            type(exc).__name__
        )
        return fallback

    fallback["planner_status"] = (
        "gemini_unavailable_or_invalid"
    )
    return fallback


def planner_agent(query: str) -> dict:
    """Synchronous compatibility entry point used by existing callers/tests."""
    return _deterministic_plan(query)
