"""
TARANG Synthesis Agent
======================

Deterministic multilingual synthesis for EN / TA / HI.

This version:
- Uses the live INCOIS geospatial PFZ results.
- Shows multiple nearby PFZ candidates instead of only one.
- Highlights which PFZs are within the vessel operating range.
- Does not claim a "best/productive PFZ" until a validated productivity
  rule is implemented.
- Includes official IMD/RMC Chennai fishermen-warning evidence in PFZ,
  safety, and route answers without treating a missing sector match as
  proof of safety.
- Explains planner-selected future safety windows using peak wave/wind/gust
  evidence while keeping future official-warning validity explicit.
- Avoids the old "curated dataset" PFZ wording.
"""

from __future__ import annotations

import re


TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


VESSEL_LABELS = {
    "traditional": {
        "en": "Traditional (catamaran / canoe)",
        "ta": "பாரம்பரிய படகு (கட்டுமரம் / தோணி)",
        "hi": "पारंपरिक नाव (कैटामरैन / डोंगी)",
    },
    "motorized": {
        "en": "Motorized boat",
        "ta": "மோட்டார் படகு",
        "hi": "मोटर चालित नाव",
    },
    "mechanized": {
        "en": "Mechanized trawler",
        "ta": "இயந்திரமயமாக்கப்பட்ட ட்ராலர்",
        "hi": "यंत्रीकृत ट्रॉलर",
    },
}


def vessel_label(vessel_type: str, lang: str) -> str:
    return VESSEL_LABELS.get(
        vessel_type,
        VESSEL_LABELS["motorized"],
    ).get(lang, VESSEL_LABELS["motorized"]["en"])


def detect_lang(query_text: str) -> str:
    if TAMIL_RE.search(query_text or ""):
        return "ta"

    if DEVANAGARI_RE.search(query_text or ""):
        return "hi"

    return "en"


def render_reason(reason: dict, lang: str) -> str:
    """
    Convert structured risk reason codes into user-facing text.

    NOTE:
    Legacy simulated cyclone/lightning reason codes are retained only for
    backward-compatible rendering. The current Risk Agent does not use
    simulated station flags as official hazard evidence.
    """

    code = reason.get("code", "")

    if code == "weather_unavailable":
        return {
            "en": (
                "Live weather data is currently unavailable, so the "
                "assessment is based on incomplete information."
            ),
            "ta": (
                "நேரடி வானிலை தரவு தற்போது கிடைக்கவில்லை; எனவே மதிப்பீடு "
                "முழுமையற்ற தகவலை அடிப்படையாகக் கொண்டது."
            ),
            "hi": (
                "लाइव मौसम डेटा अभी उपलब्ध नहीं है, इसलिए आकलन अधूरी "
                "जानकारी पर आधारित है।"
            ),
        }[lang]

    if code == "wave_exceeds":
        label = vessel_label(reason.get("vessel_type", "motorized"), lang)

        return {
            "en": (
                f"Wave height {reason.get('wave')} m exceeds this vessel's "
                f"{reason.get('threshold')} m threshold ({label})."
            ),
            "ta": (
                f"அலை உயரம் {reason.get('wave')} மீ, இந்த படகின் "
                f"{reason.get('threshold')} மீ வரம்பை மீறுகிறது ({label})."
            ),
            "hi": (
                f"लहर की ऊँचाई {reason.get('wave')} मी इस नाव की "
                f"{reason.get('threshold')} मी सीमा से अधिक है ({label})।"
            ),
        }[lang]

    if code == "wind_exceeds":
        label = vessel_label(reason.get("vessel_type", "motorized"), lang)

        return {
            "en": (
                f"Wind speed {reason.get('wind')} km/h exceeds this vessel's "
                f"{reason.get('threshold')} km/h threshold ({label})."
            ),
            "ta": (
                f"காற்று வேகம் {reason.get('wind')} கிமீ/மணி, இந்த படகின் "
                f"{reason.get('threshold')} கிமீ/மணி வரம்பை மீறுகிறது ({label})."
            ),
            "hi": (
                f"हवा की गति {reason.get('wind')} किमी/घंटा इस नाव की "
                f"{reason.get('threshold')} किमी/घंटा सीमा से अधिक है ({label})।"
            ),
        }[lang]

    if code == "cyclone_watch":
        return {
            "en": (
                "A simulated cyclone flag exists in the current prototype. "
                "It is not an official warning."
            ),
            "ta": (
                "தற்போதைய மாதிரியில் ஒரு சிமுலேட்டட் புயல் குறியீடு உள்ளது. "
                "இது அதிகாரப்பூர்வ எச்சரிக்கை அல்ல."
            ),
            "hi": (
                "वर्तमान प्रोटोटाइप में एक सिम्युलेटेड चक्रवात संकेत है। "
                "यह आधिकारिक चेतावनी नहीं है।"
            ),
        }[lang]

    if code == "lightning_risk":
        return {
            "en": (
                "A simulated lightning flag exists in the current prototype. "
                "It is not an official warning."
            ),
            "ta": (
                "தற்போதைய மாதிரியில் ஒரு சிமுலேட்டட் மின்னல் குறியீடு உள்ளது. "
                "இது அதிகாரப்பூர்வ எச்சரிக்கை அல்ல."
            ),
            "hi": (
                "वर्तमान प्रोटोटाइप में एक सिम्युलेटेड बिजली संकेत है। "
                "यह आधिकारिक चेतावनी नहीं है।"
            ),
        }[lang]

    if code == "current_official_warning_future_applicability_unverified":
        requested = reason.get("requested_time_window") or "requested future period"
        label_map = {
            "tomorrow_morning": {"en": "tomorrow morning", "ta": "நாளை காலை", "hi": "कल सुबह"},
            "tomorrow": {"en": "tomorrow", "ta": "நாளை", "hi": "कल"},
            "tonight": {"en": "tonight", "ta": "இன்றிரவு", "hi": "आज रात"},
            "today": {"en": "today", "ta": "இன்று", "hi": "आज"},
        }
        period = label_map.get(
            requested,
            {
                "en": str(requested).replace("_", " "),
                "ta": str(requested).replace("_", " "),
                "hi": str(requested).replace("_", " "),
            },
        )[lang]

        return {
            "en": (
                f"A current official marine warning exists, but its validity for "
                f"{period} has not yet been verified."
            ),
            "ta": (
                f"தற்போது அதிகாரப்பூர்வ கடல் எச்சரிக்கை உள்ளது; ஆனால் அது "
                f"{period} காலத்திற்கும் செல்லுபடியாகுமா என்பது இன்னும் சரிபார்க்கப்படவில்லை."
            ),
            "hi": (
                f"वर्तमान में एक आधिकारिक समुद्री चेतावनी है, लेकिन {period} के लिए "
                f"उसकी वैधता अभी सत्यापित नहीं हुई है।"
            ),
        }[lang]

    if code == "no_hazard_data":
        return {
            "en": (
                "Official hazard data is not yet connected for this exact "
                "location."
            ),
            "ta": (
                "இந்த துல்லியமான இடத்திற்கான அதிகாரப்பூர்வ ஆபத்து தரவு "
                "இன்னும் இணைக்கப்படவில்லை."
            ),
            "hi": (
                "इस सटीक स्थान के लिए आधिकारिक खतरा डेटा अभी जोड़ा नहीं गया है।"
            ),
        }[lang]

    if code == "official_marine_warning":
        sector = reason.get("sector") or "the requested marine sector"
        return {
            "en": (
                f"An official IMD/RMC Chennai marine warning matched {sector}."
            ),
            "ta": (
                f"{sector} பகுதிக்கு அதிகாரப்பூர்வ IMD/RMC Chennai கடல் எச்சரிக்கை பொருந்துகிறது."
            ),
            "hi": (
                f"{sector} क्षेत्र के लिए आधिकारिक IMD/RMC Chennai समुद्री चेतावनी मिली है।"
            ),
        }[lang]

    if code == "best_pfz_out_of_range":
        return {
            "en": (
                f"Recommended PFZ {reason.get('name')} is "
                f"{reason.get('distance_km')} km away, beyond this vessel's "
                f"{reason.get('range_km')} km operating range."
            ),
            "ta": (
                f"பரிந்துரைக்கப்பட்ட PFZ {reason.get('name')} "
                f"{reason.get('distance_km')} கிமீ தொலைவில் உள்ளது; இது "
                f"படகின் {reason.get('range_km')} கிமீ இயக்க வரம்பிற்கு அப்பால்."
            ),
            "hi": (
                f"अनुशंसित PFZ {reason.get('name')} "
                f"{reason.get('distance_km')} किमी दूर है, जो नाव की "
                f"{reason.get('range_km')} किमी सीमा से बाहर है।"
            ),
        }[lang]

    if code == "geofence_hit":
        inside = bool(reason.get("inside"))

        if lang == "en":
            where = (
                "inside"
                if inside
                else f"{reason.get('distance_km')} km from"
            )
            return (
                f"{where} the {reason.get('zone')} "
                f"({reason.get('kind')} zone)."
            )

        if lang == "ta":
            where = (
                "உள்ளே"
                if inside
                else f"{reason.get('distance_km')} கிமீ தொலைவில்"
            )
            return (
                f"{reason.get('zone')} ({reason.get('kind')} மண்டலம்) "
                f"{where}."
            )

        where = (
            "अंदर"
            if inside
            else f"{reason.get('distance_km')} किमी दूर"
        )
        return (
            f"{reason.get('zone')} ({reason.get('kind')} क्षेत्र) से "
            f"{where}।"
        )

    return code


