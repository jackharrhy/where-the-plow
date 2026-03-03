/* ── Address search (server-proxied Nominatim) ──────── */

const addressSearchInput = document.getElementById("address-search");
const searchIconEl = document.getElementById("search-icon");
const searchResultsEl = document.getElementById("search-results");
const searchContainer = document.getElementById("search-container");

let searchAbort = null;

const SEARCH_SVG = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="10.5" cy="10.5" r="7.5"/><line x1="16" y1="16" x2="22" y2="22"/></svg>';

function setSearchSpinner(on) {
  if (on) {
    searchIconEl.innerHTML = "";
    searchIconEl.classList.add("spinning");
  } else {
    searchIconEl.innerHTML = SEARCH_SVG;
    searchIconEl.classList.remove("spinning");
  }
}

async function searchAddress(query, signal) {
  const q = query.trim();
  if (!q) return [];

  const params = new URLSearchParams({ q });
  const resp = await fetch(`/search?${params}`, { signal });
  if (resp.status === 429) throw new Error("Too many searches. Please wait a moment.");
  if (!resp.ok) throw new Error("Search failed");
  return resp.json();
}

function showSearchResults(results, query) {
  searchResultsEl.innerHTML = "";
  searchResultsEl.classList.remove("search-results-hidden");
  searchContainer.classList.add("has-results");

  if (results.length === 0) {
    const item = document.createElement("div");
    item.className = "search-result-item search-result-error";
    item.textContent = "No results found. Try a street name or address.";
    searchResultsEl.appendChild(item);
    return;
  }

  for (const r of results) {
    const item = document.createElement("div");
    item.className = "search-result-item";
    item.dataset.lon = r.lon;
    item.dataset.lat = r.lat;
    item.innerHTML =
      '<span class="search-result-name">' +
      escapeHtml(r.label) +
      "</span>";
    item.addEventListener("click", () => {
      const lon = parseFloat(item.dataset.lon);
      const lat = parseFloat(item.dataset.lat);
      plowMap.map.flyTo({ center: [lon, lat], zoom: 17, duration: 1000 });
      addressSearchInput.value = "";
      hideSearchResults();
      addressSearchInput.blur();
      gtag("event", "address_search", { query: query.trim() });
    });
    searchResultsEl.appendChild(item);
  }
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}


function showSearchError(msg) {
  searchResultsEl.innerHTML = "";
  const item = document.createElement("div");
  item.className = "search-result-item search-result-error";
  item.textContent = msg;
  searchResultsEl.appendChild(item);
  searchResultsEl.classList.remove("search-results-hidden");
  searchContainer.classList.add("has-results");
}

function hideSearchResults() {
  searchResultsEl.innerHTML = "";
  searchResultsEl.classList.add("search-results-hidden");
  searchContainer.classList.remove("has-results");
}

async function doSearch() {
  const query = addressSearchInput.value.trim();
  if (!query) return;

  if (searchAbort) { searchAbort.abort(); searchAbort = null; }
  setSearchSpinner(true);

  searchAbort = new AbortController();
  try {
    const results = await searchAddress(query, searchAbort.signal);
    showSearchResults(results, query);
  } catch (err) {
    if (err.name === "AbortError") return;
    showSearchError(err.message || "Search failed. Please try again.");
    console.error("Address search error:", err);
  } finally {
    searchAbort = null;
    setSearchSpinner(false);
  }
}

addressSearchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    doSearch();
  } else if (e.key === "Escape") {
    if (searchAbort) { searchAbort.abort(); searchAbort = null; }
    hideSearchResults();
    addressSearchInput.blur();
  }
});

addressSearchInput.addEventListener("focus", () => {
  if (searchResultsEl.querySelector(".search-result-item")) {
    searchContainer.classList.add("has-results");
    searchResultsEl.classList.remove("search-results-hidden");
  }
});

document.addEventListener("click", (e) => {
  if (!searchContainer.contains(e.target)) {
    hideSearchResults();
  }
});

/* ── Welcome modal ──────────────────────────────────── */

const WELCOME_KEY = "wtp-welcome-dismissed";
const welcomeOverlay = document.getElementById("welcome-overlay");
const welcomeModal = document.getElementById("welcome-modal");
const welcomeCloseBtn = document.getElementById("welcome-close");
const welcomeDismissBtn = document.getElementById("welcome-dismiss");
const welcomeCtaBtn = document.getElementById("welcome-cta");
const signupPanel = document.getElementById("welcome-signup");
const signupEmail = document.getElementById("signup-email");
const signupProjects = document.getElementById("signup-projects");
const signupSH = document.getElementById("signup-siliconharbour");
const signupNoteToggle = document.getElementById("signup-note-toggle");
const signupNoteText = document.getElementById("signup-note-text");
const signupSubmitBtn = document.getElementById("signup-submit");
const signupStatus = document.getElementById("signup-status");
const btnViewInfo = document.getElementById("btn-view-info");

function showWelcome() {
  welcomeOverlay.classList.remove("hidden");
  // Reset signup section when reopening
  signupPanel.style.display = "none";
  welcomeCtaBtn.style.display = "";
  signupNoteText.style.display = "none";
  signupStatus.textContent = "";
  signupStatus.className = "";
}

function hideWelcome() {
  welcomeOverlay.classList.add("hidden");
  localStorage.setItem(WELCOME_KEY, "1");
}

// Show on first visit, hide if already dismissed
if (localStorage.getItem(WELCOME_KEY)) {
  welcomeOverlay.classList.add("hidden");
}

welcomeCloseBtn.addEventListener("click", hideWelcome);
welcomeDismissBtn.addEventListener("click", hideWelcome);

// Close on overlay click (but not modal click)
welcomeOverlay.addEventListener("click", (e) => {
  if (e.target === welcomeOverlay) hideWelcome();
});

// CTA expands signup section
welcomeCtaBtn.addEventListener("click", () => {
  welcomeCtaBtn.style.display = "none";
  signupPanel.style.display = "block";
  signupEmail.focus();
});

// Note toggle
signupNoteToggle.addEventListener("click", () => {
  const showing = signupNoteText.style.display !== "none";
  signupNoteText.style.display = showing ? "none" : "block";
  if (!showing) signupNoteText.focus();
});

// Submit signup
signupSubmitBtn.addEventListener("click", async () => {
  const email = signupEmail.value.trim();
  if (!email || !email.includes("@")) {
    signupStatus.textContent = "Please enter a valid email address.";
    signupStatus.className = "error";
    return;
  }

  signupSubmitBtn.disabled = true;
  signupStatus.textContent = "Submitting...";
  signupStatus.className = "";

  try {
    const resp = await fetch("/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        notify_plow: true,
        notify_projects: signupProjects.checked,
        notify_siliconharbour: signupSH.checked,
        note: signupNoteText.value.trim() || null,
      }),
    });
        if (resp.status === 429) {
            signupStatus.textContent = "Too many signups — please try again later.";
            signupStatus.className = "error";
            signupSubmitBtn.disabled = false;
            return;
        }
        if (!resp.ok) throw new Error("Signup failed");
    signupStatus.textContent =
      "You're signed up! I don't have a newsletter system just yet, but when I do, you'll be the first to know!";
    signupStatus.className = "success";
    signupEmail.disabled = true;
    signupProjects.disabled = true;
    signupSH.disabled = true;
    signupNoteText.disabled = true;
    signupNoteToggle.style.display = "none";
    signupSubmitBtn.style.display = "none";
    gtag("event", "signup", {
      notify_projects: signupProjects.checked,
      notify_siliconharbour: signupSH.checked,
      has_note: !!signupNoteText.value.trim(),
    });
  } catch (err) {
    signupStatus.textContent = "Something went wrong. Try again?";
    signupStatus.className = "error";
    signupSubmitBtn.disabled = false;
  }
});

