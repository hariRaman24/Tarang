const API_BASE = window.location.origin;

const $ = id => document.getElementById(id);

const STATIONS = [
  ["Chennai", 13.05, 80.28],
  ["Cuddalore", 11.75, 79.77],
  ["Nagapattinam", 10.76, 79.84],
  ["Rameswaram", 9.29, 79.31],
  ["Tuticorin", 8.76, 78.13],
  ["Kanyakumari", 8.08, 77.55],
  ["Kochi", 9.93, 76.26],
  ["Mangalore", 12.87, 74.84],
  ["Goa", 15.40, 73.80],
  ["Mumbai", 18.95, 72.83],
  ["Veraval", 20.90, 70.37],
  ["Visakhapatnam", 17.69, 83.22],
  ["Paradip", 20.32, 86.61],
  ["Kolkata (Sagar)", 21.65, 88.05],
  ["Port Blair", 11.62, 92.72],
];

const I18N = {
  en: {
    subtitle: "Agentic Marine Intelligence Platform",
    location: "LOCATION",
    vessel: "VESSEL PROFILE",
    ask: "ASK TARANG",
    voice: "Voice language:",
    demo: "HACKATHON DEMO MODE",
    focused: "Focused on",
    queryPlaceholder: "Ask a marine question…",
  },
  ta: {
    subtitle: "முகவர் அடிப்படையிலான கடல் நுண்ணறிவு தளம்",
    location: "இடம்",
    vessel: "படகு விவரம்",
    ask: "TARANG-ஐ கேளுங்கள்",
    voice: "குரல் மொழி:",
    demo: "ஹாக்கத்தான் டெமோ முறை",
    focused: "தேர்ந்தெடுத்த இடம்",
    queryPlaceholder: "கடல் தொடர்பான கேள்வியை கேளுங்கள்…",
  },
  hi: {
    subtitle: "एजेंटिक समुद्री बुद्धिमत्ता प्लेटफ़ॉर्म",
    location: "स्थान",
    vessel: "नाव प्रोफ़ाइल",
    ask: "TARANG से पूछें",
    voice: "आवाज़ भाषा:",
    demo: "हैकाथॉन डेमो मोड",
    focused: "चयनित स्थान",
    queryPlaceholder: "समुद्री प्रश्न पूछें…",
  }
};

const SAMPLE_QUERIES = {
  en: [
    "Where is the nearest Potential Fishing Zone today?",
    "Is it safe to venture into the sea tomorrow morning?",
    "What are the weather and sea conditions near me?",
    "What is the safest route for a fishing vessel today?",
    "Are there any lightning or cyclone alerts in my area?",
    "Which regions show high chlorophyll concentration?",
    "Which fishing zones should be avoided due to hazardous conditions?"
  ],
  ta: [
    "இன்று அருகிலுள்ள Potential Fishing Zone எது?",
    "நாளை காலை கடலுக்குச் செல்லுவது பாதுகாப்பானதா?",
    "என் அருகிலுள்ள வானிலை மற்றும் கடல் நிலை என்ன?",
    "இன்று மீன்பிடி படகிற்கு பாதுகாப்பான பாதை எது?",
    "என் பகுதியில் மின்னல் அல்லது புயல் எச்சரிக்கை உள்ளதா?",
    "எந்த பகுதிகளில் குளோரோஃபில் அதிகமாக உள்ளது?",
    "ஆபத்தான நிலை காரணமாக எந்த மீன்பிடி மண்டலங்களை தவிர்க்க வேண்டும்?"
  ],
  hi: [
    "आज निकटतम Potential Fishing Zone कहाँ है?",
    "क्या कल सुबह समुद्र में जाना सुरक्षित है?",
    "मेरे पास मौसम और समुद्री स्थिति क्या है?",
    "आज मछली पकड़ने वाली नाव के लिए सुरक्षित मार्ग क्या है?",
    "क्या मेरे क्षेत्र में बिजली या चक्रवात चेतावनी है?",
    "किन क्षेत्रों में क्लोरोफिल अधिक है?",
    "खतरनाक स्थितियों के कारण किन fishing zones से बचना चाहिए?"
  ]
};

