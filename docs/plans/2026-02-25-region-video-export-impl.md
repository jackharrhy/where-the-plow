# Region Video Export Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users draw a polygon on the map, select a multi-day date range, and export an MP4 video of the plow playback within that region, or copy a shareable link that replays the same view in-browser.

**Architecture:** Extends the existing `/coverage` endpoint with spatial filtering (bbox param, DuckDB `ST_Intersects`). Frontend adds Mapbox Draw for polygon selection, Mediabunny for MP4 encoding from the MapLibre canvas, and URL-param-based replay mode. All new frontend code lives in the existing `app.js` / `index.html` / `style.css` files. No build step.

**Tech Stack:** Python/FastAPI, DuckDB spatial, MapLibre GL JS v5, `@mapbox/mapbox-gl-draw` via CDN, Mediabunny via CDN, deck.gl TripsLayer (existing), vanilla JS.

---

### Task 1: Add `bbox` parameter to `/coverage` backend endpoint

Add optional spatial filtering to the existing `/coverage` route and `get_coverage_trails()` DB method. This is the foundation for all region-based queries.

**Files:**
- Modify: `src/where_the_plow/db.py:276-354` (`get_coverage_trails`)
- Modify: `src/where_the_plow/routes.py:351-400` (`get_coverage`)
- Test: `tests/test_db.py`
- Test: `tests/test_routes.py`

**Step 1: Write failing DB test for bbox filtering**

Add to `tests/test_db.py`:

```python
def test_get_coverage_trails_bbox_filter():
    """Bbox filter should only return positions within the bounding box."""
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 30, tzinfo=timezone.utc)
    ts3 = datetime(2026, 2, 19, 12, 1, 0, tzinfo=timezone.utc)

    db.upsert_vehicles(
        [
            {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "SA PLOW TRUCK"},
            {"vehicle_id": "v2", "description": "Plow 2", "vehicle_type": "LOADER"},
        ],
        now,
    )
    # v1 in downtown area (-52.73, 47.56) to (-52.75, 47.58)
    # v2 far away at (-53.00, 47.30)
    db.insert_positions(
        [
            {"vehicle_id": "v1", "timestamp": ts1, "longitude": -52.73, "latitude": 47.56, "bearing": 0, "speed": 10.0, "is_driving": "maybe"},
            {"vehicle_id": "v1", "timestamp": ts2, "longitude": -52.74, "latitude": 47.57, "bearing": 90, "speed": 15.0, "is_driving": "maybe"},
            {"vehicle_id": "v1", "timestamp": ts3, "longitude": -52.75, "latitude": 47.58, "bearing": 180, "speed": 20.0, "is_driving": "maybe"},
            {"vehicle_id": "v2", "timestamp": ts1, "longitude": -53.00, "latitude": 47.30, "bearing": 0, "speed": 5.0, "is_driving": "maybe"},
            {"vehicle_id": "v2", "timestamp": ts2, "longitude": -53.01, "latitude": 47.31, "bearing": 0, "speed": 5.0, "is_driving": "maybe"},
            {"vehicle_id": "v2", "timestamp": ts3, "longitude": -53.02, "latitude": 47.32, "bearing": 0, "speed": 5.0, "is_driving": "maybe"},
        ],
        now,
    )

    # Bbox around downtown — should include v1, exclude v2
    trails = db.get_coverage_trails(
        since=ts1, until=ts3, bbox=(-52.80, 47.50, -52.70, 47.60)
    )
    assert len(trails) == 1
    assert trails[0]["vehicle_id"] == "v1"

    # Bbox around v2's area — should include v2, exclude v1
    trails = db.get_coverage_trails(
        since=ts1, until=ts3, bbox=(-53.10, 47.25, -52.95, 47.35)
    )
    assert len(trails) == 1
    assert trails[0]["vehicle_id"] == "v2"

    # Bbox that includes neither
    trails = db.get_coverage_trails(
        since=ts1, until=ts3, bbox=(-50.00, 48.00, -49.00, 49.00)
    )
    assert len(trails) == 0

    # No bbox — returns both vehicles
    trails = db.get_coverage_trails(since=ts1, until=ts3)
    assert len(trails) == 2

    db.close()
    os.unlink(path)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_get_coverage_trails_bbox_filter -v`