// "About" link in panel footer reopens modal
btnViewInfo.addEventListener("click", (e) => {
  e.preventDefault();
  showWelcome();
});

/* ── Changelog modal ───────────────────────────────── */

const CHANGELOG_KEY = "wtp-changelog-seen";
const changelogOverlay = document.getElementById("changelog-overlay");
const changelogModal = document.getElementById("changelog-modal");
const changelogCloseBtn = document.getElementById("changelog-close");
const changelogContent = document.getElementById("changelog-content");
const btnViewChangelog = document.getElementById("btn-view-changelog");
const btnAboutChangelog = document.getElementById("btn-about-changelog");

let changelogHtml = null;
let changelogId = null;

async function loadChangelog() {
  if (changelogHtml !== null) return;
  try {
    const resp = await fetch("/static/changelog.html");
    if (!resp.ok) {
      changelogHtml = "<p>Changelog unavailable.</p>";
      return;
    }
    const html = await resp.text();
    const match = html.match(/data-changelog-id="(\d+)"/);
    changelogId = match ? parseInt(match[1]) : null;
    changelogHtml = html;
    checkChangelogUpdate();
  } catch {
    changelogHtml = "<p>Changelog unavailable.</p>";
  }
}

function checkChangelogUpdate() {
  if (changelogId === null) return;
  const seen = parseInt(localStorage.getItem(CHANGELOG_KEY) || "0");
  if (changelogId > seen) {
    btnViewChangelog.classList.add("has-update");
  }
}

function showChangelog() {
  changelogContent.innerHTML = changelogHtml || "<p>Loading...</p>";
  changelogOverlay.classList.remove("hidden");
  if (changelogId !== null) {
    localStorage.setItem(CHANGELOG_KEY, String(changelogId));
    btnViewChangelog.classList.remove("has-update");
  }
}

function hideChangelog() {
  changelogOverlay.classList.add("hidden");
}

// Load changelog eagerly on page load
loadChangelog();

btnViewChangelog.addEventListener("click", (e) => {
  e.preventDefault();
  showChangelog();
});

btnAboutChangelog.addEventListener("click", () => {
  hideWelcome();
  showChangelog();
});

changelogCloseBtn.addEventListener("click", hideChangelog);

changelogOverlay.addEventListener("click", (e) => {
  if (e.target === changelogOverlay) hideChangelog();
});

/* ── Panel toggle (mobile) ──────────────────────────── */

const panelToggle = document.getElementById("panel-toggle");
const infoPanel = document.getElementById("info-panel");

panelToggle.addEventListener("click", () => {
  const isOpen = infoPanel.classList.toggle("open");
  panelToggle.textContent = isOpen ? "\u2715" : "\u2630";
});

/* ── Move map controls when panel is tall ──────────── */

function updateControlPosition() {
  const panel = document.getElementById("info-panel");
  const panelHeight = panel.offsetHeight;
  const viewportHeight = window.innerHeight;
  // If panel uses >=70% of viewport height, shift controls left
  document.body.classList.toggle("controls-left", panelHeight >= viewportHeight * 0.7);
}

const _panelObserver = new ResizeObserver(updateControlPosition);
_panelObserver.observe(document.getElementById("info-panel"));
window.addEventListener("resize", updateControlPosition);

/* ── PlowMap class ─────────────────────────────────── */

class PlowMap {
  constructor(container, options) {
    this.map = new maplibregl.Map({ container, ...options });
    this.coverageAbort = null;
    this.deckOverlay = null;
  }

  on(event, layerOrCb, cb) {
    if (cb) this.map.on(event, layerOrCb, cb);
    else this.map.on(event, layerOrCb);
  }
  addControl(control, position) {
    this.map.addControl(control, position);
  }
  getZoom() {
    return this.map.getZoom();
  }
  getCenter() {
    return this.map.getCenter();
  }
  getBounds() {
    return this.map.getBounds();
  }
  getCanvas() {
    return this.map.getCanvas();
  }

  /* ── Vehicles ───────────────────────────────────── */

  _createArrowIcon() {
    const size = 32;
    const data = new Uint8Array(size * size * 4);

    // Draw a solid upward-pointing arrow using canvas for anti-aliasing,
    // then read the pixels back for addImage.
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");

    ctx.fillStyle = "white";
    ctx.beginPath();
    // Arrow pointing up: tip at top-center, wide base at bottom
    ctx.moveTo(size / 2, 2); // tip
    ctx.lineTo(size - 4, size - 4); // bottom-right
    ctx.lineTo(size / 2, size - 10); // notch
    ctx.lineTo(4, size - 4); // bottom-left
    ctx.closePath();
    ctx.fill();

    const imgData = ctx.getImageData(0, 0, size, size);
    data.set(imgData.data);

    this.map.addImage(
      "vehicle-arrow",
      { width: size, height: size, data },
      { sdf: true },
    );
  }