const DEMO_SCENARIOS = [
  {
    id: "pfz",
    label: "1 · Find nearest PFZ",
    query: "Where is the nearest Potential Fishing Zone today?",
    steps: [
      "Select a coastal location.",
      "Run a PFZ query.",
      "Show official PFZ + vessel range + landing-centre evidence."
    ]
  },
  {
    id: "safety",
    label: "2 · Check vessel safety",
    query: "Is it safe to venture into the sea tomorrow morning?",
    steps: [
      "Use tomorrow-morning forecast window.",
      "Compare wave/wind against vessel limits.",
      "Keep warning validity separate from model conditions."
    ]
  },
  {
    id: "route",
    label: "3 · Explain safest route",
    query: "What is the safest route for a fishing vessel today?",
    steps: [
      "Run Route Agent only for route intent.",
      "Show chosen and rejected corridors.",
      "Treat official warning as overriding benign model conditions."
    ]
  },
  {
    id: "tamil",
    label: "4 · Tamil conversation",
    query: "நாளை காலை கடலுக்குச் செல்லுவது பாதுகாப்பானதா?",
    steps: [
      "Switch UI/voice language to Tamil.",
      "Ask the question in Tamil.",
      "Show same-language synthesis and evidence."
    ]
  }
];

let uiLang = "en";
let voiceLang = "en-IN";
let selectedLat = 13.05;
let selectedLon = 80.28;
let selectedLocationName = "Chennai";
let latestResponse = null;
let currentForecastIndex = 0;
let radarLayer = null;
let routeLayer = null;

const map = L.map("map", {
  zoomControl: true
}).setView([13.05, 80.28], 7);

const osm = L.tileLayer(
  "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  { maxZoom: 18, attribution: "© OpenStreetMap" }
);

const satellite = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { maxZoom: 18, attribution: "Tiles © Esri" }
);

const ocean = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
  { maxZoom: 16, attribution: "Esri Ocean" }
);

satellite.addTo(map);

const mapOverlays = {};

L.control.layers(
  {
    "Satellite": satellite,
    "Ocean": ocean,
    "Street": osm
  },
  mapOverlays,
  { collapsed: true }
).addTo(map);

const pfzLayer = L.layerGroup().addTo(map);
let userMarker = L.marker([selectedLat, selectedLon])
  .addTo(map)
  .bindPopup("Chennai");

function safeText(value, fallback = "—") {
  return value === undefined || value === null || value === ""
    ? fallback
    : String(value);
}

function esc(value) {
  return safeText(value, "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function num(value, digits = 1) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function detectLanguage(text) {
  if (/[\u0B80-\u0BFF]/.test(text)) return "ta";
  if (/[\u0900-\u097F]/.test(text)) return "hi";
  return "en";
}

function applyLanguage(lang, syncVoice = true) {
  uiLang = I18N[lang] ? lang : "en";
  const t = I18N[uiLang];

  $("subtitle").textContent = t.subtitle;
  $("locationTitle").textContent = t.location;
  $("vesselTitle").textContent = t.vessel;
  $("askTitle").textContent = t.ask;
  $("voiceLabel").textContent = t.voice;
  $("demoTitle").textContent = t.demo;
  $("queryInput").placeholder = t.queryPlaceholder;

  document.querySelectorAll(".lang-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.lang === uiLang);
  });

  if (syncVoice) {
    voiceLang = uiLang === "ta" ? "ta-IN" : uiLang === "hi" ? "hi-IN" : "en-IN";
    document.querySelectorAll(".voice-lang").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.voiceLang === voiceLang);
    });
  }

  renderQueryChips();
  updateLocationText();
}

function updateLocationText() {
  $("locationText").textContent =
    `${I18N[uiLang].focused}: ${selectedLocationName} (${selectedLat.toFixed(4)}, ${selectedLon.toFixed(4)})`;
}

function renderQueryChips() {
  const wrap = $("queryChips");
  wrap.innerHTML = "";

  SAMPLE_QUERIES[uiLang].forEach((query, idx) => {
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = query.length > 43 ? query.slice(0, 43) + "…" : query;
    b.title = query;
    b.addEventListener("click", () => {
      $("queryInput").value = query;
      $("queryInput").focus();
    });
    wrap.appendChild(b);
  });
}

function renderDemoScenarios() {
  const wrap = $("demoScenarios");
  wrap.innerHTML = "";

  DEMO_SCENARIOS.forEach(scenario => {
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = scenario.label;
    b.addEventListener("click", () => {
      $("queryInput").value = scenario.query;
      $("demoSteps").innerHTML =
        `<b>${esc(scenario.label)}</b><br>` +
        scenario.steps.map((s, i) => `${i + 1}. ${esc(s)}`).join("<br>");

      if (scenario.id === "tamil") {
        applyLanguage("ta", true);
      }
    });
    wrap.appendChild(b);
  });
}

function resetDemoMode() {
  $("demoSteps").textContent =
    "Choose a scenario to guide the live demonstration.";
  $("queryInput").value = SAMPLE_QUERIES[uiLang][0];
}

document.querySelectorAll(".lang-btn").forEach(btn => {
  btn.addEventListener("click", () => applyLanguage(btn.dataset.lang, true));
});