def _pfz_status_text(
    within_range: bool | None,
    lang: str,
) -> str:
    if within_range is True:
        return {
            "en": "WITHIN RANGE",
            "ta": "படகு வரம்பிற்குள்",
            "hi": "नाव की सीमा के भीतर",
        }[lang]

    if within_range is False:
        return {
            "en": "OUTSIDE RANGE",
            "ta": "படகு வரம்பிற்கு வெளியே",
            "hi": "नाव की सीमा से बाहर",
        }[lang]

    return {
        "en": "RANGE UNKNOWN",
        "ta": "வரம்பு தெரியவில்லை",
        "hi": "सीमा अज्ञात",
    }[lang]


def _pfz_display_name(candidate: dict) -> str:
    """
    Friendly label for a real INCOIS PFZ candidate.
    """

    serial = candidate.get("serial_number")
    state = candidate.get("state_name")

    if serial and state:
        return f"PFZ {serial} — {state.title()}"

    return candidate.get("name", "INCOIS PFZ")


def _pfz_answer(
    lang: str,
    location: dict,
    geo: dict,
    risk: dict,
) -> tuple[str, list[str]]:
    """
    Build the PFZ answer from live INCOIS ranked candidates.

    Returns:
        answer_text,
        alerts
    """

    ranked = geo.get("ranked_closest") or []

    vessel_range = (
        risk.get("vessel", {}).get("range_km")
        or geo.get("vessel_range_km")
    )

    location_name = (
        location.get("matched_station")
        or location.get("location_name")
        or {
            "en": "this location",
            "ta": "இந்த இடம்",
            "hi": "इस स्थान",
        }[lang]
    )

    alerts: list[str] = []

    if not ranked:
        return (
            {
                "en": (
                    "No current official INCOIS PFZ geometry is available "
                    f"near {location_name}."
                ),
                "ta": (
                    f"{location_name} அருகில் தற்போதைய அதிகாரப்பூர்வ INCOIS "
                    "PFZ தகவல் கிடைக்கவில்லை."
                ),
                "hi": (
                    f"{location_name} के पास वर्तमान आधिकारिक INCOIS PFZ "
                    "ज्यामिति उपलब्ध नहीं है।"
                ),
            }[lang],
            alerts,
        )

    nearby = ranked[:5]

    item_texts: list[str] = []

    for index, candidate in enumerate(nearby, start=1):
        name = _pfz_display_name(candidate)
        distance = candidate.get("distance_km")
        status = _pfz_status_text(
            candidate.get("within_vessel_range"),
            lang,
        )

        landing = candidate.get("landing_centre") or {}

        landing_name = landing.get("name")
        landing_district = landing.get("district")
        landing_distance = landing.get("distance_from_pfz_km")

        if landing_name:
            if landing_district:
                landing_label = f"{landing_name}, {landing_district}"
            else:
                landing_label = landing_name
        else:
            landing_label = None

        if lang == "en":
            item = (
                f"{index}) {name} — {distance} km from {location_name}"
            )

            if landing_label:
                item += f" — near {landing_label}"

            if landing_distance is not None:
                item += (
                    f" — {landing_distance} km from the PFZ point "
                    f"to the landing centre"
                )

            item += f" — {status}"
            item_texts.append(item)

        elif lang == "ta":
            item = (
                f"{index}) {name} — {location_name} இலிருந்து "
                f"{distance} கிமீ"
            )

            if landing_label:
                item += f" — அருகிலுள்ள இறங்குமிடம்: {landing_label}"

            if landing_distance is not None:
                item += (
                    f" — PFZ புள்ளியிலிருந்து இறங்குமிடம் வரை "
                    f"{landing_distance} கிமீ"
                )

            item += f" — {status}"
            item_texts.append(item)

        else:
            item = (
                f"{index}) {name} — {location_name} से "
                f"{distance} किमी"
            )

            if landing_label:
                item += f" — निकटतम लैंडिंग सेंटर: {landing_label}"

            if landing_distance is not None:
                item += (
                    f" — PFZ बिंदु से लैंडिंग सेंटर तक "
                    f"{landing_distance} किमी"
                )

            item += f" — {status}"
            item_texts.append(item)

    actionable = [
        candidate
        for candidate in nearby
        if candidate.get("within_vessel_range") is True
    ]

    if actionable:
        actionable_names = ", ".join(
            _pfz_display_name(candidate)
            for candidate in actionable
        )

        actionable_line = {
            "en": (
                f"Within the configured {vessel_range} km vessel range: "
                f"{actionable_names}. This is a range check only, not an overall "
                f"safety clearance."
            ),
            "ta": (
                f"அமைக்கப்பட்ட {vessel_range} கிமீ படகு வரம்பிற்குள் உள்ள PFZ: "
                f"{actionable_names}. இது படகு வரம்பு சரிபார்ப்பு மட்டுமே; முழுமையான "
                f"பாதுகாப்பு அனுமதி அல்ல."
            ),
            "hi": (
                f"निर्धारित {vessel_range} किमी नाव सीमा के भीतर PFZ: "
                f"{actionable_names}। यह केवल दूरी/सीमा जाँच है, सम्पूर्ण "
                f"सुरक्षा अनुमति नहीं।"
            ),
        }[lang]
    else:
        nearest = nearby[0]

        actionable_line = {
            "en": (
                f"None of these PFZs is within the configured {vessel_range} km "
                f"vessel range. The nearest is "
                f"{_pfz_display_name(nearest)} at "
                f"{nearest.get('distance_km')} km, so it is not actionable "
                "for this vessel."
            ),
            "ta": (
                f"இந்த PFZ-களில் எதுவும் அமைக்கப்பட்ட {vessel_range} கிமீ படகு "
                f"வரம்பிற்குள் இல்லை. அருகிலுள்ளது "
                f"{_pfz_display_name(nearest)} — {nearest.get('distance_km')} கிமீ; "
                "எனவே இந்த படகுக்கு அது நடைமுறை பரிந்துரை அல்ல."
            ),
            "hi": (
                f"इन PFZ में से कोई भी निर्धारित {vessel_range} किमी नाव सीमा "
                f"के भीतर नहीं है। निकटतम "
                f"{_pfz_display_name(nearest)} {nearest.get('distance_km')} किमी "
                "दूर है, इसलिए यह इस नाव के लिए क्रियाशील सिफारिश नहीं है।"
            ),
        }[lang]

    source = geo.get("pfz_source") or {}
    landing_source = geo.get("landing_centre_source") or {}

    valid_upto = source.get("advisory_valid_upto")

    landing_live = (
        landing_source.get("status") == "LIVE"
    )

    if lang == "en":
        source_line = "Source: official INCOIS PFZ GeoServer WFS"
        if landing_live:
            source_line += " + official INCOIS Landing Centres WFS"
        if valid_upto:
            source_line += f"; PFZ advisory valid up to {valid_upto}"
        source_line += "."

        intro = (
            f"Nearby current Potential Fishing Zones from {location_name}: "
        )

        answer = (
            intro
            + "; ".join(item_texts)
            + ". "
            + actionable_line
            + " "
            + source_line
        )

    elif lang == "ta":
        source_line = "ஆதாரம்: அதிகாரப்பூர்வ INCOIS PFZ GeoServer WFS"
        if landing_live:
            source_line += " + அதிகாரப்பூர்வ INCOIS Landing Centres WFS"
        if valid_upto:
            source_line += f"; PFZ ஆலோசனை {valid_upto} வரை செல்லுபடியாகும்"
        source_line += "."

        intro = (
            f"{location_name} அருகிலுள்ள தற்போதைய மீன்பிடி மண்டலங்கள்: "
        )

        answer = (
            intro
            + "; ".join(item_texts)
            + ". "
            + actionable_line
            + " "
            + source_line
        )

    else:
        source_line = "स्रोत: आधिकारिक INCOIS PFZ GeoServer WFS"
        if landing_live:
            source_line += " + आधिकारिक INCOIS Landing Centres WFS"
        if valid_upto:
            source_line += f"; PFZ सलाह {valid_upto} तक मान्य"
        source_line += "।"

        intro = (
            f"{location_name} के पास वर्तमान संभावित मछली पकड़ने के क्षेत्र: "
        )

        answer = (
            intro
            + "; ".join(item_texts)
            + "। "
            + actionable_line
            + " "
            + source_line
        )

    return answer, alerts