  initVehicles(data) {
    this._createArrowIcon();
    this.map.addSource("vehicles", { type: "geojson", data });

    // Black outline layer — slightly larger, drawn first (behind)
    this.map.addLayer({
      id: "vehicle-outline",
      type: "symbol",
      source: "vehicles",
      layout: {
        "icon-image": "vehicle-arrow",
        "icon-size": [
          "interpolate",
          ["linear"],
          ["zoom"],
          10,
          0.55,
          13,
          1.05,
          16,
          1.6,
        ],
        "icon-rotate": ["get", "bearing"],
        "icon-rotation-alignment": "map",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
      paint: {
        "icon-color": "#000000",
      },
    });

    // Colored foreground layer — drawn on top
    this.map.addLayer({
      id: "vehicle-circles",
      type: "symbol",
      source: "vehicles",
      layout: {
        "icon-image": "vehicle-arrow",
        "icon-size": [
          "interpolate",
          ["linear"],
          ["zoom"],
          10,
          0.4,
          13,
          0.85,
          16,
          1.4,
        ],
        "icon-rotate": ["get", "bearing"],
        "icon-rotation-alignment": "map",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
      paint: {
        "icon-color": [
          "match",
          ["get", "vehicle_type"],
          "SA PLOW TRUCK",
          "#2563eb",
          "TA PLOW TRUCK",
          "#2563eb",
          "LOADER",
          "#ea580c",
          "GRADER",
          "#16a34a",
          "#6b7280",
        ],
      },
    });
  }

  updateVehicles(data) {
    this.map.getSource("vehicles").setData(data);
  }

  setVehiclesVisible(visible) {
    const vis = visible ? "visible" : "none";
    for (const id of ["vehicle-outline", "vehicle-circles"]) {
      if (this.map.getLayer(id)) {
        this.map.setLayoutProperty(id, "visibility", vis);
      }
    }
  }

  /* ── Trails ─────────────────────────────────────── */

  showTrail(trailData, lineData) {
    this.clearTrail();
    this.map.addSource("vehicle-trail", { type: "geojson", data: trailData });
    this.map.addSource("vehicle-trail-line", {
      type: "geojson",
      data: lineData,
    });

    this.map.addLayer(
      {
        id: "vehicle-trail-line",
        type: "line",
        source: "vehicle-trail-line",
        paint: {
          "line-color": ["get", "seg_color"],
          "line-width": 5,
          "line-opacity": ["get", "seg_opacity"],
        },
      },
      "vehicle-circles",
    );

    this.map.addLayer(
      {
        id: "vehicle-trail-dots",
        type: "circle",
        source: "vehicle-trail",
        paint: {
          "circle-color": ["get", "trail_color"],
          "circle-radius": 2.5,
          "circle-opacity": ["get", "trail_opacity"],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1,
          "circle-stroke-opacity": ["*", ["get", "trail_opacity"], 0.8],
        },
      },
      "vehicle-circles",
    );
  }

  updateTrail(trailData, lineData) {
    const trailSource = this.map.getSource("vehicle-trail");
    if (trailSource) trailSource.setData(trailData);

    const lineSource = this.map.getSource("vehicle-trail-line");
    if (lineSource) lineSource.setData(lineData);
  }

  clearTrail() {
    if (this.map.getLayer("vehicle-trail-dots"))
      this.map.removeLayer("vehicle-trail-dots");
    if (this.map.getLayer("vehicle-trail-line"))
      this.map.removeLayer("vehicle-trail-line");
    if (this.map.getSource("vehicle-trail"))
      this.map.removeSource("vehicle-trail");
    if (this.map.getSource("vehicle-trail-line"))
      this.map.removeSource("vehicle-trail-line");
  }

  /* ── Mini-trails (realtime) ─────────────────────── */

  initMiniTrails(data) {
    this.map.addSource("mini-trails", { type: "geojson", data });
    this.map.addLayer(
      {
        id: "mini-trails",
        type: "line",
        source: "mini-trails",
        paint: {
          "line-color": ["get", "color"],
          "line-width": 5,
          "line-opacity": ["get", "opacity"],
        },
      },
      "vehicle-outline",
    );
  }

  updateMiniTrails(data) {
    const source = this.map.getSource("mini-trails");
    if (source) source.setData(data);
  }

  setMiniTrailsVisible(visible) {
    const vis = visible ? "visible" : "none";
    if (this.map.getLayer("mini-trails")) {
      this.map.setLayoutProperty("mini-trails", "visibility", vis);
    }
  }

  /* ── Coverage ───────────────────────────────────── */

  clearCoverage() {
    this.setDeckLayers([]);
  }

  setDeckLayers(layers) {
    if (this.deckOverlay) {
      this.deckOverlay.setProps({ layers });
    }
  }

  /* ── Type filtering ─────────────────────────────── */

  setTypeFilter(filter) {
    const layerIds = [
      "vehicle-outline",
      "vehicle-circles",
      "mini-trails",
      "vehicle-trail-dots",
      "vehicle-trail-line",
    ];
    for (const id of layerIds) {
      if (this.map.getLayer(id)) {
        this.map.setFilter(id, filter);
      }
    }
  }

  /* ── Abort management ───────────────────────────── */

  abortCoverage() {
    if (this.coverageAbort) {
      this.coverageAbort.abort();
      this.coverageAbort = null;
    }
  }

  newCoverageSignal() {
    this.abortCoverage();
    this.coverageAbort = new AbortController();
    return this.coverageAbort.signal;
  }
}

/* ── Map view persistence ──────────────────────────── */

const MAP_VIEW_KEY = "wtp-map-view";

function saveMapView() {
  const c = plowMap.getCenter();
  const z = plowMap.getZoom();
  localStorage.setItem(
    MAP_VIEW_KEY,
    JSON.stringify({ center: [c.lng, c.lat], zoom: z })
  );
}

function loadMapView() {
  try {
    const raw = localStorage.getItem(MAP_VIEW_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw);
    if (Array.isArray(v.center) && typeof v.zoom === "number") return v;
  } catch {}
  return null;
}

/* ── Map init ──────────────────────────────────────── */

const MAP_STYLE_KEY = "wtp-map-style";
const LIGHT_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const DARK_STYLE = "https://tiles.openfreemap.org/styles/dark";

function getMapStyle() {
  const saved = localStorage.getItem(MAP_STYLE_KEY);
  return saved === "dark" ? DARK_STYLE : LIGHT_STYLE;
}

function isMapDark() {
  return localStorage.getItem(MAP_STYLE_KEY) === "dark";
}

const savedView = loadMapView();

const plowMap = new PlowMap("map", {
  style: getMapStyle(),
  center: savedView ? savedView.center : [-52.71, 47.56],
  zoom: savedView ? savedView.zoom : 12,
});

const geolocate = new maplibregl.GeolocateControl({
  positionOptions: { enableHighAccuracy: true },
  trackUserLocation: true,
  showUserHeading: true,
});
plowMap.addControl(geolocate, "bottom-right");
geolocate.on("geolocate", () => gtag("event", "geolocate"));

// Persist map view to localStorage on every move
plowMap.on("moveend", saveMapView);

/* ── Analytics: debounced viewport tracking ────────── */

let viewportTimer = null;

plowMap.on("moveend", () => {
  clearTimeout(viewportTimer);
  viewportTimer = setTimeout(() => {
    const zoom = plowMap.getZoom();
    if (zoom < 13) return;

    const center = plowMap.getCenter();
    const bounds = plowMap.getBounds();
    const round4 = (n) => Math.round(n * 10000) / 10000;

    gtag("event", "viewport_focus", {
      zoom: Math.round(zoom * 10) / 10,
      center_lng: round4(center.lng),
      center_lat: round4(center.lat),
    });

    const payload = JSON.stringify({
      zoom: Math.round(zoom * 10) / 10,
      center: [round4(center.lng), round4(center.lat)],
      bounds: {
        sw: [round4(bounds.getWest()), round4(bounds.getSouth())],
        ne: [round4(bounds.getEast()), round4(bounds.getNorth())],
      },
    });

    if (navigator.sendBeacon) {
      navigator.sendBeacon(
        "/track",
        new Blob([payload], { type: "application/json" }),
      );
    } else {
      fetch("/track", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
        keepalive: true,
      }).catch(() => {});
    }
  }, 5000);
});

/* ── Utilities ─────────────────────────────────────── */

const ONE_DAY_MS = 24 * 60 * 60 * 1000;
const FIVE_MIN_MS = 5 * 60 * 1000;

/** Round a Date down to the nearest 5-minute boundary. */
function floorTo5Min(date) {
  return new Date(Math.floor(date.getTime() / FIVE_MIN_MS) * FIVE_MIN_MS);
}
const VEHICLE_STALE_MS = 2 * 60 * 60 * 1000; // hide vehicles not seen in 2 hours
const SOURCE_STALE_MS = 30 * 60 * 1000; // warn if source has no data in 30 minutes

const VEHICLE_COLORS = {
  "SA PLOW TRUCK": "#2563eb",
  "TA PLOW TRUCK": "#2563eb",
  LOADER: "#ea580c",
  GRADER: "#16a34a",
};
const DEFAULT_COLOR = "#6b7280";
const KNOWN_TYPES = ["SA PLOW TRUCK", "TA PLOW TRUCK", "LOADER", "GRADER"];

function vehicleColor(type) {
  return VEHICLE_COLORS[type] || DEFAULT_COLOR;
}

/** Return [R, G, B] for a vehicle type — used by deck.gl layers. */
function vehicleColorRGB(type) {
  const hex = vehicleColor(type);
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

function buildMiniTrails(data) {
  const features = [];
  for (const f of data.features) {
    const trail = f.properties.trail;
    if (!trail || trail.length < 2) continue;
    const color = vehicleColor(f.properties.vehicle_type);
    const count = trail.length - 1;
    for (let i = 0; i < count; i++) {
      const opacity = count === 1 ? 0.7 : 0.15 + (i / (count - 1)) * 0.55;
      features.push({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [trail[i], trail[i + 1]],
        },
        properties: { color, opacity, vehicle_type: f.properties.vehicle_type, source: f.properties.source },
      });
    }
  }
  return { type: "FeatureCollection", features };
}

function formatTimestamp(ts) {
  const d = new Date(ts);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDurationAgo(ms) {
  const minutes = Math.floor(ms / 60000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  const remainMin = minutes % 60;
  if (hours < 24) return remainMin > 0 ? `${hours}h ${remainMin}m ago` : `${hours}h ago`;
  const days = Math.floor(hours / 24);
  const remainHrs = hours % 24;
  return remainHrs > 0 ? `${days}d ${remainHrs}h ago` : `${days}d ago`;
}

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1024 * 1024 * 1024)
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + " GB";
}

/* ── API ───────────────────────────────────────────── */

async function fetchVehicles() {
  const resp = await fetch("/vehicles");
  return resp.json();
}

function updateVehicleCount(data) {
  const count = data.features ? data.features.length : 0;
  document.getElementById("vehicle-count").textContent =
    count + " vehicle" + (count !== 1 ? "s" : "") + " tracked";
  fetch("/stats")
    .then((r) => r.json())
    .then((stats) => {
      if (stats.db_size_bytes) {
        document.getElementById("db-size").textContent =
          formatBytes(stats.db_size_bytes) + " of data";
      }
    })
    .catch(() => {});
}

function filterRecentFeatures(data) {
  const cutoff = Date.now() - VEHICLE_STALE_MS;
  return {
    ...data,
    features: data.features.filter(
      (f) => new Date(f.properties.timestamp).getTime() > cutoff,
    ),
  };
}

/* ── Vehicle detail panel: DOM refs ─────────────────── */

const vehicleHint = document.getElementById("vehicle-hint");
const detailPanel = document.getElementById("vehicle-detail");
const detailName = document.getElementById("detail-name");
const detailType = document.getElementById("detail-type");
const detailSpeed = document.getElementById("detail-speed");
const detailBearing = document.getElementById("detail-bearing");
const detailUpdated = document.getElementById("detail-updated");
const detailSource = document.getElementById("detail-source");

/* ── Vehicle trails ────────────────────────────────── */

async function fetchTrail(vehicleId, vehicleTimestamp) {
  let until, since;
  if (vehicleTimestamp) {
    until = new Date(vehicleTimestamp);
    since = new Date(until.getTime() - 10 * 60 * 1000);
  } else {
    until = new Date();
    since = new Date(until.getTime() - 10 * 60 * 1000);
  }
  const resp = await fetch(
    `/vehicles/${vehicleId}/history?since=${since.toISOString()}&until=${until.toISOString()}&limit=2000`,
  );
  return resp.json();
}

function addTrailOpacity(features) {
  const count = features.length;
  return features.map((f, i) => ({
    ...f,
    properties: {
      ...f.properties,
      trail_opacity: count === 1 ? 0.7 : 0.15 + (i / (count - 1)) * 0.55,
      trail_color: vehicleColor(f.properties.vehicle_type),
    },
  }));
}

function buildTrailSegments(features) {
  const segments = [];
  for (let i = 0; i < features.length - 1; i++) {
    segments.push({
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          features[i].geometry.coordinates,
          features[i + 1].geometry.coordinates,
        ],
      },
      properties: {
        seg_opacity: features[i].properties.trail_opacity,
        seg_color: features[i].properties.trail_color,
        vehicle_type: features[i].properties.vehicle_type,
        source: features[i].properties.source,
      },
    });
  }
  return segments;
}