document.querySelectorAll(".voice-lang").forEach(btn => {
  btn.addEventListener("click", () => {
    voiceLang = btn.dataset.voiceLang;
    document.querySelectorAll(".voice-lang").forEach(x => x.classList.remove("active"));
    btn.classList.add("active");
  });
});

$("resetDemo").addEventListener("click", resetDemoMode);

$("locationSelect").addEventListener("change", () => {
  const [lat, lon] = $("locationSelect").value.split(",").map(Number);
  selectedLat = lat;
  selectedLon = lon;
  selectedLocationName =
    $("locationSelect").options[$("locationSelect").selectedIndex].text;

  updateLocationText();
  userMarker.setLatLng([lat, lon]).bindPopup(selectedLocationName);
  map.setView([lat, lon], 8);
});

$("gpsBtn").addEventListener("click", () => {
  if (!navigator.geolocation) {
    $("requestState").textContent = "GPS is not supported by this browser.";
    return;
  }

  $("requestState").textContent = "Reading GPS location…";

  navigator.geolocation.getCurrentPosition(
    pos => {
      selectedLat = pos.coords.latitude;
      selectedLon = pos.coords.longitude;
      selectedLocationName = "GPS location";
      updateLocationText();
      userMarker.setLatLng([selectedLat, selectedLon]).bindPopup("GPS location");
      map.setView([selectedLat, selectedLon], 9);
      $("requestState").textContent = "GPS location selected.";
    },
    err => {
      $("requestState").textContent = `GPS unavailable: ${err.message}`;
    },
    { enableHighAccuracy: true, timeout: 12000 }
  );
});

function startVoiceInput() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SR) {
    $("requestState").textContent =
      "Voice recognition is not supported in this browser.";
    return;
  }

  const recognition = new SR();
  recognition.lang = voiceLang;
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  $("micBtn").textContent = "●";
  $("requestState").textContent = "Listening…";

  recognition.onresult = event => {
    const text = event.results?.[0]?.[0]?.transcript || "";
    if (text) {
      $("queryInput").value = text;
      const detected = detectLanguage(text);
      applyLanguage(detected, false);
    }
  };

  recognition.onerror = event => {
    $("requestState").textContent = `Voice input error: ${event.error}`;
  };

  recognition.onend = () => {
    $("micBtn").textContent = "🎙";
  };

  recognition.start();
}

$("micBtn").addEventListener("click", startVoiceInput);