def _normalize_warning_sector(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    if (
        "north" in cleaned
        and "tamil" in cleaned
    ):
        return "north_tamilnadu"

    if (
        "south" in cleaned
        and "tamil" in cleaned
    ):
        return "south_tamilnadu"

    return cleaned


def _pfz_hazard_avoidance_answer(
    lang: str,
    location: dict,
    geo: dict,
    risk: dict,
) -> tuple[str, list[str]]:
    """
    Answer: "Which fishing zones should be avoided due to hazardous conditions?"

    Safety policy:
    - Do not turn query-location weather into a fake per-PFZ hazard score.
    - A PFZ may be specifically flagged only when official warning evidence
      matches the same resolved marine sector.
    - "No warning match" is not treated as "safe".
    - Vessel range is reported separately from hazard evidence.
    """

    ranked = (
        geo.get("ranked_closest")
        or []
    )

    location_name = (
        location.get("matched_station")
        or location.get("location_name")
        or {
            "en": "this location",
            "ta": "இந்த இடம்",
            "hi": "इस स्थान",
        }[lang]
    )

    if not ranked:
        return (
            {
                "en": (
                    "TARANG cannot identify a fishing zone to avoid because "
                    f"no current official INCOIS PFZ geometry is available near "
                    f"{location_name}."
                ),
                "ta": (
                    f"{location_name} அருகில் தற்போதைய அதிகாரப்பூர்வ INCOIS PFZ "
                    "தரவு கிடைக்காததால் தவிர்க்க வேண்டிய மீன்பிடி மண்டலத்தை "
                    "TARANG குறிப்பிட முடியவில்லை."
                ),
                "hi": (
                    f"{location_name} के पास वर्तमान आधिकारिक INCOIS PFZ डेटा "
                    "उपलब्ध नहीं है, इसलिए TARANG किसी विशिष्ट मछली पकड़ने वाले "
                    "क्षेत्र को टालने के लिए चिन्हित नहीं कर सकता।"
                ),
            }[lang],
            [],
        )

    warning = (
        risk.get(
            "official_marine_warning"
        )
        or {}
    )

    warning_match = warning.get(
        "sector_warning_match"
    )

    warning_sector = (
        _normalize_warning_sector(
            warning.get("sector")
        )
    )

    in_range = [
        candidate
        for candidate in ranked[:5]
        if candidate.get(
            "within_vessel_range"
        )
        is True
    ]

    same_sector_in_range = []

    if (
        warning_match is True
        and warning_sector
    ):
        for candidate in in_range:
            candidate_sector = (
                _normalize_warning_sector(
                    candidate.get(
                        "state_name"
                    )
                )
            )

            if (
                candidate_sector
                == warning_sector
            ):
                same_sector_in_range.append(
                    candidate
                )

    flagged_names = [
        _pfz_display_name(
            candidate
        )
        for candidate in same_sector_in_range
    ]

    other_in_range = [
        candidate
        for candidate in in_range
        if candidate
        not in same_sector_in_range
    ]

    alerts: list[str] = []

    if flagged_names:
        flagged_text = ", ".join(
            flagged_names
        )

        if lang == "en":
            answer = (
                f"Avoid treating {flagged_text} as advisable for departure "
                f"right now. These PFZ candidate(s) are within the configured "
                f"vessel range and fall in the same marine sector for which the "
                f"official IMD/RMC Chennai warning is currently matched. "
                f"This is a warning-sector decision, not a productivity score."
            )

        elif lang == "ta":
            answer = (
                f"தற்போது {flagged_text} நோக்கி செல்லுவதை பரிந்துரைக்கப்பட்ட "
                f"நடவடிக்கையாக கருத வேண்டாம். இவை அமைக்கப்பட்ட படகு வரம்பிற்குள் "
                f"உள்ளதுடன், தற்போதைய அதிகாரப்பூர்வ IMD/RMC Chennai எச்சரிக்கை "
                f"பொருந்தும் அதே கடல் பிரிவில் உள்ள PFZ-கள். இது எச்சரிக்கை-பிரிவு "
                f"அடிப்படையிலான முடிவு; productivity score அல்ல."
            )

        else:
            answer = (
                f"अभी {flagged_text} की ओर प्रस्थान को सलाहयोग्य न मानें। ये "
                f"PFZ उम्मीदवार निर्धारित नाव सीमा के भीतर हैं और उसी समुद्री "
                f"क्षेत्र में आते हैं जिसके लिए वर्तमान आधिकारिक IMD/RMC Chennai "
                f"चेतावनी मेल खाती है। यह चेतावनी-क्षेत्र आधारित निर्णय है, "
                f"उत्पादकता स्कोर नहीं।"
            )

        if other_in_range:
            other_names = ", ".join(
                _pfz_display_name(
                    candidate
                )
                for candidate in other_in_range
            )

            answer += {
                "en": (
                    f" Other in-range PFZ candidate(s): {other_names}. "
                    "The current connector has not independently validated a "
                    "hazard warning for those candidate sectors, so TARANG does "
                    "not label them safe or hazardous from this evidence alone."
                ),
                "ta": (
                    f" வரம்பிற்குள் உள்ள மற்ற PFZ-கள்: {other_names}. "
                    "அந்த PFZ பிரிவுகளுக்கான தனித்த அதிகாரப்பூர்வ ஆபத்து "
                    "எச்சரிக்கை தற்போது சரிபார்க்கப்படாததால் அவற்றை பாதுகாப்பான "
                    "அல்லது ஆபத்தானதாக TARANG தனியாகக் குறிக்காது."
                ),
                "hi": (
                    f" अन्य सीमा-अंदर PFZ उम्मीदवार: {other_names}। उन क्षेत्रों "
                    "के लिए स्वतंत्र आधिकारिक खतरा चेतावनी सत्यापित नहीं हुई है, "
                    "इसलिए TARANG केवल इस साक्ष्य से उन्हें सुरक्षित या खतरनाक "
                    "नहीं कहता।"
                ),
            }[lang]

    elif warning_match is True:
        answer = {
            "en": (
                "An official marine warning is active for the resolved sector, "
                "but TARANG cannot confidently match any within-range PFZ "
                "candidate to that exact warning sector. It therefore does not "
                "invent a zone-specific 'avoid' label."
            ),
            "ta": (
                "தீர்மானிக்கப்பட்ட கடல் பிரிவுக்கு அதிகாரப்பூர்வ எச்சரிக்கை உள்ளது. "
                "ஆனால் வரம்பிற்குள் உள்ள எந்த PFZ-யையும் அந்த எச்சரிக்கை பிரிவுடன் "
                "உறுதியாக இணைக்க முடியாததால் TARANG போலியான zone-specific "
                "'தவிர்க்கவும்' குறிச்சொல்லை உருவாக்காது."
            ),
            "hi": (
                "निर्धारित समुद्री क्षेत्र के लिए आधिकारिक चेतावनी सक्रिय है, "
                "लेकिन TARANG किसी सीमा-अंदर PFZ को उस चेतावनी क्षेत्र से "
                "विश्वसनीय रूप से नहीं जोड़ पा रहा। इसलिए यह कोई कृत्रिम "
                "zone-specific 'avoid' लेबल नहीं बनाता।"
            ),
        }[lang]

    else:
        answer = {
            "en": (
                "TARANG cannot currently identify a specific PFZ that should be "
                "avoided from official hazard evidence alone. No explicit current "
                "warning match was validated for the resolved sector; that does "
                "not mean the PFZs are safe. Vessel range and weather conditions "
                "must still be considered separately."
            ),
            "ta": (
                "அதிகாரப்பூர்வ ஆபத்து ஆதாரத்தின் அடிப்படையில் தற்போது குறிப்பிட்ட "
                "ஒரு PFZ-யை 'தவிர்க்க வேண்டும்' என்று TARANG உறுதியாகச் சொல்ல முடியாது. "
                "தீர்மானிக்கப்பட்ட பிரிவுக்கு வெளிப்படையான தற்போதைய எச்சரிக்கை "
                "பொருத்தம் சரிபார்க்கப்படவில்லை; இதனால் PFZ-கள் பாதுகாப்பானவை என்று "
                "அர்த்தமில்லை. படகு வரம்பும் வானிலை நிலையும் தனியாக பார்க்க வேண்டும்."
            ),
            "hi": (
                "केवल आधिकारिक खतरा साक्ष्य के आधार पर TARANG अभी किसी विशिष्ट "
                "PFZ को 'टालें' नहीं कह सकता। निर्धारित क्षेत्र के लिए स्पष्ट "
                "वर्तमान चेतावनी मेल सत्यापित नहीं हुआ है; इसका अर्थ यह नहीं कि "
                "PFZ सुरक्षित हैं। नाव सीमा और मौसम को अलग से देखना होगा।"
            ),
        }[lang]

    if not in_range:
        nearest = ranked[0]
        answer += {
            "en": (
                f" Also, none of the displayed nearby PFZ candidates is within "
                f"the configured vessel range; the nearest is "
                f"{_pfz_display_name(nearest)} at {nearest.get('distance_km')} km."
            ),
            "ta": (
                f" மேலும் காட்டப்பட்ட PFZ-களில் எதுவும் அமைக்கப்பட்ட படகு "
                f"வரம்பிற்குள் இல்லை; அருகிலுள்ளது {_pfz_display_name(nearest)} "
                f"— {nearest.get('distance_km')} கிமீ."
            ),
            "hi": (
                f" साथ ही, दिखाए गए PFZ उम्मीदवारों में कोई भी निर्धारित नाव "
                f"सीमा के भीतर नहीं है; निकटतम {_pfz_display_name(nearest)} "
                f"{nearest.get('distance_km')} किमी दूर है।"
            ),
        }[lang]

    return answer, alerts



def _hazard_status_line(
    lang: str,
    risk: dict,
) -> tuple[str | None, list[str]]:
    """
    Convert official warning evidence into a concise user-facing safety caveat.
    Missing warning matches must never be presented as "safe".
    """
    decision_status = risk.get("decision_status")
    hazard = risk.get("official_marine_warning") or {}
    alerts: list[str] = []

    if decision_status == "OFFICIAL_MARINE_WARNING_MATCHED":
        line = {
            "en": (
                "Official IMD/RMC Chennai warning evidence matches this marine "
                "sector. Treat the warning as overriding otherwise benign model "
                "conditions."
            ),
            "ta": (
                "இந்த கடல் பகுதிக்கு அதிகாரப்பூர்வ IMD/RMC Chennai எச்சரிக்கை "
                "பொருந்துகிறது. சாதகமாகத் தோன்றும் மாதிரி வானிலை மதிப்புகளை விட "
                "இந்த அதிகாரப்பூர்வ எச்சரிக்கைக்கு முன்னுரிமை அளிக்க வேண்டும்."
            ),
            "hi": (
                "इस समुद्री क्षेत्र के लिए आधिकारिक IMD/RMC Chennai चेतावनी "
                "मिली है। सामान्य दिखने वाली मॉडल स्थितियों पर इस आधिकारिक "
                "चेतावनी को प्राथमिकता दें।"
            ),
        }[lang]

        alerts.append(
            {
                "en": "Official IMD/RMC Chennai marine warning matched this sector.",
                "ta": "இந்த பகுதிக்கு அதிகாரப்பூர்வ IMD/RMC Chennai கடல் எச்சரிக்கை பொருந்துகிறது.",
                "hi": "इस क्षेत्र के लिए आधिकारिक IMD/RMC Chennai समुद्री चेतावनी मिली है।",
            }[lang]
        )
        return line, alerts

    if decision_status == "OFFICIAL_WARNING_CHECKED_NO_EXPLICIT_SECTOR_MATCH":
        line = {
            "en": (
                "The official IMD/RMC Chennai fishermen-warning bulletin was "
                "checked for this sector and no explicit current sector warning "
                "was matched. This does not mean conditions are safe; official "
                "hazard coverage is still incomplete."
            ),
            "ta": (
                "இந்த பகுதிக்கான அதிகாரப்பூர்வ IMD/RMC Chennai மீனவர் எச்சரிக்கை "
                "அறிக்கை சரிபார்க்கப்பட்டது; தெளிவான தற்போதைய பகுதி எச்சரிக்கை "
                "பொருந்தவில்லை. இதனால் கடல் பாதுகாப்பானது என்று பொருள் கொள்ளக்கூடாது; "
                "அதிகாரப்பூர்வ ஆபத்து தரவு இன்னும் முழுமையில்லை."
            ),
            "hi": (
                "इस क्षेत्र के लिए आधिकारिक IMD/RMC Chennai मछुआरा चेतावनी "
                "बुलेटिन जाँचा गया और कोई स्पष्ट वर्तमान क्षेत्रीय चेतावनी नहीं "
                "मिली। इसका अर्थ समुद्र सुरक्षित है नहीं है; आधिकारिक खतरा "
                "कवरेज अभी अधूरा है।"
            ),
        }[lang]
        return line, alerts

    if risk.get("hazard_status") == "REQUESTED_WINDOW_OFFICIAL_WARNING_VALIDITY_NOT_EVALUATED":
        requested = (risk.get("conditions") or {}).get("requested_time_window")
        period = _window_label(requested, lang).lower()
        line = {
            "en": (
                f"Official warning validity for {period} has not yet been fully evaluated. "
                "A current warning may exist, but TARANG does not assume that it automatically "
                "applies to the requested future period."
            ),
            "ta": (
                f"{period} காலத்திற்கான அதிகாரப்பூர்வ எச்சரிக்கை செல்லுபடியாகும் நிலை இன்னும் முழுமையாக மதிப்பிடப்படவில்லை. "
                "தற்போதைய எச்சரிக்கை எதிர்கால காலத்திற்கும் தானாக பொருந்தும் என TARANG கருதாது."
            ),
            "hi": (
                f"{period} के लिए आधिकारिक चेतावनी की वैधता अभी पूरी तरह जाँची नहीं गई है। "
                "TARANG वर्तमान चेतावनी को अनुरोधित भविष्य अवधि पर स्वतः लागू नहीं मानता।"
            ),
        }[lang]
        return line, alerts

    if risk.get("hazard_status") in {
        "UNAVAILABLE",
        "NO_VALIDATED_OFFICIAL_WARNING_CONNECTOR_FOR_SECTOR",
        "OFFICIAL_WARNING_SCOPE_OR_TIME_AMBIGUOUS",
    }:
        line = {
            "en": (
                "Official hazard coverage is incomplete or unavailable for this "
                "sector, so TARANG cannot issue an overall safety clearance."
            ),
            "ta": (
                "இந்த பகுதிக்கான அதிகாரப்பூர்வ ஆபத்து தரவு முழுமையாக இல்லை அல்லது "
                "கிடைக்கவில்லை; எனவே TARANG முழுமையான பாதுகாப்பு அனுமதி வழங்காது."
            ),
            "hi": (
                "इस क्षेत्र के लिए आधिकारिक खतरा कवरेज अधूरा या अनुपलब्ध है, "
                "इसलिए TARANG पूर्ण सुरक्षा अनुमति नहीं देता।"
            ),
        }[lang]
        return line, alerts

    return None, alerts


def _window_label(
    requested: str | None,
    lang: str,
) -> str:
    labels = {
        "tomorrow_morning": {"en": "Tomorrow morning", "ta": "நாளை காலை", "hi": "कल सुबह"},
        "tomorrow": {"en": "Tomorrow", "ta": "நாளை", "hi": "कल"},
        "tonight": {"en": "Tonight", "ta": "இன்றிரவு", "hi": "आज रात"},
        "today": {"en": "Today", "ta": "இன்று", "hi": "आज"},
    }
    if requested in labels:
        return labels[requested][lang]
    return {
        "en": "Requested forecast period",
        "ta": "கோரப்பட்ட முன்னறிவிப்பு காலம்",
        "hi": "अनुरोधित पूर्वानुमान अवधि",
    }[lang]


def _clock_part(value) -> str | None:
    if not value:
        return None
    value = str(value)
    if "T" in value:
        return value.split("T", 1)[1][:5]
    return value


def _fmt_metric(value, digits: int = 1) -> str:
    if isinstance(value, (int, float)):
        rounded = round(float(value), digits)
        return str(int(rounded)) if float(rounded).is_integer() else str(rounded)
    return "UNAVAILABLE"


def _forecast_safety_line(
    lang: str,
    risk: dict,
) -> str | None:
    conditions = risk.get("conditions") or {}
    if conditions.get("evidence_mode") != "FORECAST_WINDOW":
        return None

    requested = conditions.get("requested_time_window")
    period = _window_label(requested, lang)
    start = _clock_part(conditions.get("window_start_local"))
    end = _clock_part(conditions.get("window_end_local"))
    window_text = f"{start}–{end} local" if start and end else "selected forecast window"

    wave = conditions.get("wave_height_m")
    wind = conditions.get("wind_speed_kmh")
    gust = conditions.get("wind_gusts_kmh")
    sst = conditions.get("sea_surface_temperature_c")
    vessel = risk.get("vessel") or {}
    max_wave = vessel.get("max_wave")
    max_wind = vessel.get("max_wind")
    threshold_exceeded = (
        conditions.get("wave_within_vessel_limit") is False
        or conditions.get("wind_within_vessel_limit") is False
    )

    if lang == "en":
        metrics = (
            f"peak wave {_fmt_metric(wave, 2)} m (limit {_fmt_metric(max_wave, 2)} m), "
            f"peak wind {_fmt_metric(wind, 1)} km/h (limit {_fmt_metric(max_wind, 1)} km/h), "
            f"peak gust {_fmt_metric(gust, 1)} km/h, average SST {_fmt_metric(sst, 1)}°C"
        )
        if threshold_exceeded:
            conclusion = (
                "At least one configured vessel threshold is exceeded, so "
                "TARANG marks this forecast window CAUTION."
            )
        else:
            conclusion = (
                "The available model wave/wind values do not exceed the configured vessel thresholds. "
                "Overall safety remains UNAVAILABLE because official hazard/warning validity for this "
                "future window is not yet fully verified."
            )
        return f"{period} ({window_text}): {metrics}. {conclusion}"

    if lang == "ta":
        metrics = (
            f"அதிகபட்ச அலை {_fmt_metric(wave, 2)} மீ (வரம்பு {_fmt_metric(max_wave, 2)} மீ), "
            f"அதிகபட்ச காற்று {_fmt_metric(wind, 1)} கிமீ/மணி (வரம்பு {_fmt_metric(max_wind, 1)} கிமீ/மணி), "
            f"அதிகபட்ச gust {_fmt_metric(gust, 1)} கிமீ/மணி, சராசரி SST {_fmt_metric(sst, 1)}°C"
        )
        conclusion = (
            "குறைந்தது ஒரு படகு வரம்பு மீறப்படுகிறது; எனவே இந்த காலத்துக்கு TARANG CAUTION எனக் காட்டுகிறது."
            if threshold_exceeded
            else "கிடைக்கும் மாதிரி அலை/காற்று மதிப்புகள் படகின் வரம்பை மீறவில்லை. ஆனால் இந்த எதிர்கால காலத்திற்கான அதிகாரப்பூர்வ ஆபத்து/எச்சரிக்கை செல்லுபடியாகும் நிலை முழுமையாக சரிபார்க்கப்படாததால் மொத்த பாதுகாப்பு நிலை UNAVAILABLE ஆகவே உள்ளது."
        )
        return f"{period} ({window_text}): {metrics}. {conclusion}"

    metrics = (
        f"अधिकतम लहर {_fmt_metric(wave, 2)} मी (सीमा {_fmt_metric(max_wave, 2)} मी), "
        f"अधिकतम हवा {_fmt_metric(wind, 1)} किमी/घंटा (सीमा {_fmt_metric(max_wind, 1)} किमी/घंटा), "
        f"अधिकतम झोंका {_fmt_metric(gust, 1)} किमी/घंटा, औसत SST {_fmt_metric(sst, 1)}°C"
    )
    conclusion = (
        "कम-से-कम एक निर्धारित नाव सीमा पार हो रही है, इसलिए TARANG इस अवधि को CAUTION मानता है।"
        if threshold_exceeded
        else "उपलब्ध मॉडल लहर/हवा मान निर्धारित नाव सीमा से अधिक नहीं हैं। लेकिन इस भविष्य अवधि के लिए आधिकारिक खतरे/चेतावनी की वैधता पूरी तरह सत्यापित नहीं है, इसलिए समग्र सुरक्षा स्थिति UNAVAILABLE है।"
    )
    return f"{period} ({window_text}): {metrics}. {conclusion}"


def _safety_line(
    lang: str,
    risk: dict,
) -> str:
    vessel = risk.get("vessel", {})

    label = vessel_label(
        vessel.get("type", "motorized"),
        lang,
    )

    safety_score = risk.get("safety_score")
    verdict = risk.get("verdict", "UNAVAILABLE")

    if safety_score is None:
        return {
            "en": (
                f"Complete safety scoring is unavailable for a {label.lower()} "
                f"because official hazard coverage is incomplete — status: {verdict}."
            ),
            "ta": (
                f"{label} க்கான முழுமையான பாதுகாப்பு மதிப்பீடு கிடைக்கவில்லை; "
                f"அதிகாரப்பூர்வ ஆபத்து தரவு முழுமையில்லை — நிலை: {verdict}."
            ),
            "hi": (
                f"{label} के लिए पूर्ण सुरक्षा स्कोर उपलब्ध नहीं है क्योंकि "
                f"आधिकारिक खतरा कवरेज अधूरा है — स्थिति: {verdict}।"
            ),
        }[lang]

    return {
        "en": (
            f"Safety score {safety_score}/100 for a {label.lower()} — "
            f"overall recommendation: {verdict}."
        ),
        "ta": (
            f"{label} க்கான பாதுகாப்பு மதிப்பெண் {safety_score}/100 — "
            f"மொத்த பரிந்துரை: {verdict}."
        ),
        "hi": (
            f"{label} के लिए सुरक्षा स्कोर {safety_score}/100 — "
            f"समग्र सिफारिश: {verdict}।"
        ),
    }[lang]


def _conditions_line(
    lang: str,
    weather: dict,
) -> str:
    wave = weather.get("wave_height_m")
    wind = weather.get("wind_speed_kmh")
    sst = weather.get("sea_surface_temperature_c")

    if wave is None and wind is None:
        return {
            "en": (
                "Live conditions are unavailable right now because the "
                "weather feed could not be reached."
            ),
            "ta": (
                "வானிலை தரவை பெற முடியாததால் தற்போதைய நேரடி நிலைமைகள் "
                "கிடைக்கவில்லை."
            ),
            "hi": (
                "मौसम फ़ीड उपलब्ध न होने के कारण लाइव स्थितियाँ अभी उपलब्ध नहीं हैं।"
            ),
        }[lang]

    return {
        "en": (
            f"Current conditions: wave {wave} m, wind {wind} km/h, "
            f"SST {sst}°C."
        ),
        "ta": (
            f"தற்போதைய நிலைமைகள்: அலை {wave} மீ, காற்று {wind} கிமீ/மணி, "
            f"கடல் மேற்பரப்பு வெப்பநிலை {sst}°C."
        ),
        "hi": (
            f"वर्तमान स्थिति: लहर {wave} मी, हवा {wind} किमी/घंटा, "
            f"समुद्र सतह तापमान {sst}°C।"
        ),
    }[lang]


def _route_line(
    lang: str,
    route: dict,
) -> str:
    chosen = route["chosen"]
    rejected = route["rejected"]

    crossed = bool(
        rejected.get("crosses_restricted")
    )

    protected_note = {
        "en": (
            " (the rejected alternative crosses a protected zone)"
            if crossed
            else ""
        ),
        "ta": (
            " (நிராகரிக்கப்பட்ட மாற்றுப் பாதை பாதுகாக்கப்பட்ட பகுதியை கடக்கிறது)"
            if crossed
            else ""
        ),
        "hi": (
            " (अस्वीकृत वैकल्पिक मार्ग संरक्षित क्षेत्र से गुजरता है)"
            if crossed
            else ""
        ),
    }[lang]

    return {
        "en": (
            f"Recommended route from {route.get('start')} to "
            f"{route.get('end')}: chosen corridor risk score "
            f"{chosen.get('risk_score')}, versus "
            f"{rejected.get('risk_score')} for the rejected alternative"
            f"{protected_note}."
        ),
        "ta": (
            f"{route.get('start')} முதல் {route.get('end')} வரை பரிந்துரைக்கப்பட்ட "
            f"பாதை: தேர்ந்தெடுக்கப்பட்ட பாதையின் ஆபத்து மதிப்பெண் "
            f"{chosen.get('risk_score')}; நிராகரிக்கப்பட்ட மாற்றுப் பாதை "
            f"{rejected.get('risk_score')}{protected_note}."
        ),
        "hi": (
            f"{route.get('start')} से {route.get('end')} तक अनुशंसित मार्ग: "
            f"चुने गए मार्ग का जोखिम स्कोर {chosen.get('risk_score')}, "
            f"अस्वीकृत विकल्प का {rejected.get('risk_score')}"
            f"{protected_note}।"
        ),
    }[lang]



def _automatic_safety_alerts(
    lang: str,
    weather_agent_result: dict,
    risk: dict,
    agents: dict,
) -> list[str]:
    """
    Add platform-wide safety and data-quality alerts to every response.

    For a planner-requested forecast window, threshold alerts use the
    time-window evidence already selected by Risk Agent rather than the
    current-condition weather values.

    A current official warning is NOT promoted to an active future-window
    warning unless Risk Agent explicitly marks it as applying to that
    requested period.
    """

    weather = (
        weather_agent_result.get("data")
        or {}
    )

    alerts: list[str] = []

    vessel = (
        risk.get("vessel")
        or {}
    )

    conditions = (
        risk.get("conditions")
        or {}
    )

    forecast_window = (
        conditions.get("evidence_mode")
        == "FORECAST_WINDOW"
    )

    if forecast_window:
        wave = conditions.get(
            "wave_height_m"
        )
        wind = conditions.get(
            "wind_speed_kmh"
        )
    else:
        wave = weather.get(
            "wave_height_m"
        )
        wind = weather.get(
            "wind_speed_kmh"
        )

    wave_limit = vessel.get(
        "max_wave"
    )
    wind_limit = vessel.get(
        "max_wind"
    )

    if (
        wave is not None
        and wave_limit is not None
        and wave > wave_limit
    ):
        alerts.append(
            {
                "en": (
                    f"High-wave alert: {wave} m exceeds the "
                    f"{wave_limit} m limit for this vessel."
                ),
                "ta": (
                    f"அதிக அலை எச்சரிக்கை: {wave} மீ, இந்த படகின் "
                    f"{wave_limit} மீ வரம்பை மீறுகிறது."
                ),
                "hi": (
                    f"ऊंची लहर चेतावनी: {wave} मी इस नाव की "
                    f"{wave_limit} मी सीमा से अधिक है।"
                ),
            }[lang]
        )

    if (
        wind is not None
        and wind_limit is not None
        and wind > wind_limit
    ):
        alerts.append(
            {
                "en": (
                    f"Strong-wind alert: {wind} km/h exceeds the "
                    f"{wind_limit} km/h limit for this vessel."
                ),
                "ta": (
                    f"பலத்த காற்று எச்சரிக்கை: {wind} கிமீ/மணி, "
                    f"இந்த படகின் {wind_limit} கிமீ/மணி வரம்பை மீறுகிறது."
                ),
                "hi": (
                    f"तेज हवा चेतावनी: {wind} किमी/घंटा इस नाव की "
                    f"{wind_limit} किमी/घंटा सीमा से अधिक है।"
                ),
            }[lang]
        )

    if not weather_agent_result.get(
        "ok",
        False,
    ):
        alerts.append(
            {
                "en": (
                    "Data-quality alert: live weather and marine data is "
                    "unavailable; do not treat this response as a safety "
                    "clearance."
                ),
                "ta": (
                    "தரத் தகவல் எச்சரிக்கை: நேரடி வானிலை மற்றும் கடல் தரவு "
                    "கிடைக்கவில்லை; இதை பாதுகாப்பு அனுமதியாக கருத வேண்டாம்."
                ),
                "hi": (
                    "डेटा गुणवत्ता चेतावनी: लाइव मौसम और समुद्री डेटा "
                    "उपलब्ध नहीं है; इसे सुरक्षा मंजूरी न मानें।"
                ),
            }[lang]
        )

    warning = (
        risk.get(
            "official_marine_warning"
        )
        or {}
    )

    if forecast_window:
        warning_match = warning.get(
            "applies_to_requested_time_window"
        )
    else:
        warning_match = warning.get(
            "sector_warning_match"
        )

    if warning_match is True:
        alerts.append(
            {
                "en": (
                    "Official marine-warning alert: an IMD/RMC warning "
                    "matches this sector."
                ),
                "ta": (
                    "அதிகாரப்பூர்வ கடல் எச்சரிக்கை: இந்த கடல் பிரிவுக்கு "
                    "IMD/RMC எச்சரிக்கை பொருந்துகிறது."
                ),
                "hi": (
                    "आधिकारिक समुद्री चेतावनी: इस क्षेत्र के लिए "
                    "IMD/RMC चेतावनी मिली है।"
                ),
            }[lang]
        )

    elif warning.get(
        "status"
    ) == "WARNING_SECTOR_UNRESOLVED":
        alerts.append(
            {
                "en": (
                    "Data-quality alert: the official warning sector could "
                    "not be resolved for this location."
                ),
                "ta": (
                    "தரத் தகவல் எச்சரிக்கை: இந்த இடத்திற்கான அதிகாரப்பூர்வ "
                    "எச்சரிக்கை பிரிவை தீர்மானிக்க முடியவில்லை."
                ),
                "hi": (
                    "डेटा गुणवत्ता चेतावनी: इस स्थान के लिए आधिकारिक "
                    "चेतावनी क्षेत्र निर्धारित नहीं हो सका।"
                ),
            }[lang]
        )

    geo = (
        agents.get(
            "geospatial",
            {},
        ).get(
            "data"
        )
        or {}
    )

    catalogue = (
        geo.get(
            "geofence_catalogue"
        )
        or {}
    )

    if not catalogue.get(
        "authoritative_dataset_loaded",
        False,
    ):
        alerts.append(
            {
                "en": (
                    "Geofence limitation: the configured boundary layer is "
                    "incomplete and approximate, not a legal navigation "
                    "boundary."
                ),
                "ta": (
                    "Geofence வரம்பு: இணைக்கப்பட்டுள்ள எல்லை அடுக்கு "
                    "முழுமையற்றது மற்றும் தோராயமானது; இது சட்டபூர்வ "
                    "வழிசெலுத்தல் எல்லை அல்ல."
                ),
                "hi": (
                    "जियोफेंस सीमा: उपलब्ध सीमा परत अधूरी और अनुमानित है; "
                    "यह कानूनी नेविगेशन सीमा नहीं है।"
                ),
            }[lang]
        )

    if (
        risk.get(
            "verdict"
        ) == "UNAVAILABLE"
        or not risk.get(
            "hazard_coverage_complete",
            False,
        )
    ):
        alerts.append(
            {
                "en": (
                    "Safety status is advisory and incomplete: official "
                    "hazard coverage is not complete."
                ),
                "ta": (
                    "பாதுகாப்பு நிலை ஆலோசனைக்குரியது மற்றும் முழுமையற்றது: "
                    "அதிகாரப்பூர்வ ஆபத்து தரவு முழுமையாக இல்லை."
                ),
                "hi": (
                    "सुरक्षा स्थिति सलाहकारी और अधूरी है: आधिकारिक खतरा "
                    "कवरेज पूरी नहीं है।"
                ),
            }[lang]
        )

    for name, result in agents.items():
        if (
            name != "risk"
            and result.get(
                "ok"
            ) is False
        ):
            alerts.append(
                {
                    "en": (
                        f"Data-quality alert: {name} agent did not return "
                        "a live result."
                    ),
                    "ta": (
                        f"தரத் தகவல் எச்சரிக்கை: {name} agent நேரடி "
                        "முடிவை வழங்கவில்லை."
                    ),
                    "hi": (
                        f"डेटा गुणवत्ता चेतावनी: {name} agent ने लाइव "
                        "परिणाम नहीं लौटाया।"
                    ),
                }[lang]
            )

    return alerts



def synthesize(
    plan: dict,
    location: dict,
    agents: dict,
    query_text: str = "",
) -> dict:
    lang = detect_lang(query_text)

    intent = plan.get("intent", "general")

    weather = (
        agents.get("weather", {}).get("data")
        or {}
    )

    geo = (
        agents.get("geospatial", {}).get("data")
        or {}
    )

    risk = (
        agents.get("risk", {}).get("data")
        or {}
    )

    lines: list[str] = []
    alerts: list[str] = []

    translated_reasons = [
        render_reason(reason, lang)
        for reason in risk.get("reasons", [])
    ]

    reason_prefix = {
        "en": "Reasoning: ",
        "ta": "காரணம்: ",
        "hi": "कारण: ",
    }[lang]

    if intent == "pfz":
        if (
            plan.get("query_focus")
            == "hazard_avoidance"
        ):
            pfz_answer, pfz_alerts = (
                _pfz_hazard_avoidance_answer(
                    lang,
                    location,
                    geo,
                    risk,
                )
            )
        else:
            pfz_answer, pfz_alerts = _pfz_answer(
                lang,
                location,
                geo,
                risk,
            )

        lines.append(pfz_answer)
        alerts.extend(pfz_alerts)

        hazard_line, hazard_alerts = _hazard_status_line(
            lang,
            risk,
        )

        if hazard_line:
            lines.append(hazard_line)

        alerts.extend(hazard_alerts)

    elif intent == "safety":
        forecast_line = _forecast_safety_line(
            lang,
            risk,
        )

        if forecast_line:
            lines.append(forecast_line)
        else:
            lines.append(_safety_line(lang, risk))

        hazard_line, hazard_alerts = _hazard_status_line(
            lang,
            risk,
        )
        if hazard_line:
            lines.append(hazard_line)
        alerts.extend(hazard_alerts)

        if translated_reasons:
            lines.append(
                reason_prefix
                + "; ".join(translated_reasons)
                + "."
            )

    elif intent == "conditions":
        lines.append(
            _conditions_line(
                lang,
                weather,
            )
        )

    elif intent == "geofence":
        hits = geo.get(
            "geofence_hits",
            [],
        )

        if hits:
            for hit in hits:
                alerts.append(
                    f"Restricted/geofenced zone: {hit.get('zone')}"
                )

            if translated_reasons:
                lines.append(
                    " ".join(
                        translated_reasons
                    )
                )

        else:
            lines.append(
                {
                    "en": (
                        "No geofenced zones were detected near this location "
                        "by the currently configured geofence layer."
                    ),
                    "ta": (
                        "தற்போது இணைக்கப்பட்டுள்ள geofence அடுக்கின் அடிப்படையில் "
                        "இந்த இடத்திற்கு அருகில் geofence பகுதி கண்டறியப்படவில்லை."
                    ),
                    "hi": (
                        "वर्तमान geofence लेयर के अनुसार इस स्थान के पास कोई "
                        "geofenced क्षेत्र नहीं मिला।"
                    ),
                }[lang]
            )

    elif intent == "chlorophyll":
        lines.append(
            {
                "en": (
                    "Official INCOIS chlorophyll is connected. Exact PFZ pixels "
                    "may still return NoData because of cloud, coastal or raster "
                    "masking. TARANG does not fabricate or substitute distant values."
                ),
                "ta": (
                    "அதிகாரப்பூர்வ INCOIS chlorophyll தரவு இணைக்கப்பட்டுள்ளது. "
                    "சில PFZ பிக்சல்களில் cloud/coastal/raster masking காரணமாக "
                    "NoData வரலாம். TARANG போலி அல்லது தொலைதூர மதிப்பை மாற்றாக பயன்படுத்தாது."
                ),
                "hi": (
                    "आधिकारिक INCOIS chlorophyll डेटा जुड़ा हुआ है। कुछ PFZ "
                    "पिक्सेल cloud/coastal/raster masking के कारण NoData दे सकते हैं। "
                    "TARANG कोई कृत्रिम या दूर का मान प्रतिस्थापित नहीं करता।"
                ),
            }[lang]
        )

    elif intent == "route":
        route = (
            agents.get("route", {}).get("data")
        )

        if route and route.get("chosen"):
            lines.append(
                _route_line(
                    lang,
                    route,
                )
            )

            if (
                route.get("rejected", {})
                .get("crosses_restricted")
            ):
                alerts.append(
                    {
                        "en": (
                            "Rejected alternative would cross a protected "
                            "or restricted zone."
                        ),
                        "ta": (
                            "நிராகரிக்கப்பட்ட மாற்றுப் பாதை பாதுகாக்கப்பட்ட அல்லது "
                            "கட்டுப்படுத்தப்பட்ட பகுதியை கடக்கும்."
                        ),
                        "hi": (
                            "अस्वीकृत वैकल्पिक मार्ग संरक्षित या प्रतिबंधित "
                            "क्षेत्र से गुजरता है।"
                        ),
                    }[lang]
                )

        else:
            lines.append(
                {
                    "en": (
                        "Route could not be computed because no usable PFZ "
                        "destination is available."
                    ),
                    "ta": (
                        "பயன்படுத்தக்கூடிய PFZ இலக்கு இல்லாததால் பாதையை கணக்கிட "
                        "முடியவில்லை."
                    ),
                    "hi": (
                        "उपयोग योग्य PFZ गंतव्य उपलब्ध न होने के कारण मार्ग "
                        "की गणना नहीं की जा सकी।"
                    ),
                }[lang]
            )

        # A route result must never hide official marine-warning evidence.
        # This is deliberately independent of whether route computation
        # succeeded: an active warning still needs to be surfaced.
        hazard_line, hazard_alerts = _hazard_status_line(
            lang,
            risk,
        )

        if hazard_line:
            lines.append(
                hazard_line
            )

        alerts.extend(
            hazard_alerts
        )

    else:
        lines.append(
            {
                "en": (
                    f"Safety score {risk.get('safety_score', '—')}/100, "
                    f"suitability {risk.get('suitability_score', '—')}/100."
                ),
                "ta": (
                    f"பாதுகாப்பு மதிப்பெண் {risk.get('safety_score', '—')}/100, "
                    f"ஏற்றத்தன்மை {risk.get('suitability_score', '—')}/100."
                ),
                "hi": (
                    f"सुरक्षा स्कोर {risk.get('safety_score', '—')}/100, "
                    f"उपयुक्तता {risk.get('suitability_score', '—')}/100।"
                ),
            }[lang]
        )

        if translated_reasons:
            note_prefix = {
                "en": "Notes: ",
                "ta": "குறிப்புகள்: ",
                "hi": "टिप्पणियाँ: ",
            }[lang]

            lines.append(
                note_prefix
                + "; ".join(translated_reasons)
                + "."
            )

    alerts = list(
        dict.fromkeys(
            alerts
            + _automatic_safety_alerts(
                lang,
                agents.get(
                    "weather",
                    {},
                ),
                risk,
                agents,
            )
            + [
                {
                    "en": (
                        "Advisory only: verify official marine bulletins "
                        "and use qualified navigation judgment before sailing."
                    ),
                    "ta": (
                        "ஆலோசனை மட்டுமே: கடலுக்குச் செல்லும் முன் "
                        "அதிகாரப்பூர்வ கடல் அறிவிப்புகளையும் தகுதியான "
                        "வழிசெலுத்தல் முடிவுகளையும் சரிபார்க்கவும்."
                    ),
                    "hi": (
                        "केवल सलाह: समुद्र में जाने से पहले आधिकारिक "
                        "समुद्री बुलेटिन और योग्य नेविगेशन निर्णय की पुष्टि करें।"
                    ),
                }[lang]
            ]
        )
    )

    # Official marine-warning alerts are emitted only when validated warning
    # evidence applies to the relevant time context. A missing match is never
    # presented as proof of safety.

    return {
        "answer": " ".join(lines),
        "alerts": alerts,
        "language": lang,
    }