/* ── Coverage: DOM refs ────────────────────────────── */

const btnRealtime = document.getElementById("btn-realtime");
const btnCoverage = document.getElementById("btn-coverage");
const coveragePanelEl = document.getElementById("coverage-panel");
const timeSliderEl = document.getElementById("time-slider");
const sliderLabel = document.getElementById("slider-label");

// Initialize noUiSlider with dual handles (0-1000 internal range)
noUiSlider.create(timeSliderEl, {
  start: [0, 1000],
  connect: true,
  range: { min: 0, max: 1000 },
  step: 1,
});
const coverageLoading = document.getElementById("coverage-loading");
const coverageRangeLabel = document.getElementById("coverage-range-label");
const datePickerRow = document.getElementById("date-picker-row");
const coverageDateInput = document.getElementById("coverage-date");
const timeRangePresets = document.getElementById("time-range-presets");
const btnLines = document.getElementById("btn-lines");
const btnHeatmap = document.getElementById("btn-heatmap");
const btnPlay = document.getElementById("btn-play");
const btnStop = document.getElementById("btn-stop");
const playbackSpeedSelect = document.getElementById("playback-speed");
const playbackFollowSelect = document.getElementById("playback-follow");

/* ── Stateless DOM helpers ─────────────────────────── */

function formatRangeDate(d) {
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function setPresetActive(value) {
  timeRangePresets
    .querySelectorAll("button")
    .forEach((btn) =>
      btn.classList.toggle("active", btn.dataset.hours === value),
    );
  datePickerRow.classList.toggle("visible", value === "date");
}

function showLegend(type) {
  // Source and vehicle legends are always visible
  document.getElementById("legend-sources").style.display = "";
  document.getElementById("legend-vehicles").style.display = "";
  document.getElementById("legend-heatmap").style.display =
    type === "heatmap" ? "" : "none";
}

async function initDatePickerBounds() {
  try {
    const resp = await fetch("/stats");
    const stats = await resp.json();
    if (stats.earliest) {
      coverageDateInput.min = stats.earliest.slice(0, 10);
    }
    coverageDateInput.max = new Date().toISOString().slice(0, 10);
  } catch (e) {
    // ignore
  }
}
initDatePickerBounds();

/* ── Legend toggle (pure UI, no app state) ─────────── */

const legendToggleBtn = document.getElementById("legend-toggle");
const legendBody = document.getElementById("legend-body");
legendToggleBtn.addEventListener("click", () => {
  const collapsed = legendBody.classList.toggle("collapsed");
  legendToggleBtn.classList.toggle("collapsed", collapsed);
});

/* ── PlowApp class ─────────────────────────────────── */

class PlowApp {
  constructor(plowMap) {
    this.map = plowMap;

    // Mode
    this.mode = "realtime";

    // Sources
    this.sources = {};
    this.enabledSources = new Set();

    // Last fetched vehicle data (for source fitBounds)
    this.vehicleData = null;

    // Realtime
    this.refreshInterval = null;
    this.activeVehicleId = null;
    this.activeVehicleTimestamp = null;

    // Coverage
    this.coverageData = null;
    this.deckTrips = null;
    this.coverageSince = null;
    this.coverageUntil = null;
    this.coveragePreset = "24";
    this.coverageView = "lines";

    // Playback
    this.playback = {
      playing: false,
      startVal: 0,
      endVal: 1000,
      durationMs: 15000,
      followVehicleId: null,
      startTime: null,
      animFrame: null,
      lastRenderTime: 0,
    };
  }

  /* ── Sources ─────────────────────────────────────── */

  async loadSources() {
    try {
      const resp = await fetch("/sources");
      if (!resp.ok) throw new Error("Failed to load sources");
      this.sources = await resp.json();
    } catch (err) {
      console.error("Failed to load sources:", err);
      this.sources = {};
    }

    // Enable all sources by default
    this.enabledSources = new Set(Object.keys(this.sources));

    // Build legend checkboxes
    const container = document.getElementById("legend-sources");
    container.innerHTML = "";

    const sourceKeys = Object.keys(this.sources);
    if (sourceKeys.length <= 1) return; // Don't show source toggles for single source

    const title = document.createElement("div");
    title.className = "legend-section-title";
    title.textContent = "Sources";
    container.appendChild(title);

    for (const key of sourceKeys) {
      const src = this.sources[key];

      const row = document.createElement("div");
      row.className = "legend-source-row";
      row.dataset.source = key;

      const zoomBtn = document.createElement("button");
      zoomBtn.className = "legend-zoom-btn";
      zoomBtn.title = `Zoom to ${src.display_name}`;
      zoomBtn.textContent = "\u2316"; // ⌖ position indicator
      zoomBtn.dataset.source = key;

      const label = document.createElement("label");
      label.className = "legend-row";

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      cb.className = "legend-check";

      const text = document.createTextNode(src.display_name);
      label.appendChild(text);

      // Staleness warning indicator
      const staleIcon = document.createElement("span");
      staleIcon.className = "source-stale-icon";
      staleIcon.dataset.source = key;
      staleIcon.textContent = "!";
      staleIcon.style.display = "none";
      label.appendChild(staleIcon);

      label.appendChild(cb);

      row.appendChild(zoomBtn);
      row.appendChild(label);
      container.appendChild(row);
    }

    // Initial staleness check
    this.updateSourceStaleness();

    // Also add a "Types" section title to the vehicle legend (idempotent)
    const vehicleLegend = document.getElementById("legend-vehicles");
    if (!vehicleLegend.querySelector(".legend-section-title")) {
      const typeTitle = document.createElement("div");
      typeTitle.className = "legend-section-title";
      typeTitle.textContent = "Types";
      vehicleLegend.insertBefore(typeTitle, vehicleLegend.firstChild);
    }
  }

  updateSourceStaleness() {
    const now = Date.now();
    for (const [key, src] of Object.entries(this.sources)) {
      const icon = document.querySelector(`.source-stale-icon[data-source="${key}"]`);
      if (!icon) continue;

      const lastUpdated = src.last_updated ? new Date(src.last_updated).getTime() : 0;
      const age = now - lastUpdated;

      if (!src.last_updated || age > SOURCE_STALE_MS) {
        const agoText = src.last_updated ? formatDurationAgo(age) : "never";
        icon.title = `No data received (last: ${agoText})`;
        icon.style.display = "";
      } else {
        icon.style.display = "none";
      }
    }
  }

  getSourceDisplayName(sourceKey) {
    const src = this.sources[sourceKey];
    return src ? src.display_name : sourceKey;
  }

  buildSourceFilter() {
    const allSources = Object.keys(this.sources);
    if (allSources.length <= 1) return null; // No filter needed for single source
    if (this.enabledSources.size === allSources.length) return null; // All enabled
    if (this.enabledSources.size === 0) return false; // Nothing visible

    return ["in", ["get", "source"], ["literal", [...this.enabledSources]]];
  }

  /* ── Type filtering ─────────────────────────────── */

  buildTypeFilter() {
    const checked = [];
    let otherChecked = false;
    for (const row of document.querySelectorAll(
      "#legend-vehicles .legend-row",
    )) {
      const cb = row.querySelector(".legend-check");
      if (!cb.checked) continue;
      const types = row.dataset.types;
      if (types === "__OTHER__") {
        otherChecked = true;
      } else {
        checked.push(...types.split(","));
      }
    }

    // If everything is checked, no filter needed
    if (checked.length === KNOWN_TYPES.length && otherChecked) {
      return null;
    }

    // Build a filter: include checked known types + "other" (not in KNOWN_TYPES)
    const parts = [];
    if (checked.length > 0) {
      parts.push(["in", ["get", "vehicle_type"], ["literal", checked]]);
    }
    if (otherChecked) {
      parts.push([
        "!",
        ["in", ["get", "vehicle_type"], ["literal", KNOWN_TYPES]],
      ]);
    }

    if (parts.length === 0) return false; // nothing visible
    if (parts.length === 1) return parts[0];
    return ["any", ...parts];
  }

  applyFilters() {
    const sourceFilter = this.buildSourceFilter();
    const typeFilter = this.buildTypeFilter();

    // null = show everything (no filter), false = hide everything
    let combined;
    if (sourceFilter === false || typeFilter === false) {
      combined = false;
    } else if (sourceFilter && typeFilter) {
      combined = ["all", sourceFilter, typeFilter];
    } else {
      combined = sourceFilter || typeFilter;
    }

    this.map.setTypeFilter(combined);
  }

  /* -- Playback UI locking ---------------------------------- */

  lockPlaybackUI() {
    timeSliderEl.setAttribute("disabled", true);
    timeRangePresets
      .querySelectorAll("button")
      .forEach((b) => (b.disabled = true));
    coverageDateInput.disabled = true;
    btnLines.disabled = true;
    btnHeatmap.disabled = true;
    playbackSpeedSelect.disabled = true;
    btnPlay.disabled = true;
    btnStop.disabled = false;
  }

  unlockPlaybackUI() {
    timeSliderEl.removeAttribute("disabled");
    timeRangePresets
      .querySelectorAll("button")
      .forEach((b) => (b.disabled = false));
    coverageDateInput.disabled = false;
    btnLines.disabled = false;
    btnHeatmap.disabled = false;
    playbackSpeedSelect.disabled = false;
    btnPlay.disabled = false;
    btnStop.disabled = true;
  }

  /* -- Playback -------------------------------------------- */

  startPlayback() {
    if (!this.coverageData || this.playback.playing) return;

    const vals = timeSliderEl.noUiSlider.get().map(Number);
    this.playback.startVal = vals[0];
    this.playback.endVal = vals[1];

    // Compute duration
    const speedVal = playbackSpeedSelect.value;
    if (speedVal === "realtime") {
      const rangeMs =
        this.coverageUntil.getTime() - this.coverageSince.getTime();
      const fraction = (this.playback.endVal - this.playback.startVal) / 1000;
      this.playback.durationMs = rangeMs * fraction;
    } else {
      this.playback.durationMs = parseInt(speedVal) * 1000;
    }

    // Set right handle to start (empty view)
    timeSliderEl.noUiSlider.set([
      this.playback.startVal,
      this.playback.startVal,
    ]);

    this.playback.playing = true;
    this.playback.startTime = Date.now();
    this.playback.lastRenderTime = 0;
    this.lockPlaybackUI();
    this.playbackTick();
  }

  stopPlayback() {
    this.playback.playing = false;
    if (this.playback.animFrame) {
      cancelAnimationFrame(this.playback.animFrame);
      this.playback.animFrame = null;
    }
    this.unlockPlaybackUI();
    // Force a final unthrottled render so the last frame is accurate
    const vals = timeSliderEl.noUiSlider.get().map(Number);
    this.renderCoverage(vals[0], vals[1]);
  }

  playbackTick() {
    if (!this.playback.playing) return;

    const elapsed = Date.now() - this.playback.startTime;
    const progress = Math.min(elapsed / this.playback.durationMs, 1);
    const currentVal =
      this.playback.startVal +
      progress * (this.playback.endVal - this.playback.startVal);

    timeSliderEl.noUiSlider.set([this.playback.startVal, currentVal]);

    // Follow vehicle
    if (this.playback.followVehicleId) {
      const time = this.sliderToTime(currentVal);
      const pos = this.interpolateVehiclePosition(
        this.playback.followVehicleId,
        time,
      );
      if (pos) {
        this.map.map.easeTo({ center: pos, duration: 300 });
      }
    }

    if (progress >= 1) {
      this.stopPlayback();
      return;
    }

    this.playback.animFrame = requestAnimationFrame(() => this.playbackTick());
  }

  /* -- Follow vehicle -------------------------------------- */

  populateFollowDropdown() {
    const select = playbackFollowSelect;
    const currentVal = select.value;
    select.innerHTML = '<option value="">None</option>';

    if (!this.coverageData) return;

    const seen = new Map();
    for (const f of this.coverageData.features) {
      const vid = f.properties.vehicle_id;
      if (seen.has(vid)) continue;
      if (!this.isTypeVisible(f.properties.vehicle_type)) continue;
      if (!this.isSourceVisible(f.properties.source)) continue;
      seen.set(vid, f.properties.description);
    }

    const sorted = [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
    for (const [vid, desc] of sorted) {
      const opt = document.createElement("option");
      opt.value = vid;
      opt.textContent = desc;
      select.appendChild(opt);
    }

    // Restore selection if still valid
    if ([...select.options].some((o) => o.value === currentVal)) {
      select.value = currentVal;
    } else {
      select.value = "";
      this.playback.followVehicleId = null;
    }
  }

  isSourceVisible(source) {
    const allSources = Object.keys(this.sources);
    if (allSources.length <= 1) return true;
    return this.enabledSources.has(source);
  }

  isTypeVisible(vehicleType) {
    for (const row of document.querySelectorAll(
      "#legend-vehicles .legend-row",
    )) {
      const cb = row.querySelector(".legend-check");
      if (!cb.checked) continue;
      const types = row.dataset.types;
      if (types === "__OTHER__") {
        if (!KNOWN_TYPES.includes(vehicleType)) return true;
      } else if (types.split(",").includes(vehicleType)) {
        return true;
      }
    }
    return false;
  }

  interpolateVehiclePosition(vehicleId, time) {
    if (!this.coverageData) return null;
    const timeMs = time.getTime();
    let bestPos = null;

    for (const feature of this.coverageData.features) {
      if (feature.properties.vehicle_id !== vehicleId) continue;
      const coords = feature.geometry.coordinates;
      const epochMs = feature.properties._epochMs;

      for (let i = 0; i < epochMs.length - 1; i++) {
        const t0 = epochMs[i];
        const t1 = epochMs[i + 1];
        if (timeMs >= t0 && timeMs <= t1) {
          const frac = (timeMs - t0) / (t1 - t0);
          return [
            coords[i][0] + frac * (coords[i + 1][0] - coords[i][0]),
            coords[i][1] + frac * (coords[i + 1][1] - coords[i][1]),
          ];
        }
        if (t0 <= timeMs) bestPos = coords[i];
        if (t1 <= timeMs) bestPos = coords[i + 1];
      }
    }
    return bestPos;
  }

  /* ── Mode switching ────────────────────────────── */

  async switchMode(mode) {
    if (mode === this.mode) return;
    gtag("event", "mode_switch", { mode });
    this.mode = mode;
    btnRealtime.classList.toggle("active", mode === "realtime");
    btnCoverage.classList.toggle("active", mode === "coverage");
    if (mode === "realtime") {
      this.enterRealtime();
    } else {
      await this.enterCoverage();
    }
  }

  enterRealtime() {
    this.stopPlayback();
    this.map.abortCoverage();
    this.map.clearCoverage();
    coveragePanelEl.style.display = "none";
    this.coverageData = null;
    this.deckTrips = null;
    this.map.setVehiclesVisible(true);
    this.map.setMiniTrailsVisible(true);
    document.getElementById("vehicle-count").style.display = "";
    document.getElementById("db-size").style.display = "none";
    vehicleHint.style.display = "";
    showLegend("vehicles");
    this.startAutoRefresh();
  }

  async enterCoverage() {
    this.stopAutoRefresh();
    this.closeDetail();
    this.coverageView = "lines";
    btnLines.classList.add("active");
    btnHeatmap.classList.remove("active");
    showLegend("vehicles");
    this.map.setVehiclesVisible(false);
    this.map.setMiniTrailsVisible(false);
    document.getElementById("vehicle-count").style.display = "none";
    document.getElementById("db-size").style.display = "";
    vehicleHint.style.display = "none";
    coveragePanelEl.style.display = "block";
    btnPlay.disabled = true;

    this.coveragePreset = "24";
    setPresetActive("24");
    const now = new Date();
    await this.loadCoverageForRange(new Date(now.getTime() - ONE_DAY_MS), now);
  }

  /* ── Coverage ──────────────────────────────────── */

  async loadCoverageForRange(since, until) {
    this.stopPlayback();
    const signal = this.map.newCoverageSignal();

    // Round to 5-minute boundaries so repeat loads hit the backend cache
    since = floorTo5Min(since);
    until = floorTo5Min(until);

    this.coverageSince = since;
    this.coverageUntil = until;
    this.updateRangeLabel();
    coverageLoading.style.display = "block";
    timeSliderEl.noUiSlider.set([0, 1000]);
    this.map.clearCoverage();
    try {
      const resp = await fetch(
        `/coverage?since=${since.toISOString()}&until=${until.toISOString()}`,
        { signal },
      );
      this.coverageData = await resp.json();
      // Pre-parse timestamp strings to epoch ms (once, not per frame)
      const baseTime = since.getTime();
      for (const feature of this.coverageData.features) {
        feature.properties._epochMs = feature.properties.timestamps.map(
          (t) => new Date(t).getTime()
        );
      }
      // Transform to deck.gl trip format with float32-safe timestamp offsets
      this.deckTrips = this.coverageData.features.map((f) => ({
        path: f.geometry.coordinates,
        timestamps: f.properties._epochMs.map((t) => t - baseTime),
        color: vehicleColorRGB(f.properties.vehicle_type),
        vehicleType: f.properties.vehicle_type,
        source: f.properties.source,
        vehicleId: f.properties.vehicle_id,
      }));
    } catch (err) {
      if (err.name === "AbortError") return;
      throw err;
    }
    coverageLoading.style.display = "none";
    this.renderCoverage(0, 1000);
    this.applyFilters();
    this.populateFollowDropdown();
    btnPlay.disabled = false;
  }

  async loadCoverageForDate(dateStr) {
    const start = new Date(dateStr + "T00:00:00");
    // Use next day midnight so the 5-min floor still covers the full day
    const nextDay = new Date(start);
    nextDay.setDate(nextDay.getDate() + 1);
    await this.loadCoverageForRange(start, nextDay);
  }

  switchCoverageView(view) {
    if (view === this.coverageView) return;
    gtag("event", "coverage_view", { view });
    this.coverageView = view;
    btnLines.classList.toggle("active", view === "lines");
    btnHeatmap.classList.toggle("active", view === "heatmap");
    showLegend(view === "heatmap" ? "heatmap" : "vehicles");
    const vals = timeSliderEl.noUiSlider.get().map(Number);
    this.renderCoverage(vals[0], vals[1]);
    this.applyFilters();
  }

  renderCoverage(fromVal, toVal, throttle = false) {
    if (!this.coverageData || this.mode !== "coverage") return;
    if (throttle) {
      const now = Date.now();
      if (now - this.playback.lastRenderTime < 100) return;
      this.playback.lastRenderTime = now;
    }
    const fromTime = this.sliderToTime(fromVal);
    const toTime = this.sliderToTime(toVal);
    sliderLabel.innerHTML =
      "<span>" +
      formatTimestamp(fromTime.toISOString()) +
      "</span>" +
      "<span>" +
      formatTimestamp(toTime.toISOString()) +
      "</span>";

    if (this.coverageView === "lines") {
      this.renderCoverageLines(fromTime, toTime);
    } else {
      this.renderHeatmap(fromTime, toTime);
    }
  }

  renderCoverageLines(fromTime, toTime) {
    if (!this.deckTrips) return;
    const fromMs = fromTime.getTime();
    const toMs = toTime.getTime();
    const baseTime = this.coverageSince.getTime();
    const fromOffset = fromMs - baseTime;
    const toOffset = toMs - baseTime;
    const zoom = plowMap.getZoom();

    // Filter trips by source zoom visibility and active filters
    const visibleTrips = this.deckTrips.filter((t) => {
      const srcConfig = this.sources[t.source];
      if (srcConfig && zoom < srcConfig.min_coverage_zoom) return false;
      if (!this.isSourceVisible(t.source)) return false;
      if (!this.isTypeVisible(t.vehicleType)) return false;
      return true;
    });

    this.map.setDeckLayers([
      new deck.TripsLayer({
        id: "coverage-trips",
        data: visibleTrips,
        getPath: (d) => d.path,
        getTimestamps: (d) => d.timestamps,
        getColor: (d) => d.color,
        currentTime: toOffset,
        trailLength: toOffset - fromOffset,
        fadeTrail: true,
        widthMinPixels: 4,
        capRounded: true,
        jointRounded: true,
        shadowEnabled: false,
      }),
    ]);
  }

  renderHeatmap(fromTime, toTime) {
    if (!this.deckTrips) return;
    const baseTime = this.coverageSince.getTime();
    const fromOffset = fromTime.getTime() - baseTime;
    const toOffset = toTime.getTime() - baseTime;
    const zoom = plowMap.getZoom();

    const points = [];
    for (const trip of this.deckTrips) {
      const srcConfig = this.sources[trip.source];
      if (srcConfig && zoom < srcConfig.min_coverage_zoom) continue;
      if (!this.isSourceVisible(trip.source)) continue;
      if (!this.isTypeVisible(trip.vehicleType)) continue;
      for (let i = 0; i < trip.path.length; i++) {
        const t = trip.timestamps[i];
        if (t < fromOffset) continue;
        if (t > toOffset) break;
        points.push(trip.path[i]);
      }
    }

    this.map.setDeckLayers([
      new deck.HeatmapLayer({
        id: "coverage-heatmap",
        data: points,
        getPosition: (d) => d,
        getWeight: 1,
        radiusPixels: 30,
        intensity: 1.2,
        threshold: 0.03,
        colorRange: [
          [37, 99, 235],
          [96, 165, 250],
          [251, 191, 36],
          [249, 115, 22],
          [239, 68, 68],
        ],
        weightsTextureSize: 512,
        debounceTimeout: 100,
      }),
    ]);
  }

  sliderToTime(val) {
    const range = this.coverageUntil.getTime() - this.coverageSince.getTime();
    return new Date(this.coverageSince.getTime() + (val / 1000) * range);
  }

  /** Convert slider value (0-1000) to ms offset from coverageSince. */
  sliderToOffsetMs(val) {
    const range = this.coverageUntil.getTime() - this.coverageSince.getTime();
    return (val / 1000) * range;
  }

  updateRangeLabel() {
    if (this.coverageSince && this.coverageUntil) {
      coverageRangeLabel.textContent =
        formatRangeDate(this.coverageSince) +
        " \u2192 " +
        formatRangeDate(this.coverageUntil);
    }
  }

  /* ── Auto-refresh ──────────────────────────────── */

  startAutoRefresh() {
    if (this.refreshInterval) return;
    this._sourceRefreshCounter = 0;
    this.refreshInterval = setInterval(async () => {
      if (this.mode !== "realtime") return;
      try {
        const rawData = await fetchVehicles();
        const freshData = filterRecentFeatures(rawData);
        this.vehicleData = freshData;
        this.map.updateVehicles(freshData);
        this.map.updateMiniTrails(buildMiniTrails(freshData));
        updateVehicleCount(freshData);
        this.updateDetailFromData(freshData);
        this.refreshTrail();
      } catch (err) {
        console.error("Failed to refresh vehicles:", err);
      }

      // Re-fetch sources every ~60s (10 ticks * 6s) to update staleness info
      this._sourceRefreshCounter = (this._sourceRefreshCounter || 0) + 1;
      if (this._sourceRefreshCounter >= 10) {
        this._sourceRefreshCounter = 0;
        try {
          const resp = await fetch("/sources");
          if (resp.ok) {
            this.sources = await resp.json();
          }
        } catch (_) { /* ignore */ }
      }
      this.updateSourceStaleness();
    }, 6000);
  }

  stopAutoRefresh() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }

  /* ── Vehicle detail ────────────────────────────── */

  showDetail(p) {
    detailName.textContent = p.description;
    detailType.textContent = p.vehicle_type;
    detailSpeed.textContent = p.speed != null ? "Speed: " + p.speed + " km/h" : "Speed: N/A";
    detailBearing.textContent = p.bearing != null ? "Bearing: " + p.bearing + "\u00B0" : "Bearing: N/A";
    detailUpdated.textContent = "Updated: " + formatTimestamp(p.timestamp);
    detailSource.textContent = "Source: " + this.getSourceDisplayName(p.source);
    vehicleHint.style.display = "none";
    detailPanel.style.display = "block";
  }

  closeDetail() {
    detailPanel.style.display = "none";
    vehicleHint.style.display = "";
    this.activeVehicleId = null;
    this.activeVehicleTimestamp = null;
    this.map.clearTrail();
  }

  updateDetailFromData(data) {
    if (!this.activeVehicleId) return;
    const feature = data.features.find(
      (f) => f.properties.vehicle_id === this.activeVehicleId,
    );
    if (!feature) {
      this.closeDetail();
      return;
    }
    this.activeVehicleTimestamp = feature.properties.timestamp;
    this.showDetail(feature.properties);
  }

  async showTrail(vehicleId, vehicleTimestamp) {
    const data = await fetchTrail(vehicleId, vehicleTimestamp);
    if (!data.features || data.features.length === 0) return;

    const features = addTrailOpacity(data.features);
    const trailData = { type: "FeatureCollection", features };
    const lineData = {
      type: "FeatureCollection",
      features: buildTrailSegments(features),
    };

    this.map.showTrail(trailData, lineData);
    this.applyFilters();
  }

  async refreshTrail() {
    if (!this.activeVehicleId) return;
    const data = await fetchTrail(
      this.activeVehicleId,
      this.activeVehicleTimestamp,
    );
    if (!data.features || data.features.length === 0) return;

    const features = addTrailOpacity(data.features);

    this.map.updateTrail(
      { type: "FeatureCollection", features },
      { type: "FeatureCollection", features: buildTrailSegments(features) },
    );
  }
}

/* ── App init & event wiring ───────────────────────── */

const app = new PlowApp(plowMap);

// Mode
btnRealtime.addEventListener("click", () => app.switchMode("realtime"));
btnCoverage.addEventListener("click", () => app.switchMode("coverage"));

// Coverage presets
timeRangePresets.addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const value = btn.dataset.hours;
  gtag("event", "coverage_preset", { preset: value });
  app.coveragePreset = value;
  setPresetActive(value);
  if (value === "date") {
    if (coverageDateInput.value)
      await app.loadCoverageForDate(coverageDateInput.value);
    return;
  }
  const hours = parseInt(value);
  const now = new Date();
  await app.loadCoverageForRange(
    new Date(now.getTime() - hours * 60 * 60 * 1000),
    now,
  );
});