async function checkBackend() {
  const el = $("backendStatus");

  try {
    const res = await fetch(`${API_BASE}/api/status`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    el.textContent = `Backend: ${data.status || "online"}`;
    el.className = "status status-ok";
  } catch (err) {
    el.textContent = "Backend: offline";
    el.className = "status status-bad";
  }
}

async function addRainRadar() {
  try {
    const res = await fetch(
      "https://api.rainviewer.com/public/weather-maps.json",
      { cache: "no-store" }
    );
    const data = await res.json();
    const frames = data?.radar?.past || [];
    const latest = frames.at(-1);
    if (!latest?.path) return;

    radarLayer = L.tileLayer(
      `https://tilecache.rainviewer.com${latest.path}/256/{z}/{x}/{y}/2/1_1.png`,
      {
        opacity: 0.55,
        maxNativeZoom: 7,
        maxZoom: 18,
        attribution: "Weather radar © RainViewer"
      }
    );

    // We add it by default but the user can remove it from the layer control
    // only after reload. This keeps the implementation dependency-free.
    radarLayer.addTo(map);
  } catch {
    // Radar is optional; map must still work without it.
  }
}

function renderAgentTrace(data) {
  const plan = data?.plan || {};
  const agents = data?.agents || {};
  const execution = data?.execution || {};

  const lines = [];

  const required =
    Array.isArray(plan.required_agents)
      ? plan.required_agents
          .map(x => prettyAgentName(x))
          .join(", ")
      : "";

  lines.push(
    `Planner Agent — intent: ${plan.intent || "unknown"}` +
    (required ? ` (agents: ${required})` : "")
  );

  if (plan.time_window) {
    lines.push(`Planner time window — ${plan.time_window}`);
  }

  if (plan.query_focus) {
    lines.push(`Planner query focus — ${plan.query_focus}`);
  }

  if (Array.isArray(plan.requested_hazards) && plan.requested_hazards.length) {
    lines.push(`Requested hazards — ${plan.requested_hazards.join(", ")}`);
  }

  if (execution.total_duration_ms != null) {
    lines.push(`Pipeline completed in ${execution.total_duration_ms} ms`);
  }

  for (const [key, value] of Object.entries(agents)) {
    if (!value) continue;

    let state = "OK";
    if (value.ok === false) state = "FAILED";
    else if (value.degraded) state = "degraded";

    lines.push(`${prettyAgentName(key)} — ${state}`);
  }

  if (Array.isArray(execution.agents)) {
    for (const item of execution.agents) {
      const name = prettyAgentName(item.agent);
      const duration = item.duration_ms ?? item.elapsed_ms ?? item.time_ms;
      const state =
        item.ok === false ? "FAILED" :
        item.degraded ? "degraded" :
        item.status || "OK";

      if (duration != null) {
        lines.push(`${name} — ${duration} ms — ${state}`);
      }
    }
  }

  $("agentTrace").innerHTML =
    lines.map(line => `<div class="trace-line">${esc(line)}</div>`).join("");

  $("agentTraceWrap").classList.remove("hidden");
}

function prettyAgentName(key) {
  const map = {
    planner: "Planner Agent",
    weather: "Weather Intelligence Agent",
    ocean: "Ocean Analytics Agent",
    geospatial: "Geospatial Reasoning Agent",
    risk: "Risk Assessment Agent",
    route: "Route Agent",
    synthesis: "Synthesis Agent"
  };
  return map[key] || key;
}

function renderAlerts(data) {
  const wrap = $("alertsArea");
  wrap.innerHTML = "";

  const alerts = Array.isArray(data?.alerts) ? [...data.alerts] : [];

  const risk = data?.agents?.risk?.data || {};
  const warning = risk.official_marine_warning || {};
  const plan = data?.plan || {};

  if (
    warning.applies_to_requested_time_window === true ||
    ((!plan.time_window || plan.time_window === "today") &&
      warning.sector_warning_match === true)
  ) {
    alerts.unshift(
      "Official marine-warning alert: an IMD/RMC warning matches this sector."
    );
  } else if (
    ["tonight", "tomorrow", "tomorrow_morning"].includes(plan.time_window) &&
    warning.current_sector_warning_match === true
  ) {
    alerts.unshift(
      "A current official marine warning exists, but its validity for the requested future period has not been confirmed."
    );
  }

  [...new Set(alerts)].forEach(alert => {
    const div = document.createElement("div");
    div.className = "alert-box";
    div.textContent = alert;
    wrap.appendChild(div);
  });
}

function renderAnswer(data) {
  latestResponse = data;

  $("answerCard").classList.remove("hidden");
  $("answerText").textContent =
    data?.answer || data?.synthesis?.answer || "No answer returned.";

  const detected = data?.language || detectLanguage($("queryInput").value);
  $("answerLangBadge").textContent = `LANG: ${detected.toUpperCase()}`;

  renderRecommendation(data);
  renderReasons(data);
  renderGeoSummary(data);
  renderTelemetry(data);
  renderProvenance(data);
  renderMarineAnalytics(data);

  renderAgentTrace(data);
  renderAlerts(data);
  renderMapData(data);
  setupForecast(data);
}

function renderRecommendation(data) {
  const risk = data?.agents?.risk?.data || {};
  const verdict = risk.verdict;

  if (!verdict) {
    $("recommendationRow").classList.add("hidden");
    return;
  }

  $("recommendationValue").textContent = verdict;
  $("recommendationRow").classList.remove("hidden");
}

function renderReasons(data) {
  const risk = data?.agents?.risk?.data || {};
  const reasons = Array.isArray(risk.reasons) ? risk.reasons : [];

  if (!reasons.length) {
    $("reasonWrap").classList.add("hidden");
    return;
  }

  $("reasons").innerHTML = reasons
    .map(reason => {
      const text =
        typeof reason === "string"
          ? reason
          : reason.code || reason.reason || JSON.stringify(reason);
      return `<div class="mini-item">— ${esc(text.replaceAll("_", " "))}</div>`;
    })
    .join("");

  $("reasonWrap").classList.remove("hidden");
}

function renderGeoSummary(data) {
  const geo = data?.agents?.geospatial?.data || {};
  const closest = geo.closest_pfz;
  const lines = [];

  if (closest) {
    lines.push(
      `Closest PFZ: ${closest.name || closest.uid || "PFZ"} (${safeText(closest.distance_km)} km)`
    );
  }

  if (geo.pfz_actionable !== undefined) {
    lines.push(`PFZ within configured range: ${geo.pfz_actionable ? "yes" : "no"}`);
  }

  if (geo.geofence_catalogue) {
    const authoritative =
      geo.geofence_catalogue.authoritative_dataset_loaded === true;
    lines.push(
      `Geofence data: ${authoritative ? "authoritative dataset loaded" : "approximate/incomplete reference only"}`
    );
  }

  if (!lines.length) {
    $("geoWrap").classList.add("hidden");
    return;
  }

  $("geoSummary").innerHTML =
    lines.map(x => `<div class="mini-item">${esc(x)}</div>`).join("");

  $("geoWrap").classList.remove("hidden");
}

function renderTelemetry(data) {
  const execution = data?.execution || {};
  const items = Array.isArray(execution.agents) ? execution.agents : [];

  if (!execution.total_duration_ms && !items.length) {
    $("telemetryWrap").classList.add("hidden");
    return;
  }

  const rows = [];

  if (execution.total_duration_ms != null) {
    rows.push(["Total pipeline time", `${execution.total_duration_ms} ms`]);
  }

  items.forEach(item => {
    rows.push([
      prettyAgentName(item.agent),
      `${item.duration_ms ?? item.elapsed_ms ?? item.time_ms ?? "—"} ms`
    ]);
  });

  $("telemetry").innerHTML =
    `<div class="telemetry-grid">` +
    rows.map(([a,b]) => `<div>${esc(a)}</div><div>${esc(b)}</div>`).join("") +
    `</div>`;

  $("telemetryWrap").classList.remove("hidden");
}

function renderProvenance(data) {
  const agents = data?.agents || {};
  const lines = [];

  const liveAgents = [];
  const degradedAgents = [];

  for (const [key, value] of Object.entries(agents)) {
    if (!value) continue;
    if (value.ok !== false) liveAgents.push(prettyAgentName(key));
    if (value.degraded) degradedAgents.push(prettyAgentName(key));
  }

  if (liveAgents.length) {
    lines.push(`Live agents: ${liveAgents.join(", ")}`);
  }

  if (degradedAgents.length) {
    lines.push(`Degraded agents: ${degradedAgents.join(", ")}`);
  }

  const weather = agents.weather || {};
  if (weather.source) {
    lines.push(`Weather source: ${weather.source}`);
  }

  const ocean = agents.ocean || {};
  if (ocean.source) {
    lines.push(`Ocean source: ${ocean.source}`);
  }

  const risk = agents.risk?.data || {};
  const warning = risk.official_marine_warning || {};
  if (warning.source) {
    lines.push(`Warning source: ${warning.source}`);
  }

  if (!lines.length) {
    $("provenanceWrap").classList.add("hidden");
    return;
  }

  $("provenance").innerHTML =
    lines.map(x => `<div class="mini-item">${esc(x)}</div>`).join("");

  $("provenanceWrap").classList.remove("hidden");
}

function renderMarineAnalytics(data) {
  const w = data?.agents?.weather?.data || {};
  const lines = [];

  if (w.wave_height_m != null) {
    const range =
      w.hourly_wave?.length
        ? `${Math.min(...w.hourly_wave.filter(Number.isFinite)).toFixed(2)}–${Math.max(...w.hourly_wave.filter(Number.isFinite)).toFixed(2)} m`
        : "—";
    lines.push(`Wave: ${w.wave_height_m} m (forecast ${range})`);
  }

  if (w.sea_surface_temperature_c != null) {
    const vals = (w.hourly_sst || []).filter(Number.isFinite);
    const range = vals.length
      ? `${Math.min(...vals).toFixed(1)}–${Math.max(...vals).toFixed(1)} °C`
      : "—";
    lines.push(`SST: ${w.sea_surface_temperature_c} °C (forecast ${range})`);
  }

  if (w.sea_level_height_msl_m != null) {
    const vals = (w.hourly_sea_level || []).filter(Number.isFinite);
    const range = vals.length
      ? `${Math.min(...vals).toFixed(2)}–${Math.max(...vals).toFixed(2)} m`
      : "—";
    lines.push(`Sea level / tide model: ${w.sea_level_height_msl_m} m (range ${range})`);
  }

  if (w.ocean_current_velocity_kmh != null) {
    lines.push(
      `Current: ${w.ocean_current_velocity_kmh} km/h at ${safeText(w.ocean_current_direction_deg)}°`
    );
  }

  if (!lines.length) {
    $("marineAnalyticsWrap").classList.add("hidden");
    return;
  }

  $("marineAnalytics").innerHTML =
    lines.map(x => `<div class="mini-item">${esc(x)}</div>`).join("");

  $("marineAnalyticsWrap").classList.remove("hidden");
}

function pfzCandidates(data) {
  return data?.agents?.geospatial?.data?.ranked_closest || [];
}

function candidateLat(c) {
  return Number(
    c.latitude ??
    c.nearest_latitude ??
    c.pfz_latitude ??
    c.lat ??
    c.nearest_point?.latitude
  );
}

function candidateLon(c) {
  return Number(
    c.longitude ??
    c.nearest_longitude ??
    c.pfz_longitude ??
    c.lon ??
    c.nearest_point?.longitude
  );
}

function renderMapData(data) {
  pfzLayer.clearLayers();

  if (routeLayer) {
    routeLayer.remove();
    routeLayer = null;
  }

  const loc = data?.location || {};
  const lat = Number(loc.latitude ?? selectedLat);
  const lon = Number(loc.longitude ?? selectedLon);

  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    userMarker
      .setLatLng([lat, lon])
      .bindPopup(loc.matched_station || selectedLocationName);

    map.setView([lat, lon], 8);
  }

  const candidates = pfzCandidates(data).slice(0, 10);

  candidates.forEach((c, idx) => {
    const plat = candidateLat(c);
    const plon = candidateLon(c);

    if (!Number.isFinite(plat) || !Number.isFinite(plon)) return;

    const within = c.within_vessel_range === true;
    const name = c.name || c.uid || c.sector || `PFZ ${idx + 1}`;

    const marker = L.circleMarker(
      [plat, plon],
      {
        radius: idx === 0 ? 7 : 6,
        weight: 2,
        color: within ? "#67d391" : "#9bb2bd",
        fillColor: within ? "#67d391" : "#8099a5",
        fillOpacity: .65
      }
    );

    const landing = c.nearest_landing_centre || c.landing_centre || {};
    const landingText =
      landing.name || landing.lc_name || c.nearest_landing_centre_name || "";

    marker.bindPopup(
      `<b>${esc(name)}</b><br>` +
      `Distance: ${esc(c.distance_km)} km<br>` +
      `Range: ${within ? "WITHIN" : "OUTSIDE"}<br>` +
      (landingText ? `Landing centre: ${esc(landingText)}<br>` : "")
    );

    marker.addTo(pfzLayer);
  });

  const route = data?.agents?.route?.data || {};
  const chosen = route.chosen || {};
  const waypoints = Array.isArray(chosen.waypoints) ? chosen.waypoints : [];

  const points = waypoints
    .map(w => {
      if (Array.isArray(w) && w.length >= 2) return [Number(w[0]), Number(w[1])];
      const a = Number(w.latitude ?? w.lat);
      const b = Number(w.longitude ?? w.lon);
      return [a,b];
    })
    .filter(([a,b]) => Number.isFinite(a) && Number.isFinite(b));

  if (points.length >= 2) {
    routeLayer = L.polyline(points, {
      weight: 3,
      color: "#f4a62a",
      dashArray: "6 5"
    }).addTo(map);

    map.fitBounds(routeLayer.getBounds(), { padding: [30,30] });
  }
}

