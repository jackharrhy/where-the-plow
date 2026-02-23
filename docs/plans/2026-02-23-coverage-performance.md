# Coverage Rendering Performance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Dramatically improve coverage/playback rendering performance by eliminating per-frame string parsing, adding viewport-aware culling, throttling render updates, and filtering sources by zoom level.

**Architecture:** All changes are in the frontend (`app.js`) and source config (`source_config.py`, `routes.py`). Coverage data is pre-processed once on fetch (timestamps parsed to epoch ms). Render functions filter by viewport bounds and zoom-based source visibility. Playback throttles `setData()` to ~10fps instead of ~60fps. No backend query changes needed.

**Tech Stack:** Vanilla JS, MapLibre GL JS, existing Python backend (minor config additions).

---

### Task 1: Pre-parse timestamps on coverage load

The hottest loop in the codebase is `renderCoverageLines()` / `renderHeatmap()`. Both call `new Date(timestamps[i]).getTime()` on every coordinate, every frame. During playback at 60fps with 30K coordinates, that's ~1.8M string-to-Date parses per second.

**Fix:** Parse timestamps once when coverage data arrives, store as a parallel `_epochMs` array on each feature.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Add pre-parse function after coverage data loads**

In `loadCoverageForRange()` (around line 1502), after `this.coverageData = await resp.json()`, add a pre-parse step:

```js
// Pre-parse timestamp strings to epoch ms (once, not per frame)
for (const feature of this.coverageData.features) {
  feature.properties._epochMs = feature.properties.timestamps.map(
    (t) => new Date(t).getTime()
  );
}
```

**Step 2: Update `renderCoverageLines()` to use pre-parsed timestamps**

Replace (lines ~1555-1592):
```js
renderCoverageLines(fromTime, toTime) {
  const fromMs = fromTime.getTime();
  const toMs = toTime.getTime();
  const rangeMs = toMs - fromMs;

  const segmentFeatures = [];
  for (const feature of this.coverageData.features) {
    const coords = feature.geometry.coordinates;
    const epochMs = feature.properties._epochMs;
    const color = vehicleColor(feature.properties.vehicle_type);

    for (let i = 0; i < coords.length - 1; i++) {
      const tMs = epochMs[i];
      const tNextMs = epochMs[i + 1];
      if (tMs < fromMs) continue;
      if (tNextMs > toMs) break;

      const progress = rangeMs > 0 ? (tMs - fromMs) / rangeMs : 1;
      const opacity = 0.15 + progress * 0.65;

      segmentFeatures.push({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [coords[i], coords[i + 1]],
        },
        properties: {
          seg_opacity: opacity,
          seg_color: color,
          vehicle_type: feature.properties.vehicle_type,
          source: feature.properties.source,
        },
      });
    }
  }

  const data = { type: "FeatureCollection", features: segmentFeatures };
  this.map.renderCoverageLines(data);
}
```

**Step 3: Update `renderHeatmap()` to use pre-parsed timestamps**

Replace (lines ~1594-1617):
```js
renderHeatmap(fromTime, toTime) {
  if (!this.coverageData) return;
  const fromMs = fromTime.getTime();
  const toMs = toTime.getTime();

  const pointFeatures = [];
  for (const feature of this.coverageData.features) {
    const coords = feature.geometry.coordinates;
    const epochMs = feature.properties._epochMs;
    for (let i = 0; i < coords.length; i++) {
      const tMs = epochMs[i];
      if (tMs < fromMs) continue;
      if (tMs > toMs) break;
      pointFeatures.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: coords[i] },
        properties: {
          vehicle_type: feature.properties.vehicle_type,
          source: feature.properties.source,
        },
      });
    }
  }

  const data = { type: "FeatureCollection", features: pointFeatures };
  this.map.renderHeatmap(data);
}
```

**Step 4: Update `interpolateVehiclePosition()` to use pre-parsed timestamps**

Replace (lines ~1406-1431):
```js
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
```

**Step 5: Test manually**

Load the app, switch to coverage mode, drag the slider, verify lines/heatmap render correctly. Start playback, verify it works.