coverageDateInput.addEventListener("change", async () => {
  if (app.coveragePreset === "date" && coverageDateInput.value) {
    gtag("event", "coverage_date_pick", { date: coverageDateInput.value });
    await app.loadCoverageForDate(coverageDateInput.value);
  }
});

// Coverage view
btnLines.addEventListener("click", () => app.switchCoverageView("lines"));
btnHeatmap.addEventListener("click", () => app.switchCoverageView("heatmap"));

// Slider
timeSliderEl.noUiSlider.on("update", () => {
  const vals = timeSliderEl.noUiSlider.get().map(Number);
  const throttle = app.playback.playing && app.coverageView === "heatmap";
  app.renderCoverage(vals[0], vals[1], throttle);
});

// Legend source checkboxes
document.getElementById("legend-sources").addEventListener("change", (e) => {
  const row = e.target.closest(".legend-source-row");
  if (!row) return;
  const sourceKey = row.dataset.source;
  if (e.target.checked) {
    app.enabledSources.add(sourceKey);
  } else {
    app.enabledSources.delete(sourceKey);
  }
  app.applyFilters();
  app.populateFollowDropdown();
  if (app.mode === "coverage") {
    const vals = timeSliderEl.noUiSlider.get().map(Number);
    app.renderCoverage(vals[0], vals[1]);
  }
});