function findCurrentHourIndex(times) {
  if (!Array.isArray(times) || !times.length) return 0;

  const now = Date.now();
  let bestIndex = 0;
  let bestDiff = Infinity;

  times.forEach((time, idx) => {
    const ts = new Date(time).getTime();
    if (!Number.isFinite(ts)) return;

    const diff = Math.abs(ts - now);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestIndex = idx;
    }
  });

  return bestIndex;
}

function arrVal(arr, idx) {
  return Array.isArray(arr) ? arr[idx] : undefined;
}

function setupForecast(data) {
  const w = data?.agents?.weather?.data || {};
  const times = w.hourly_time || [];
  const slider = $("forecastSlider");

  if (!times.length) {
    slider.min = 0;
    slider.max = 0;
    slider.value = 0;
    $("forecastReadout").textContent = "Hourly forecast unavailable.";
    $("forecastCard").classList.add("hidden");
    drawTrendChart(w, 0, 0);
    return;
  }

  const startIndex = findCurrentHourIndex(times);
  const maxOffset = Math.max(
    0,
    Math.min(47, times.length - startIndex - 1)
  );

  let initialOffset = 0;
  const assessment = w.assessment || {};

  if (
    assessment.status === "FORECAST_WINDOW_SELECTED" &&
    assessment.start_local
  ) {
    const targetIndex = times.findIndex(
      time =>
        String(time).slice(0,16) ===
        String(assessment.start_local).slice(0,16)
    );

    if (targetIndex >= startIndex) {
      initialOffset = Math.min(targetIndex - startIndex, maxOffset);
    }
  }

  slider.min = 0;
  slider.max = maxOffset;
  slider.value = initialOffset;

  const update = () => {
    const offset = Number(slider.value || 0);
    const idx = Math.min(startIndex + offset, times.length - 1);
    currentForecastIndex = idx;

    renderForecastReadout(w, idx, offset, initialOffset, assessment);
    renderForecastCard(w, idx, offset);
    drawTrendChart(
      w,
      startIndex,
      Math.min(times.length, startIndex + 48),
      offset
    );
  };

  slider.oninput = update;
  update();
}