**Step 6: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "perf: pre-parse coverage timestamps to avoid per-frame Date parsing"
```

---

### Task 2: Throttle playback rendering to ~10fps

Currently `playbackTick()` fires via `requestAnimationFrame` (~60fps). Each tick triggers `noUiSlider.set()` which fires `renderCoverage()` which rebuilds the full GeoJSON and calls `setData()`. At 60fps this is far more work than the visual result justifies.

**Fix:** Track `lastRenderTime` and skip renders that are less than 100ms apart during playback. The slider still updates at 60fps (smooth handle movement), but the expensive coverage render only fires at ~10fps.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Add render throttle to playback**

Add a `_lastCoverageRender` timestamp to the PlowApp constructor (in the playback section, around line 1084):
```js
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
```

**Step 2: Modify `renderCoverage()` to support throttling**

Change `renderCoverage()` to accept an optional `throttle` parameter:

```js
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
    this.map.setHeatmapVisibility(false);
    this.renderCoverageLines(fromTime, toTime);
    this.map.setCoverageLineVisibility(true);
  } else {
    this.map.setCoverageLineVisibility(false);
    this.renderHeatmap(fromTime, toTime);
    this.map.setHeatmapVisibility(true);
  }
}
```

**Step 3: Update the slider `"update"` handler to pass throttle during playback**

Find the slider event handler (around line 1765):
```js
timeSliderEl.noUiSlider.on("update", () => {
  const vals = timeSliderEl.noUiSlider.get().map(Number);
  app.renderCoverage(vals[0], vals[1], app.playback.playing);
});
```

The third argument `app.playback.playing` means throttling only applies during playback. Manual slider dragging still renders at full speed.

**Step 4: Force a final render when playback ends**

In `stopPlayback()`, after stopping, force one last unthrottled render so the final frame is accurate:

```js
stopPlayback() {
  this.playback.playing = false;
  if (this.playback.animFrame) {
    cancelAnimationFrame(this.playback.animFrame);
    this.playback.animFrame = null;
  }
  this.unlockPlaybackUI();
  // Force final render at actual position
  const vals = timeSliderEl.noUiSlider.get().map(Number);
  this.renderCoverage(vals[0], vals[1]);
}
```

**Step 5: Test manually**

Start playback, verify it looks smooth at ~10fps. Drag slider manually, verify it's still responsive (no throttle).

**Step 6: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "perf: throttle coverage rendering to ~10fps during playback"
```

---

### Task 3: Viewport-aware coverage filtering

Currently `renderCoverageLines()` and `renderHeatmap()` create Features for every coordinate pair in the time window, even if they're hundreds of km off-screen.

**Fix:** Before building Features, compute padded viewport bounds. Skip coordinate pairs where both endpoints fall outside the bounds. For the heatmap, skip points outside bounds.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Add bounds helper function**

Add near the top of the file (after the utility functions section, around line 830):

```js
/** Get padded viewport bounds for coverage culling. */
function getPaddedBounds(map, padding) {
  const b = map.getBounds();
  const padLng = (b.getEast() - b.getWest()) * padding;
  const padLat = (b.getNorth() - b.getSouth()) * padding;
  return {
    west: b.getWest() - padLng,
    south: b.getSouth() - padLat,
    east: b.getEast() + padLng,
    north: b.getNorth() + padLat,
  };
}

function inBounds(coord, b) {
  return (
    coord[0] >= b.west &&
    coord[0] <= b.east &&
    coord[1] >= b.south &&
    coord[1] <= b.north
  );
}
```

**Step 2: Add bounds filtering to `renderCoverageLines()`**

Add at the start of the method, and add a check in the inner loop:

```js
renderCoverageLines(fromTime, toTime) {
  const fromMs = fromTime.getTime();
  const toMs = toTime.getTime();
  const rangeMs = toMs - fromMs;
  const bounds = getPaddedBounds(plowMap.map, 0.2);

  const segmentFeatures = [];
  for (const feature of this.coverageData.features) {
    const coords = feature.geometry.coordinates;
    const epochMs = feature.properties._epochMs;
    const color = vehicleColor(feature.properties.vehicle_type);

    for (let i = 0; i < coords.length - 1; i++) {
      const tMs = epochMs[i];
      const tNextMs = epochMs[i + 1];
      if (tMs < fromMs) continue;
      if (tNextMs > toMs) break;

      // Viewport culling: skip if both endpoints are off-screen
      if (!inBounds(coords[i], bounds) && !inBounds(coords[i + 1], bounds))
        continue;

      const progress = rangeMs > 0 ? (tMs - fromMs) / rangeMs : 1;
      const opacity = 0.15 + progress * 0.65;

      segmentFeatures.push({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [coords[i], coords[i + 1]],
        },
        properties: {
          seg_opacity: opacity,
          seg_color: color,
          vehicle_type: feature.properties.vehicle_type,
          source: feature.properties.source,
        },
      });
    }
  }

  const data = { type: "FeatureCollection", features: segmentFeatures };
  this.map.renderCoverageLines(data);
}
```

**Step 3: Add bounds filtering to `renderHeatmap()`**

Same pattern:

```js
renderHeatmap(fromTime, toTime) {
  if (!this.coverageData) return;
  const fromMs = fromTime.getTime();
  const toMs = toTime.getTime();
  const bounds = getPaddedBounds(plowMap.map, 0.2);

  const pointFeatures = [];
  for (const feature of this.coverageData.features) {
    const coords = feature.geometry.coordinates;
    const epochMs = feature.properties._epochMs;
    for (let i = 0; i < coords.length; i++) {
      const tMs = epochMs[i];
      if (tMs < fromMs) continue;
      if (tMs > toMs) break;
      if (!inBounds(coords[i], bounds)) continue;
      pointFeatures.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: coords[i] },
        properties: {
          vehicle_type: feature.properties.vehicle_type,
          source: feature.properties.source,
        },
      });
    }
  }

  const data = { type: "FeatureCollection", features: pointFeatures };
  this.map.renderHeatmap(data);
}
```

**Step 4: Re-render coverage on map move (debounced)**

When the user pans/zooms while viewing coverage, re-render to include newly visible areas. Add a debounced handler.

In the map load section (or near the viewport tracking code), add:

```js
let coverageMoveTimeout = null;
plowMap.on("moveend", () => {
  if (app.mode !== "coverage" || !app.coverageData) return;
  if (app.playback.playing) return; // playback handles its own rendering
  clearTimeout(coverageMoveTimeout);
  coverageMoveTimeout = setTimeout(() => {
    const vals = timeSliderEl.noUiSlider.get().map(Number);
    app.renderCoverage(vals[0], vals[1]);
  }, 150);
});
```

**Step 5: Test manually**

Load coverage, zoom into a neighborhood. Pan around — new coverage lines should appear as you move. Zoom out to the province — everything renders. Start playback while zoomed in — only local segments animate.

**Step 6: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "perf: viewport-aware coverage culling with debounced re-render on pan"
```

---

### Task 4: Zoom-based source filtering for coverage

At province-level zoom, urban sources (St. John's, Mount Pearl) collapse to a blob. We add a `min_coverage_zoom` field to `SourceConfig` and expose it to the frontend. The coverage renderer skips features from sources whose `min_coverage_zoom` exceeds the current map zoom.

**Files:**
- Modify: `src/where_the_plow/source_config.py`
- Modify: `src/where_the_plow/routes.py` (expose field in `/sources`)
- Modify: `src/where_the_plow/static/app.js`
- Test: `tests/test_config.py` (add assertion)

**Step 1: Add `min_coverage_zoom` to `SourceConfig`**

In `source_config.py`, add the field to the dataclass:

```python
@dataclass
class SourceConfig:
    name: str
    display_name: str
    api_url: str
    poll_interval: int  # seconds
    center: tuple[float, float]  # (lng, lat)
    zoom: int
    parser: str  # "avl" or "aatracking"
    enabled: bool = True
    referer: str | None = None
    min_coverage_zoom: int = 0  # below this zoom, hide in coverage view
```

Set values in `build_sources()`:
- `st_johns`: `min_coverage_zoom=10`
- `mt_pearl`: `min_coverage_zoom=10`
- `provincial`: `min_coverage_zoom=0` (always show)

**Step 2: Expose in `/sources` endpoint**

In `routes.py`, add `min_coverage_zoom` to the response dict:

```python
return {
    name: {
        "display_name": src.display_name,
        "center": list(src.center),
        "zoom": src.zoom,
        "enabled": src.enabled,
        "min_coverage_zoom": src.min_coverage_zoom,
    }
    for name, src in SOURCES.items()
    if src.enabled
}
```

**Step 3: Add zoom-based source filtering to coverage renderers**

In both `renderCoverageLines()` and `renderHeatmap()`, add a source visibility check at the top of the feature loop. Get the current zoom and build a set of visible sources:

```js
renderCoverageLines(fromTime, toTime) {
  const fromMs = fromTime.getTime();
  const toMs = toTime.getTime();
  const rangeMs = toMs - fromMs;
  const bounds = getPaddedBounds(plowMap.map, 0.2);
  const zoom = plowMap.getZoom();

  const segmentFeatures = [];
  for (const feature of this.coverageData.features) {
    // Skip sources not visible at this zoom level
    const srcConfig = this.sources[feature.properties.source];
    if (srcConfig && zoom < srcConfig.min_coverage_zoom) continue;

    // ... rest of the loop unchanged
  }
  // ...
}
```

Same pattern for `renderHeatmap()`.

**Step 4: Add test for the new field**

In `tests/test_config.py`, add to `test_source_config_has_required_fields()`:
```python
assert src.min_coverage_zoom >= 0
```

And add a specific test:
```python
def test_source_min_coverage_zoom():
    assert SOURCES["st_johns"].min_coverage_zoom == 10
    assert SOURCES["mt_pearl"].min_coverage_zoom == 10
    assert SOURCES["provincial"].min_coverage_zoom == 0
```

**Step 5: Run tests**

Run: `uv run pytest --tb=short -q`
Expected: all pass.

**Step 6: Commit**

```bash
git add src/where_the_plow/source_config.py src/where_the_plow/routes.py src/where_the_plow/static/app.js tests/test_config.py
git commit -m "feat: zoom-based source filtering hides urban coverage at province zoom"
```