// Legend source zoom buttons
document.getElementById("legend-sources").addEventListener("click", (e) => {
  const btn = e.target.closest(".legend-zoom-btn");
  if (!btn) return;
  const sourceKey = btn.dataset.source;

  // Fit to the source's vehicle positions, fall back to default view
  if (app.vehicleData) {
    const features = app.vehicleData.features.filter(
      (f) => f.properties && f.properties.source === sourceKey
    );
    if (features.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      for (const f of features) bounds.extend(f.geometry.coordinates);
      plowMap.map.fitBounds(bounds, { padding: 50, maxZoom: 13 });
      return;
    }
  }
  // No vehicles — fly to source's default center/zoom
  if (app.sources[sourceKey]) {
    const src = app.sources[sourceKey];
    plowMap.map.flyTo({ center: src.center, zoom: src.zoom });
  }
});

// Legend type checkboxes
document.getElementById("legend-vehicles").addEventListener("change", () => {
  app.applyFilters();
  app.populateFollowDropdown();
  if (app.mode === "coverage") {
    const vals = timeSliderEl.noUiSlider.get().map(Number);
    app.renderCoverage(vals[0], vals[1]);
  }
});

// Playback controls
btnPlay.addEventListener("click", () => app.startPlayback());
btnStop.addEventListener("click", () => app.stopPlayback());
playbackFollowSelect.addEventListener("change", () => {
  app.playback.followVehicleId = playbackFollowSelect.value || null;
});