function renderForecastReadout(w, idx, offset, initialOffset, assessment) {
  const bits = [];

  if (
    assessment.status === "FORECAST_WINDOW_SELECTED" &&
    offset === initialOffset
  ) {
    bits.push(`Requested period: ${assessment.label || assessment.requested_time_window}`);
  }

  bits.push(safeText(arrVal(w.hourly_time, idx)));
  bits.push(`🌡 ${safeText(arrVal(w.hourly_temperature, idx))}°C`);
  bits.push(`💨 ${safeText(arrVal(w.hourly_wind, idx))} km/h`);
  bits.push(`↯ ${safeText(arrVal(w.hourly_wind_gusts, idx))} km/h`);
  bits.push(`🌊 ${safeText(arrVal(w.hourly_wave, idx))} m`);
  bits.push(`SST ${safeText(arrVal(w.hourly_sst, idx))}°C`);

  $("forecastReadout").textContent = bits.join("  ·  ");
}

function renderForecastCard(w, idx, offset) {
  $("forecastCard").classList.remove("hidden");
  $("forecastCardTitle").textContent = `FORECAST +${offset}h`;

  const body = [];

  const condition =
    arrVal(w.hourly_weather_condition, idx) ||
    w.weather_condition ||
    "Marine forecast";

  body.push(`<div style="font-weight:700;margin-bottom:7px">${esc(condition)}</div>`);

  body.push(
    `<div>🌡 Air temperature: <b>${esc(safeText(arrVal(w.hourly_temperature, idx)))}°C</b></div>`
  );
  body.push(
    `<div>🔥 Feels like: <b>${esc(safeText(arrVal(w.hourly_apparent_temperature, idx)))}°C</b></div>`
  );
  body.push(
    `<div>💧 Humidity: <b>${esc(safeText(arrVal(w.hourly_humidity, idx)))}%</b></div>`
  );
  body.push(
    `<div>🌧 Rain: <b>${esc(safeText(arrVal(w.hourly_rain, idx)))} mm</b></div>`
  );
  body.push(
    `<div>☁ Cloud cover: <b>${esc(safeText(arrVal(w.hourly_cloud_cover, idx)))}%</b></div>`
  );
  body.push(
    `<div>◉ Pressure: <b>${esc(safeText(arrVal(w.hourly_pressure_msl, idx)))} hPa</b></div>`
  );
  body.push(
    `<div>💨 Wind: <b>${esc(safeText(arrVal(w.hourly_wind, idx)))} km/h</b></div>`
  );
  body.push(
    `<div>↯ Gust: <b>${esc(safeText(arrVal(w.hourly_wind_gusts, idx)))} km/h</b></div>`
  );

  body.push(`<div class="forecast-group-title">Marine</div>`);
  body.push(
    `<div>🌊 Sea temperature: <b>${esc(safeText(arrVal(w.hourly_sst, idx)))}°C</b></div>`
  );
  body.push(
    `<div>≈ Wave height: <b>${esc(safeText(arrVal(w.hourly_wave, idx)))} m</b></div>`
  );
  body.push(
    `<div>↗ Wave direction: <b>${esc(safeText(arrVal(w.hourly_wave_direction, idx)))}°</b></div>`
  );
  body.push(
    `<div>◴ Wave period: <b>${esc(safeText(arrVal(w.hourly_wave_period, idx)))} s</b></div>`
  );
  body.push(
    `<div>↕ Sea level: <b>${esc(safeText(arrVal(w.hourly_sea_level, idx)))} m</b></div>`
  );
  body.push(
    `<div>→ Ocean current: <b>${esc(safeText(arrVal(w.hourly_current_velocity, idx)))} km/h / ${esc(safeText(arrVal(w.hourly_current_direction, idx)))}°</b></div>`
  );

  $("forecastCardBody").innerHTML = body.join("");
}