Expected: FAIL with `TypeError: get_coverage_trails() got an unexpected keyword argument 'bbox'`

**Step 3: Implement bbox filtering in `get_coverage_trails()`**

In `src/where_the_plow/db.py`, modify the `get_coverage_trails` method signature and query. Add `bbox` parameter as `tuple[float, float, float, float] | None = None` (west, south, east, north).

Add after the source filter block (line 292):

```python
bbox_filter = ""
if bbox is not None:
    west, south, east, north = bbox
    bbox_filter = f"AND ST_Intersects(p.geom, ST_MakeEnvelope(${len(params)+1}, ${len(params)+2}, ${len(params)+3}, ${len(params)+4}))"
    params.extend([west, south, east, north])
```

Insert `{bbox_filter}` into the query's WHERE clause after `{source_filter}` (line 310).

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py::test_get_coverage_trails_bbox_filter -v`
Expected: PASS

**Step 5: Write failing route test for bbox query param**

Add to `tests/test_routes.py`:

```python
def test_get_coverage_with_bbox_filter(test_client):
    # v1 positions are around (-52.73 to -52.75, 47.56 to 47.58)
    # v2 position is at (-52.80, 47.50) — only 1 position so no trail
    # Bbox around v1 — should return v1's trail
    resp = test_client.get(
        "/coverage?since=2026-02-19T00:00:00Z&until=2026-02-20T00:00:00Z"
        "&bbox=-52.80,47.50,-52.70,47.60"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["vehicle_id"] == "v1"

    # Bbox far away — should return empty
    resp = test_client.get(
        "/coverage?since=2026-02-19T00:00:00Z&until=2026-02-20T00:00:00Z"
        "&bbox=-50.00,48.00,-49.00,49.00"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["features"]) == 0
```

**Step 6: Implement bbox query param in route**

In `src/where_the_plow/routes.py`, add to the `get_coverage` function signature:

```python
bbox: str | None = Query(
    None,
    description="Bounding box filter: west,south,east,north (e.g. '-52.8,47.5,-52.7,47.6')",
),
```

Parse it into a tuple before passing to `db.get_coverage_trails()`:

```python
bbox_tuple = None
if bbox is not None:
    try:
        parts = [float(x) for x in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        bbox_tuple = tuple(parts)
    except ValueError:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=422,
            content={"detail": "bbox must be 4 comma-separated floats: west,south,east,north"},
        )
```

Pass `bbox=bbox_tuple` to `db.get_coverage_trails(...)`.

Update cache key logic: include bbox in both in-memory and file cache keys. For in-memory cache, change the key to `(since_iso, until_iso, source, bbox)`. For the file cache, modify `cache._cache_key` to accept an optional `bbox_str` parameter and include it in the hash.

**Step 7: Run all tests**

Run: `uv run pytest tests/test_routes.py tests/test_db.py -v`
Expected: All PASS

**Step 8: Commit**

```bash
git add src/where_the_plow/db.py src/where_the_plow/routes.py src/where_the_plow/cache.py tests/test_db.py tests/test_routes.py
git commit -m "feat: add bbox spatial filter to /coverage endpoint (#29)"
```

---

### Task 2: Add Mapbox Draw CDN and export UI panel HTML/CSS

Add the Mapbox Draw library, create the export UI panel in the HTML, and style it. No JS logic yet — just the static structure.

**Files:**
- Modify: `src/where_the_plow/static/index.html:72-74` (CDN scripts), `113-161` (coverage panel)
- Modify: `src/where_the_plow/static/style.css`

**Step 1: Add Mapbox Draw CDN links**

In `index.html`, add after the noUiSlider CSS link (line 69-70):

```html
<link rel="stylesheet" href="https://unpkg.com/@mapbox/mapbox-gl-draw@1/dist/mapbox-gl-draw.css" />
```

Add after the noUiSlider JS script (line 74):

```html
<script src="https://unpkg.com/@mapbox/mapbox-gl-draw@1/dist/mapbox-gl-draw.js"></script>
```

**Step 2: Add Mediabunny CDN script**

Add after the Mapbox Draw script:

```html
<script type="module" id="mediabunny-loader">
    import { Output, Mp4OutputFormat, BufferTarget, CanvasSource } from 'https://esm.sh/mediabunny@0';
    window.Mediabunny = { Output, Mp4OutputFormat, BufferTarget, CanvasSource };
    window.dispatchEvent(new Event('mediabunny-ready'));
</script>
```

Note: Mediabunny is ESM-only, so we use an inline module script that imports from esm.sh and exposes the needed classes on `window.Mediabunny`. The `mediabunny-ready` event lets `app.js` (which is a classic script) know when it's available.

**Step 3: Add export panel HTML**

In `index.html`, add inside the `#coverage-panel` div, after the `#coverage-loading` div (line 160), before the closing `</div>` of `#coverage-panel`:

```html
<div id="export-panel" style="display: none">
    <div class="coverage-hint export-section-title">
        Export Region Video
    </div>
    <div id="export-draw-controls" class="export-row">
        <button id="btn-draw-polygon" title="Draw polygon">Polygon</button>
        <button id="btn-draw-rectangle" title="Draw rectangle">Rectangle</button>
        <button id="btn-draw-clear" title="Clear drawing" disabled>Clear</button>
    </div>
    <div id="export-date-range" class="export-row">
        <label>From</label>
        <input type="date" id="export-date-start" />
        <label>To</label>
        <input type="date" id="export-date-end" />
    </div>
    <div id="export-speed-row" class="export-row">
        <label>Video duration</label>
        <select id="export-speed">
            <option value="15">15s</option>
            <option value="30" selected>30s</option>
            <option value="60">1m</option>
        </select>
    </div>
    <div id="export-actions" class="export-row">
        <button id="btn-export-preview" disabled>Preview</button>
        <button id="btn-export-record" disabled>Export MP4</button>
        <button id="btn-export-link" disabled>Copy Link</button>
    </div>
    <div id="export-progress" style="display: none">
        <div id="export-progress-bar">
            <div id="export-progress-fill"></div>
        </div>
        <span id="export-progress-text">Encoding...</span>
        <button id="btn-export-cancel">Cancel</button>
    </div>
    <div id="export-unsupported" style="display: none">
        Video export requires a Chromium-based browser (Chrome, Edge) or Safari 16.4+.
    </div>
</div>
```

**Step 4: Add entry button for export mode**

In `index.html`, add a button after the `#coverage-view-toggle` div (line 133):

```html
<button id="btn-export-mode" class="export-toggle-btn" style="display: none">Export Region</button>
```

This button is hidden by default, shown when in coverage mode.

**Step 5: Style the export panel**

Add to `style.css` after the existing coverage panel styles (around line 369):

```css
/* ── Export panel ───────────────────────────────── */

.export-toggle-btn {
    width: 100%;
    padding: 6px 10px;
    margin: 6px 0;
    background: var(--color-accent);
    color: #fff;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.8rem;
}
.export-toggle-btn:hover {
    opacity: 0.9;
}

#export-panel {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--border-subtle);
}

.export-section-title {
    font-weight: 600;
    margin-bottom: 6px;
}

.export-row {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
    flex-wrap: wrap;
}

.export-row label {
    font-size: 0.75rem;
    color: var(--color-text-secondary);
    white-space: nowrap;
}

.export-row input[type="date"] {
    flex: 1;
    min-width: 0;
    background: var(--color-input-bg);
    color: var(--color-text);
    border: 1px solid var(--border-subtle);
    border-radius: 3px;
    padding: 3px 4px;
    font-size: 0.75rem;
}

.export-row select {
    flex: 1;
    background: var(--color-input-bg);
    color: var(--color-text);
    border: 1px solid var(--border-subtle);
    border-radius: 3px;
    padding: 3px 4px;
    font-size: 0.75rem;
}

#export-draw-controls button {
    flex: 1;
    padding: 4px 8px;
    background: var(--color-input-bg);
    color: var(--color-text);
    border: 1px solid var(--border-subtle);
    border-radius: 3px;
    cursor: pointer;
    font-size: 0.75rem;
}
#export-draw-controls button:hover:not(:disabled) {
    background: var(--color-hover-bg);
}
#export-draw-controls button:disabled {
    opacity: 0.4;
    cursor: default;
}

#export-actions button {
    flex: 1;
    padding: 5px 8px;
    border: 1px solid var(--border-subtle);
    border-radius: 3px;
    cursor: pointer;
    font-size: 0.75rem;
    background: var(--color-input-bg);
    color: var(--color-text);
}
#export-actions button:disabled {
    opacity: 0.4;
    cursor: default;
}
#btn-export-record {
    background: var(--color-accent);
    color: #fff;
    border-color: var(--color-accent);
}
#btn-export-record:disabled {
    background: var(--color-input-bg);
    color: var(--color-text);
    border-color: var(--border-subtle);
}

#export-progress {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
}
#export-progress-bar {
    flex: 1;
    height: 6px;
    background: var(--color-input-bg);
    border-radius: 3px;
    overflow: hidden;
}
#export-progress-fill {
    height: 100%;
    width: 0%;
    background: var(--color-accent);
    transition: width 0.2s;
}
#export-progress-text {
    font-size: 0.7rem;
    color: var(--color-text-secondary);
    white-space: nowrap;
}
#btn-export-cancel {
    padding: 2px 8px;
    background: transparent;
    color: var(--color-text-muted);
    border: 1px solid var(--border-subtle);
    border-radius: 3px;
    cursor: pointer;
    font-size: 0.7rem;
}

#export-unsupported {
    font-size: 0.75rem;
    color: var(--color-text-muted);
    padding: 4px 0;
}
```

**Step 6: Commit**

```bash
git add src/where_the_plow/static/index.html src/where_the_plow/static/style.css
git commit -m "feat: add export panel HTML/CSS and Mapbox Draw + Mediabunny CDN (#29)"
```

---

### Task 3: Wire up Mapbox Draw for region selection

Initialize Mapbox Draw, wire the draw/clear buttons, and track the drawn polygon. When a polygon is drawn + dates are selected, enable the Preview/Export/Link buttons.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Add Draw initialization in PlowMap**

In the `PlowMap` class (around line 350 in app.js), add a method to initialize and manage Mapbox Draw:

```js
initDraw() {
    this.draw = new MapboxDraw({
        displayControlsDefault: false,
        controls: {},  // We use custom buttons, not built-in controls
        defaultMode: 'simple_select',
    });
    this.map.addControl(this.draw, 'top-left');
    // Hide the default draw controls (we have our own buttons)
    const drawControls = this.map.getContainer().querySelector('.mapboxgl-ctrl-group.mapboxgl-ctrl-top-left');
    if (drawControls) drawControls.style.display = 'none';
}

getDrawnPolygon() {
    if (!this.draw) return null;
    const data = this.draw.getAll();
    if (!data || data.features.length === 0) return null;
    return data.features[0];  // Only allow one polygon at a time
}

clearDraw() {
    if (this.draw) this.draw.deleteAll();
}

getDrawnBbox() {
    const feature = this.getDrawnPolygon();
    if (!feature) return null;
    const coords = feature.geometry.coordinates[0];
    let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
    for (const [lng, lat] of coords) {
        if (lng < west) west = lng;
        if (lng > east) east = lng;
        if (lat < south) south = lat;
        if (lat > north) north = lat;
    }
    return [west, south, east, north];
}
```

**Step 2: Add export state and methods to PlowApp**

Add to the `PlowApp` constructor state:

```js
// Export
this.exportMode = false;
this.exportPolygon = null;
```

Add export mode methods to `PlowApp`:

```js
/* ── Export mode ────────────────────────────────── */

enterExportMode() {
    this.exportMode = true;
    this.map.initDraw();
    document.getElementById('export-panel').style.display = 'block';
    document.getElementById('btn-export-mode').textContent = 'Exit Export';

    // Set date picker bounds
    const startInput = document.getElementById('export-date-start');
    const endInput = document.getElementById('export-date-end');
    if (coverageDateInput.min) startInput.min = coverageDateInput.min;
    if (coverageDateInput.max) endInput.max = coverageDateInput.max;
    startInput.max = coverageDateInput.max;
    endInput.min = startInput.min;

    // Default: last 3 days
    const now = new Date();
    const threeDaysAgo = new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000);
    endInput.value = now.toISOString().slice(0, 10);
    startInput.value = threeDaysAgo.toISOString().slice(0, 10);

    // Check WebCodecs support
    if (typeof VideoEncoder === 'undefined') {
        document.getElementById('export-unsupported').style.display = 'block';
        document.getElementById('btn-export-record').disabled = true;
    }

    this.updateExportButtons();
}

exitExportMode() {
    this.exportMode = false;
    this.map.clearDraw();
    // Remove draw control
    if (this.map.draw) {
        this.map.map.removeControl(this.map.draw);
        this.map.draw = null;
    }
    document.getElementById('export-panel').style.display = 'none';
    document.getElementById('btn-export-mode').textContent = 'Export Region';
    document.getElementById('export-unsupported').style.display = 'none';
    this.exportPolygon = null;
}

updateExportButtons() {
    const hasPolygon = this.map.getDrawnPolygon() !== null;
    const startDate = document.getElementById('export-date-start').value;
    const endDate = document.getElementById('export-date-end').value;
    const hasDates = startDate && endDate && startDate <= endDate;
    const ready = hasPolygon && hasDates;

    document.getElementById('btn-draw-clear').disabled = !hasPolygon;
    document.getElementById('btn-export-preview').disabled = !ready;
    document.getElementById('btn-export-link').disabled = !ready;

    // Record also needs WebCodecs
    const hasWebCodecs = typeof VideoEncoder !== 'undefined';
    document.getElementById('btn-export-record').disabled = !(ready && hasWebCodecs);
}
```

**Step 3: Wire event listeners**

Add at the bottom of app.js, in the event wiring section (after line 1841):

```js
// Export mode toggle
document.getElementById('btn-export-mode').addEventListener('click', () => {
    if (app.exportMode) {
        app.exitExportMode();
    } else {
        app.enterExportMode();
    }
});

// Draw buttons
document.getElementById('btn-draw-polygon').addEventListener('click', () => {
    if (app.map.draw) app.map.draw.changeMode('draw_polygon');
});
document.getElementById('btn-draw-rectangle').addEventListener('click', () => {
    if (app.map.draw) app.map.draw.changeMode('draw_polygon');
    // MapboxDraw doesn't have a built-in rectangle mode; use draw_polygon.
    // For a true rectangle, we'd need a custom mode — polygon is fine for now.
});
document.getElementById('btn-draw-clear').addEventListener('click', () => {
    app.map.clearDraw();
    app.updateExportButtons();
});

// Date inputs update button state
document.getElementById('export-date-start').addEventListener('change', () => app.updateExportButtons());
document.getElementById('export-date-end').addEventListener('change', () => app.updateExportButtons());
```

**Step 4: Wire draw events to update state**

In the `plowMap.on('load', ...)` handler (line 1850), add after the deck.gl overlay init:

```js
// Listen for Mapbox Draw events
plowMap.on('draw.create', () => {
    // Only allow one polygon at a time
    const data = plowMap.draw?.getAll();
    if (data && data.features.length > 1) {
        const latest = data.features[data.features.length - 1];
        plowMap.draw.deleteAll();
        plowMap.draw.add(latest);
    }
    app.updateExportButtons();
});
plowMap.on('draw.update', () => app.updateExportButtons());
plowMap.on('draw.delete', () => app.updateExportButtons());
```

**Step 5: Show "Export Region" button when in coverage mode**

In the `enterCoverage()` method (line 1415), add:

```js
document.getElementById('btn-export-mode').style.display = 'block';
```

In the `enterRealtime()` method (line 1399), add:

```js
document.getElementById('btn-export-mode').style.display = 'none';
if (this.exportMode) this.exitExportMode();
```

**Step 6: Test manually** — load the app, enter coverage mode, click "Export Region", draw a polygon, verify buttons enable/disable correctly.

**Step 7: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "feat: wire Mapbox Draw for region selection in export mode (#29)"
```

---

### Task 4: Export preview — load spatially-filtered coverage and play back

Wire the "Preview" button to load coverage data filtered to the drawn bbox and play it back using the existing playback system.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Add preview method to PlowApp**

```js
async previewExport() {
    const bbox = this.map.getDrawnBbox();
    if (!bbox) return;
    const startDate = document.getElementById('export-date-start').value;
    const endDate = document.getElementById('export-date-end').value;
    if (!startDate || !endDate) return;

    const since = new Date(startDate + 'T00:00:00');
    const until = new Date(endDate + 'T23:59:59');
    const bboxParam = bbox.join(',');

    // Store bbox for the fetch
    this._exportBbox = bboxParam;

    await this.loadCoverageForRange(since, until);

    // Fit map to drawn region
    const [west, south, east, north] = bbox;
    this.map.map.fitBounds([[west, south], [east, north]], { padding: 50 });
}
```

**Step 2: Modify `loadCoverageForRange` to include bbox**

In `loadCoverageForRange()` (line 1438), modify the fetch URL to include bbox when available:

```js
let url = `/coverage?since=${since.toISOString()}&until=${until.toISOString()}`;
if (this._exportBbox) {
    url += `&bbox=${this._exportBbox}`;
}
const resp = await fetch(url, { signal });
```

**Step 3: Wire preview button**

```js
document.getElementById('btn-export-preview').addEventListener('click', () => {
    app.previewExport();
});
```

**Step 4: Test manually** — draw a region, set dates, click Preview, verify coverage loads filtered to the region and playback works.

**Step 5: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "feat: export preview loads spatially-filtered coverage (#29)"
```

---

### Task 5: Shareable link — encode/decode replay state in URL params

Add the ability to generate a shareable URL and to auto-load replay mode from URL params on page load.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Add share link generation**

Add to `PlowApp`:

```js
generateShareLink() {
    const bbox = this.map.getDrawnBbox();
    const startDate = document.getElementById('export-date-start').value;
    const endDate = document.getElementById('export-date-end').value;
    const speed = document.getElementById('export-speed').value;
    const center = this.map.map.getCenter();
    const zoom = this.map.map.getZoom().toFixed(2);

    const params = new URLSearchParams({
        mode: 'replay',
        since: startDate,
        until: endDate,
        speed: speed,
        center: `${center.lat.toFixed(4)},${center.lng.toFixed(4)}`,
        zoom: zoom,
    });
    if (bbox) {
        params.set('bbox', bbox.map(v => v.toFixed(6)).join(','));
    }
    const polygon = this.map.getDrawnPolygon();
    if (polygon) {
        params.set('polygon', JSON.stringify(polygon.geometry.coordinates[0]));
    }

    return `${window.location.origin}/?${params.toString()}`;
}
```

**Step 2: Wire "Copy Link" button**

```js
document.getElementById('btn-export-link').addEventListener('click', () => {
    const url = app.generateShareLink();
    navigator.clipboard.writeText(url).then(() => {
        const btn = document.getElementById('btn-export-link');
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = 'Copy Link'; }, 2000);
    });
});
```

**Step 3: Add replay mode initialization**

Add a function near the top of app.js (after the utility functions, before the PlowApp class):

```js
function parseReplayParams() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('mode') !== 'replay') return null;
    return {
        since: params.get('since'),
        until: params.get('until'),
        speed: params.get('speed') || '30',
        center: params.get('center'),
        zoom: params.get('zoom'),
        bbox: params.get('bbox'),
        polygon: params.get('polygon'),
    };
}
```

**Step 4: Handle replay mode on app startup**

In the `plowMap.on('load', ...)` handler (line 1850), after `app.startAutoRefresh()`, add:

```js
const replayParams = parseReplayParams();
if (replayParams) {
    // Skip welcome modal
    document.getElementById('welcome-overlay').style.display = 'none';

    // Switch to coverage mode
    await app.switchMode('coverage');

    // Set camera
    if (replayParams.center && replayParams.zoom) {
        const [lat, lng] = replayParams.center.split(',').map(Number);
        plowMap.map.jumpTo({ center: [lng, lat], zoom: parseFloat(replayParams.zoom) });
    }

    // Load coverage with bbox
    if (replayParams.since && replayParams.until) {
        const since = new Date(replayParams.since + 'T00:00:00');
        const until = new Date(replayParams.until + 'T23:59:59');
        if (replayParams.bbox) {
            app._exportBbox = replayParams.bbox;
        }
        await app.loadCoverageForRange(since, until);

        // Draw polygon outline if provided
        if (replayParams.polygon) {
            try {
                const coords = JSON.parse(replayParams.polygon);
                // Add a visual-only polygon layer
                plowMap.map.addSource('replay-polygon', {
                    type: 'geojson',
                    data: {
                        type: 'Feature',
                        geometry: { type: 'Polygon', coordinates: [coords] },
                    },
                });
                plowMap.map.addLayer({
                    id: 'replay-polygon-outline',
                    type: 'line',
                    source: 'replay-polygon',
                    paint: {
                        'line-color': '#fff',
                        'line-width': 2,
                        'line-dasharray': [3, 2],
                        'line-opacity': 0.6,
                    },
                });
            } catch (e) {
                console.warn('Failed to parse replay polygon:', e);
            }
        }

        // Set playback speed
        playbackSpeedSelect.value = replayParams.speed;

        // Auto-start playback
        app.startPlayback();
    }
}
```

**Step 5: Test manually** — generate a link, open it in a new tab, verify it loads and auto-plays.

**Step 6: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "feat: shareable replay links with URL param encoding/decoding (#29)"
```

---

### Task 6: Video recording pipeline with Mediabunny

Implement the stepped-playback recording pipeline that captures the MapLibre canvas frame-by-frame and encodes to MP4 using Mediabunny.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Add recording state and methods to PlowApp**

Add to the constructor:

```js
// Recording
this.recording = {
    active: false,
    cancelled: false,
    output: null,
    videoSource: null,
};
```

**Step 2: Implement the recording method**

Add to `PlowApp`:

```js
async startRecording() {
    if (!window.Mediabunny) {
        alert('Mediabunny not loaded yet. Please wait a moment and try again.');
        return;
    }
    if (!this.coverageData || !this.deckTrips) {
        alert('Load a preview first before recording.');
        return;
    }

    const { Output, Mp4OutputFormat, BufferTarget, CanvasSource } = window.Mediabunny;

    const mapCanvas = this.map.map.getCanvas();
    const width = mapCanvas.width;
    const height = mapCanvas.height;

    // Create compositing canvas
    const composite = document.createElement('canvas');
    composite.width = width;
    composite.height = height;
    const ctx = composite.getContext('2d');

    const videoSource = new CanvasSource(composite, {
        codec: 'avc',
        bitrate: 4_000_000,
    });

    const output = new Output({
        format: new Mp4OutputFormat(),
        target: new BufferTarget(),
    });
    output.addVideoTrack(videoSource, { frameRate: 30 });

    this.recording = { active: true, cancelled: false, output, videoSource };

    // UI
    const progressEl = document.getElementById('export-progress');
    const progressFill = document.getElementById('export-progress-fill');
    const progressText = document.getElementById('export-progress-text');
    const actionsEl = document.getElementById('export-actions');
    progressEl.style.display = 'flex';
    actionsEl.style.display = 'none';
    this.lockPlaybackUI();

    await output.start();

    const fps = 30;
    const durationSec = parseInt(document.getElementById('export-speed').value);
    const totalFrames = fps * durationSec;
    const sinceMs = this.coverageSince.getTime();
    const untilMs = this.coverageUntil.getTime();
    const rangeMs = untilMs - sinceMs;

    try {
        for (let i = 0; i < totalFrames; i++) {
            if (this.recording.cancelled) break;

            const progress = i / totalFrames;
            const currentTimeMs = sinceMs + progress * rangeMs;

            // Update slider to match
            const sliderVal = (progress * 1000);
            timeSliderEl.noUiSlider.set([0, sliderVal]);

            // Render coverage at this time
            this.renderCoverage(0, sliderVal);

            // Wait a frame for WebGL to paint
            await new Promise(r => requestAnimationFrame(r));
            // Additional wait for deck.gl async rendering
            await new Promise(r => setTimeout(r, 50));

            // Composite: map + overlay
            ctx.drawImage(mapCanvas, 0, 0);
            this._drawRecordingOverlay(ctx, width, height, new Date(currentTimeMs));

            // Feed frame to encoder
            const timestamp = i / fps;
            const duration = 1 / fps;
            videoSource.add(timestamp, duration);

            // Update progress
            const pct = Math.round(progress * 100);
            progressFill.style.width = pct + '%';
            progressText.textContent = `Encoding: ${pct}%`;
        }

        if (!this.recording.cancelled) {
            await output.finalize();

            // Download
            const blob = new Blob([output.target.buffer], { type: 'video/mp4' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'plow-coverage.mp4';
            a.click();
            URL.revokeObjectURL(url);
        } else {
            await output.cancel();
        }
    } catch (err) {
        console.error('Recording failed:', err);
        try { await output.cancel(); } catch (_) {}
        alert('Recording failed: ' + err.message);
    }

    // Restore UI
    this.recording.active = false;
    progressEl.style.display = 'none';
    actionsEl.style.display = 'flex';
    this.unlockPlaybackUI();
}

cancelRecording() {
    this.recording.cancelled = true;
}

_drawRecordingOverlay(ctx, width, height, time) {
    const fontSize = Math.max(14, Math.round(height / 40));
    ctx.font = `${fontSize}px sans-serif`;
    ctx.textBaseline = 'bottom';

    // Timestamp — bottom left
    const timeStr = time.toLocaleString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
    ctx.shadowColor = 'rgba(0,0,0,0.8)';
    ctx.shadowBlur = 4;
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'left';
    ctx.fillText(timeStr, 12, height - 12);

    // Branding — bottom right
    ctx.textAlign = 'right';
    ctx.fillText('plow.jackharrhy.dev', width - 12, height - 12);

    // Reset shadow
    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;
}
```

**Step 3: Wire recording buttons**

```js
document.getElementById('btn-export-record').addEventListener('click', () => {
    app.startRecording();
});
document.getElementById('btn-export-cancel').addEventListener('click', () => {
    app.cancelRecording();
});
```

**Step 4: Test manually** — draw a region, set dates, click Preview to load data, click "Export MP4", verify progress bar works and an MP4 file downloads. Open the MP4 in a video player to verify it's valid.

**Step 5: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "feat: MP4 video recording pipeline with Mediabunny (#29)"
```

---

### Task 7: Polish and edge cases

Clean up UX, handle edge cases, and finalize the feature.

**Files:**
- Modify: `src/where_the_plow/static/app.js`
- Modify: `src/where_the_plow/static/style.css`
- Modify: `src/where_the_plow/static/index.html`

**Step 1: Mobile guard**

In `enterExportMode()`, add a check:

```js
if (window.innerWidth < 768) {
    alert('Video export works best on desktop. Please use a larger screen.');
    return;
}
```

**Step 2: Disable map interaction during recording**

In `startRecording()`, before the frame loop:

```js
this.map.map.getContainer().style.pointerEvents = 'none';
```

In cleanup (after the loop):

```js
this.map.map.getContainer().style.pointerEvents = '';
```

**Step 3: Clear `_exportBbox` when not in export mode**

In `exitExportMode()`:

```js
this._exportBbox = null;
```

In `loadCoverageForRange()`, clear after the fetch so normal coverage loads aren't affected:

After the fetch completes (before the transform), add a comment noting that `_exportBbox` is intentionally persistent during the export flow but cleared when exiting export mode.

**Step 4: Google Analytics events**

Add `gtag` calls for key actions:

```js
gtag('event', 'export_preview', { bbox: this._exportBbox });
gtag('event', 'export_record_start');
gtag('event', 'export_record_complete', { duration_sec: durationSec, frames: totalFrames });
gtag('event', 'export_share_link');
```

**Step 5: Run all backend tests**

Run: `uv run pytest -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/where_the_plow/static/
git commit -m "feat: export polish — mobile guard, analytics, UX improvements (#29)"
```

---

### Task 8: Update README API table

Add documentation for the new `bbox` parameter on the `/coverage` endpoint.

**Files:**
- Modify: `README.md`

**Step 1: Update the API table**

Find the `/coverage` row in the API endpoint table and add the `bbox` parameter to its description.

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document bbox parameter on /coverage endpoint (#29)"
```