// Detail close
document
  .getElementById("detail-close")
  .addEventListener("click", () => app.closeDetail());

/* ── Map load: sources, layers, handlers ───────────── */

function updateMapStyleButtons() {
  const dark = isMapDark();
  const lightBtn = document.getElementById("btn-map-light");
  const darkBtn = document.getElementById("btn-map-dark");
  if (lightBtn) lightBtn.classList.toggle("active", !dark);
  if (darkBtn) darkBtn.classList.toggle("active", dark);
}

async function initMapLayersAfterStyleLoad(reAddGeolocate = false) {
  plowMap.deckOverlay = new deck.MapboxOverlay({ layers: [] });
  plowMap.map.addControl(plowMap.deckOverlay);

  if (reAddGeolocate) {
    plowMap.map.addControl(geolocate, "bottom-right");
  }

  await app.loadSources();

  const rawData = await fetchVehicles();
  const data = filterRecentFeatures(rawData);
  app.vehicleData = data;
  updateVehicleCount(data);

  plowMap.initVehicles(data);
  plowMap.initMiniTrails(buildMiniTrails(data));

  plowMap.on("mouseenter", "vehicle-circles", () => {
    plowMap.getCanvas().style.cursor = "pointer";
  });
  plowMap.on("mouseleave", "vehicle-circles", () => {
    plowMap.getCanvas().style.cursor = "";
  });

  plowMap.on("click", "vehicle-circles", async (e) => {
    const feature = e.features[0];
    const p = feature.properties;
    gtag("event", "vehicle_click", {
      vehicle_type: p.vehicle_type,
      vehicle_id: p.vehicle_id,
    });

    app.activeVehicleId = p.vehicle_id;
    app.activeVehicleTimestamp = p.timestamp;
    app.showDetail(p);
    await app.showTrail(p.vehicle_id, p.timestamp);
  });

  if (app.mode === "realtime") {
    app.startAutoRefresh();
  }

  if (app.mode === "coverage" && app.coverageData) {
    const vals = timeSliderEl.noUiSlider.get().map(Number);
    app.renderCoverage(vals[0], vals[1]);
  }

  if (app.activeVehicleId) {
    await app.showTrail(app.activeVehicleId, app.activeVehicleTimestamp);
  }
}

async function switchMapStyle(dark) {
  localStorage.setItem(MAP_STYLE_KEY, dark ? "dark" : "light");
  updateMapStyleButtons();

  const styleUrl = dark ? DARK_STYLE : LIGHT_STYLE;
  await plowMap.map.setStyle(styleUrl);
  await initMapLayersAfterStyleLoad(true); // re-add geolocate (setStyle removes it)
}

plowMap.on("load", async () => {
  updateMapStyleButtons();
  await initMapLayersAfterStyleLoad();
});

const btnMapLight = document.getElementById("btn-map-light");
const btnMapDark = document.getElementById("btn-map-dark");
if (btnMapLight) {
  btnMapLight.addEventListener("click", (e) => {
    e.preventDefault();
    if (!isMapDark()) return;
    if (typeof gtag === "function") gtag("event", "map_style", { style: "light" });
    switchMapStyle(false);
  });
}
if (btnMapDark) {
  btnMapDark.addEventListener("click", (e) => {
    e.preventDefault();
    if (isMapDark()) return;
    if (typeof gtag === "function") gtag("event", "map_style", { style: "dark" });
    switchMapStyle(true);
  });
}