$("forecastCardToggle").addEventListener("click", () => {
  const body = $("forecastCardBody");
  const hidden = body.classList.toggle("hidden");
  $("forecastCardToggle").textContent = hidden ? "+" : "−";
});

function normalizedSeries(values, start, end) {
  const slice = values.slice(start, end).map(Number);
  const valid = slice.filter(Number.isFinite);

  if (!valid.length) return slice.map(() => null);

  const min = Math.min(...valid);
  const max = Math.max(...valid);

  if (max === min) {
    return slice.map(v => Number.isFinite(v) ? 50 : null);
  }

  return slice.map(v =>
    Number.isFinite(v)
      ? ((v - min) / (max - min)) * 100
      : null
  );
}

function drawTrendChart(w, startIndex, endIndex, offset = 0) {
  const canvas = $("trendCanvas");
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();

  const width = Math.max(300, Math.floor(rect.width * devicePixelRatio));
  const height = Math.max(180, Math.floor(210 * devicePixelRatio));

  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.scale(devicePixelRatio, devicePixelRatio);

  const cssW = canvas.width / devicePixelRatio;
  const cssH = canvas.height / devicePixelRatio;

  const left = 34;
  const right = 12;
  const top = 12;
  const bottom = 26;
  const plotW = cssW - left - right;
  const plotH = cssH - top - bottom;

  ctx.strokeStyle = "#214759";
  ctx.lineWidth = 1;

  [0,25,50,75,100].forEach(v => {
    const y = top + plotH - (v / 100) * plotH;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(left + plotW, y);
    ctx.stroke();

    ctx.fillStyle = "#8fb1c2";
    ctx.font = "8px monospace";
    ctx.fillText(String(v), 5, y + 3);
  });

  const end = endIndex || Math.min((w.hourly_time || []).length, startIndex + 48);
  const wave = normalizedSeries((w.hourly_wave || []), startIndex, end);
  const wind = normalizedSeries((w.hourly_wind || []), startIndex, end);
  const sst = normalizedSeries((w.hourly_sst || []), startIndex, end);

  drawLine(ctx, wave, left, top, plotW, plotH, "#ed5a35");
  drawLine(ctx, wind, left, top, plotW, plotH, "#e8aa2b");
  drawLine(ctx, sst, left, top, plotW, plotH, "#75b796");

  const count = Math.max(wave.length, wind.length, sst.length, 1);
  const markerX =
    left + (Math.min(offset, count - 1) / Math.max(count - 1, 1)) * plotW;

  ctx.strokeStyle = "#d2dce1";
  ctx.setLineDash([3,3]);
  ctx.beginPath();
  ctx.moveTo(markerX, top);
  ctx.lineTo(markerX, top + plotH);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = "#8fb1c2";
  ctx.font = "8px monospace";
  ctx.fillText("now", left, cssH - 8);
  ctx.fillText(`+${Math.max(0, count - 1)}h`, left + plotW - 25, cssH - 8);

  ctx.restore();
}

function drawLine(ctx, series, left, top, plotW, plotH, color) {
  const n = Math.max(series.length - 1, 1);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();

  let started = false;

  series.forEach((v, i) => {
    if (v == null) {
      started = false;
      return;
    }

    const x = left + (i / n) * plotW;
    const y = top + plotH - (v / 100) * plotH;

    if (!started) {
      ctx.moveTo(x, y);
      started = true;
    } else {
      ctx.lineTo(x, y);
    }
  });

  ctx.stroke();
}

function buildPayload() {
  return {
    query: $("queryInput").value.trim(),
    latitude: selectedLat,
    longitude: selectedLon,
    location_name: selectedLocationName,
    vessel: {
      vessel_type: $("vesselType").value,
      range_km: Number($("rangeKm").value || 25)
    }
  };
}

async function askTarang() {
  const payload = buildPayload();

  if (!payload.query) {
    $("requestState").textContent = "Enter a question first.";
    return;
  }

  $("askBtn").disabled = true;
  $("requestState").textContent = "Sending query to planner…";
  $("answerCard").classList.add("hidden");
  $("agentTraceWrap").classList.remove("hidden");
  $("agentTrace").innerHTML =
    `<div class="trace-line">Sending query to planner…</div>`;

  try {
    const res = await fetch(`${API_BASE}/api/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    let data;
    try {
      data = await res.json();
    } catch {
      throw new Error(`HTTP ${res.status}: backend returned non-JSON content`);
    }

    if (!res.ok) {
      throw new Error(data?.detail || `HTTP ${res.status}`);
    }

    $("requestState").textContent = "Query complete.";
    renderAnswer(data);
  } catch (err) {
    $("requestState").textContent = `Request failed: ${err.message}`;
    $("answerCard").classList.remove("hidden");
    $("answerText").textContent =
      "The TARANG frontend could not obtain a valid backend response.";
  } finally {
    $("askBtn").disabled = false;
  }
}

$("askBtn").addEventListener("click", askTarang);

$("queryInput").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    askTarang();
  }
});

window.addEventListener("resize", () => {
  if (latestResponse) {
    const w = latestResponse?.agents?.weather?.data || {};
    const start = findCurrentHourIndex(w.hourly_time || []);
    drawTrendChart(
      w,
      start,
      Math.min((w.hourly_time || []).length, start + 48),
      Number($("forecastSlider").value || 0)
    );
  }
});

applyLanguage("en");
renderDemoScenarios();
resetDemoMode();
checkBackend();
addRainRadar();
updateLocationText();
