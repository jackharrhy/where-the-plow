# deck.gl Coverage Rendering Migration

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace MapLibre GeoJSON-based coverage rendering with deck.gl's GPU-accelerated TripsLayer and HeatmapLayer, eliminating per-frame GeoJSON rebuilding and enabling smoother playback animation.

**Architecture:** deck.gl is added as a `MapboxOverlay` on the existing MapLibre map. Only coverage rendering (lines + heatmap views) moves to deck.gl. Vehicle markers, mini-trails, and individual vehicle trails remain native MapLibre layers. Coverage data is transformed once on fetch into the format deck.gl expects. During playback, only a `currentTime` number is updated — no data rebuilding.

**Tech Stack:** Vanilla JS (no bundler), MapLibre GL JS v5, deck.gl v9 via CDN (`deck.gl/dist.min.js`), noUiSlider.

---

### Task 1: Add deck.gl CDN script and initialize MapboxOverlay

Add the deck.gl script tag and wire up a `MapboxOverlay` instance on PlowMap. This task makes no visual changes — it just establishes the deck.gl integration point.

**Files:**
- Modify: `src/where_the_plow/static/index.html`
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Add deck.gl script tag**

In `index.html`, add the deck.gl CDN bundle after the MapLibre script (line 72):

```html
<script src="https://unpkg.com/maplibre-gl@5/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@^9.0.0/dist.min.js"></script>
<script src="https://unpkg.com/nouislider@15/dist/nouislider.min.js"></script>
```

**Step 2: Add deck overlay to PlowMap constructor**

In `app.js`, modify the PlowMap constructor (line 352-356) to create a `MapboxOverlay` and add it as a map control. The overlay must be added after the map's `"load"` event, so store a reference and initialize later:

```js
class PlowMap {
  constructor(container, options) {
    this.map = new maplibregl.Map({ container, ...options });
    this.coverageAbort = null;
    this.deckOverlay = null;
  }
```

**Step 3: Initialize the deck overlay on map load**

In the `plowMap.on("load", ...)` handler (line 1972), add deck overlay initialization right after the callback opens, before `loadSources()`:

```js
plowMap.on("load", async () => {
  // Initialize deck.gl overlay for coverage rendering
  plowMap.deckOverlay = new deck.MapboxOverlay({ layers: [] });
  plowMap.map.addControl(plowMap.deckOverlay);

  await app.loadSources();
  // ... rest unchanged
```

**Step 4: Add a setDeckLayers helper to PlowMap**

Add this method to PlowMap, after the `clearCoverage()` method (after line 704):

```js
  setDeckLayers(layers) {
    if (this.deckOverlay) {
      this.deckOverlay.setProps({ layers });
    }
  }
```

**Step 5: Test manually**

Load the app. Verify the map still renders normally. Open browser console — no errors. Switch to coverage mode — existing MapLibre coverage should still work (we haven't changed the rendering path yet).

**Step 6: Commit**

```bash
git add src/where_the_plow/static/index.html src/where_the_plow/static/app.js
git commit -m "feat: add deck.gl CDN and MapboxOverlay integration scaffold"
```

---

### Task 2: Add vehicleColorRGB helper and transform coverage data for deck.gl

deck.gl uses `[R, G, B]` arrays (0-255) instead of hex strings. Add a color conversion helper and transform coverage data into the format TripsLayer expects when it's loaded.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Add vehicleColorRGB function**

Add after the existing `vehicleColor()` function (after line 847):

```js
/** Return [R, G, B] for a vehicle type — used by deck.gl layers. */
function vehicleColorRGB(type) {
  const hex = vehicleColor(type);
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}
```

**Step 2: Transform coverage data on load**

In `loadCoverageForRange()` (line 1570), after the existing `_epochMs` pre-parse (lines 1586-1591), add a `deckTrips` transformation. The timestamps must be normalized to millisecond offsets from `coverageSince` to avoid float32 precision loss in deck.gl's GPU shaders:

Replace the block from "Pre-parse timestamp strings" through the end of the try block:

```js
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
```

**Step 3: Add deckTrips to PlowApp constructor**

In the PlowApp constructor (line 1103), add `this.deckTrips = null;` alongside the existing coverage state (after line 1127):

```js
    // Coverage
    this.coverageData = null;
    this.deckTrips = null;
    this.coverageSince = null;
```

**Step 4: Clear deckTrips in enterRealtime**

In `enterRealtime()` (line 1531), after `this.coverageData = null;` (line 1536), add:

```js
    this.coverageData = null;
    this.deckTrips = null;
```

**Step 5: Add a sliderToOffsetMs helper**

The slider values (0-1000) need to map to millisecond offsets from `coverageSince` (matching the deck.gl timestamp format). Add this method to PlowApp after `sliderToTime()` (after line 1732):

```js
  /** Convert slider value (0-1000) to ms offset from coverageSince. */
  sliderToOffsetMs(val) {
    const range = this.coverageUntil.getTime() - this.coverageSince.getTime();
    return (val / 1000) * range;
  }
```

**Step 6: Test manually**

Load the app, switch to coverage mode. Open console, type `app.deckTrips` — verify it's an array of objects with `path`, `timestamps` (small numbers, not unix epoch), `color` (RGB arrays), etc.

**Step 7: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "feat: transform coverage data to deck.gl trip format on load"
```

---

### Task 3: Replace coverage lines rendering with TripsLayer

This is the core change. Replace the `renderCoverageLines()` method (which builds GeoJSON segments per frame) with a TripsLayer that renders GPU-side. Also update `renderCoverage()` to use the deck.gl path.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Rewrite renderCoverageLines to use TripsLayer**

Replace the entire `renderCoverageLines()` method (lines 1649-1696) with:

```js
  renderCoverageLines(fromTime, toTime) {
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
```

**Step 2: Update renderCoverage to stop using MapLibre visibility toggles for lines**

Replace `renderCoverage()` (lines 1621-1647) with:

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
    } else {
      this.map.setDeckLayers([]); // hide deck.gl trips layer
      this.renderHeatmap(fromTime, toTime);
      this.map.setHeatmapVisibility(true);
    }
  }
```

Note: We no longer call `setCoverageLineVisibility()` since the TripsLayer is managed entirely through `setDeckLayers()`. The MapLibre `coverage-lines` source/layer is no longer created. The heatmap still uses the old MapLibre path for now (Task 4 will migrate it).

**Step 3: Update clearCoverage to also clear deck.gl layers**

In `PlowMap.clearCoverage()` (lines 695-704), add deck.gl cleanup:

```js
  clearCoverage() {
    this.setDeckLayers([]);
    if (this.map.getLayer("coverage-lines"))
      this.map.removeLayer("coverage-lines");
    if (this.map.getSource("coverage-lines"))
      this.map.removeSource("coverage-lines");
    if (this.map.getLayer("coverage-heatmap"))
      this.map.removeLayer("coverage-heatmap");
    if (this.map.getSource("coverage-heatmap"))
      this.map.removeSource("coverage-heatmap");
  }
```

**Step 4: Update setTypeFilter to exclude coverage-lines**

In `PlowMap.setTypeFilter()` (lines 708-723), remove `"coverage-lines"` from the layer list since it no longer exists as a MapLibre layer:

```js
  setTypeFilter(filter) {
    const layerIds = [
      "vehicle-outline",
      "vehicle-circles",
      "mini-trails",
      "coverage-heatmap",
      "vehicle-trail-dots",
      "vehicle-trail-line",
    ];
    for (const id of layerIds) {
      if (this.map.getLayer(id)) {
        this.map.setFilter(id, filter);
      }
    }
  }
```

Note: The TripsLayer handles type/source filtering in `renderCoverageLines()` via the `visibleTrips` filter, so MapLibre filters don't need to apply to it.

**Step 5: Trigger re-render when filters change in coverage mode**

When source or type checkboxes change, we need to re-render the TripsLayer (since filtering happens in JS, not via MapLibre filters). The existing `applyFilters()` only sets MapLibre filters. Add a deck.gl re-render after it.

In `switchCoverageView()` (line 1609) — this already calls `renderCoverage()` then `applyFilters()`, which is correct.

For the legend checkbox handlers, after `app.applyFilters()` is called, we also need to re-render coverage. Find the source checkbox handler (line 1898) and add a re-render:

```js
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
    app.updatePlaybackAvailability();
    const vals = timeSliderEl.noUiSlider.get().map(Number);
    app.renderCoverage(vals[0], vals[1]);
  }
});
```

And the type checkbox handler (line 1940):

```js
document.getElementById("legend-vehicles").addEventListener("change", () => {
  app.applyFilters();
  app.populateFollowDropdown();
  if (app.mode === "coverage") {
    const vals = timeSliderEl.noUiSlider.get().map(Number);
    app.renderCoverage(vals[0], vals[1]);
  }
});
```

**Step 6: Test manually**

Load the app, switch to coverage mode. Verify:
- Coverage lines render with deck.gl (should look visually similar but with rounded line caps/joints and a fade effect)
- Drag the slider — lines update
- Start playback — lines animate
- Toggle source/type checkboxes — lines update
- Switch to heatmap view — old MapLibre heatmap still works
- Switch back to realtime — no errors

**Step 7: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "feat: replace MapLibre coverage lines with deck.gl TripsLayer"
```

---

### Task 4: Replace heatmap rendering with deck.gl HeatmapLayer

Migrate the heatmap view from MapLibre's native heatmap layer to deck.gl's HeatmapLayer. This eliminates GeoJSON Feature wrapping and uses deck.gl's GPU aggregation.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Rewrite renderHeatmap to use deck.gl HeatmapLayer**

Replace the entire `renderHeatmap()` method (lines 1698-1727) with:

```js
  renderHeatmap(fromTime, toTime) {
    if (!this.coverageData) return;
    const baseTime = this.coverageSince.getTime();
    const fromOffset = fromTime.getTime() - baseTime;
    const toOffset = toTime.getTime() - baseTime;
    const bounds = getPaddedBounds(plowMap.map, 0.2);
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
        if (!inBounds(trip.path[i], bounds)) continue;
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
      }),
    ]);
  }
```

**Step 2: Update renderCoverage to use deck.gl for both views**

Replace `renderCoverage()` with the unified deck.gl version — neither view uses MapLibre layers now:

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
      this.renderCoverageLines(fromTime, toTime);
    } else {
      this.renderHeatmap(fromTime, toTime);
    }
  }
```

**Step 3: Remove old MapLibre coverage methods from PlowMap**

Delete these methods that are no longer used:
- `renderCoverageLines(segmentData)` (lines 591-611) — replaced by `setDeckLayers()` with TripsLayer
- `renderHeatmap(pointData)` (lines 613-673) — replaced by `setDeckLayers()` with HeatmapLayer
- `setCoverageLineVisibility(visible)` (lines 675-683) — no longer needed
- `setHeatmapVisibility(visible)` (lines 685-693) — no longer needed

And simplify `clearCoverage()`:

```js
  clearCoverage() {
    this.setDeckLayers([]);
  }
```

**Step 4: Remove coverage-heatmap from setTypeFilter**

Update `setTypeFilter()` to remove `"coverage-heatmap"` since it no longer exists as a MapLibre layer:

```js
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
```

**Step 5: Remove the debounced coverage re-render on map move for lines view**

The `moveend` handler (line 1959-1968) was needed because MapLibre coverage lines only showed data within the viewport. deck.gl's TripsLayer renders all data regardless of viewport (GPU handles culling). However, the heatmap view still does JS-side viewport culling, so we keep the handler but only trigger for heatmap:

```js
let coverageMoveTimeout = null;
plowMap.on("moveend", () => {
  if (app.mode !== "coverage" || !app.coverageData) return;
  if (app.playback.playing) return;
  if (app.coverageView !== "heatmap") return; // TripsLayer handles viewport internally
  clearTimeout(coverageMoveTimeout);
  coverageMoveTimeout = setTimeout(() => {
    const vals = timeSliderEl.noUiSlider.get().map(Number);
    app.renderCoverage(vals[0], vals[1]);
  }, 150);
});
```

**Step 6: Test manually**

Load the app, switch to coverage mode:
- Lines view: renders with TripsLayer (same as after Task 3)
- Switch to heatmap view: renders with deck.gl HeatmapLayer (blue → yellow → orange → red gradient)
- Drag slider in heatmap view: points update
- Pan/zoom in heatmap view: re-renders after 150ms debounce
- Start playback in lines view: animated TripsLayer
- Toggle source/type checkboxes: both views update
- Switch to realtime: everything cleans up, no errors

**Step 7: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "feat: replace MapLibre heatmap with deck.gl HeatmapLayer, remove old coverage layers"
```

---

### Task 5: Optimize playback — skip throttle for TripsLayer, keep for heatmap

With deck.gl's TripsLayer, updating `currentTime` is a cheap GPU uniform update — no data transfer needed. The 100ms throttle that was added for MapLibre performance is no longer needed for the lines view. For heatmap playback (which still rebuilds point arrays), keep throttling.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Update the slider "update" handler**

Replace the slider handler (line 1892-1895) to only throttle during heatmap playback:

```js
timeSliderEl.noUiSlider.on("update", () => {
  const vals = timeSliderEl.noUiSlider.get().map(Number);
  const throttle = app.playback.playing && app.coverageView === "heatmap";
  app.renderCoverage(vals[0], vals[1], throttle);
});
```

**Step 2: Test manually**

- Start playback in lines view: should be smooth at 60fps (no throttle)
- Start playback in heatmap view: still throttled to ~10fps (heatmap is expensive)
- Drag slider manually in either view: no throttle (responsive)

**Step 3: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "perf: skip render throttle for deck.gl TripsLayer playback"
```

---

### Task 6: Remove unused viewport culling utilities

The `getPaddedBounds()` and `inBounds()` functions were added for MapLibre viewport culling. With deck.gl handling the lines view, they're only used by the heatmap renderer. They can stay for now, but the viewport culling in `renderHeatmap()` is actually optional since deck.gl's HeatmapLayer does its own GPU-side viewport culling. Removing JS-side culling simplifies the code and lets deck.gl handle it.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Remove viewport culling from renderHeatmap**

In `renderHeatmap()`, remove the bounds calculation and `inBounds` check:

```js
  renderHeatmap(fromTime, toTime) {
    if (!this.coverageData) return;
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
      }),
    ]);
  }
```

**Step 2: Remove the moveend handler for heatmap re-render**

Since we're no longer doing JS-side viewport culling, the debounced moveend handler for heatmap is no longer needed. Remove the entire block (lines 1957-1968):

```js
// DELETE this entire block:
// let coverageMoveTimeout = null;
// plowMap.on("moveend", () => { ... });
```

**Step 3: Remove getPaddedBounds and inBounds**

Delete these utility functions (lines 893-913) since they are no longer used by any code:

```js
// DELETE:
// function getPaddedBounds(map, padding) { ... }
// function inBounds(coord, b) { ... }
```

**Step 4: Test manually**

- Coverage lines: still work (TripsLayer)
- Coverage heatmap: still works, now renders all time-matching points regardless of viewport
- Pan/zoom in heatmap: deck.gl re-aggregates automatically (no debounced handler needed)
- Playback: works in both views

**Step 5: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "refactor: remove JS viewport culling, let deck.gl handle it natively"
```

---

### Task 7: Clean up old MapLibre renderCoverageLines/renderHeatmap references

Final sweep to ensure no dead code remains and the old MapLibre `coverage-lines` source/layer is truly gone.

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Verify no references to removed methods**

Search `app.js` for these strings — they should not appear:
- `"coverage-lines"` — the MapLibre source/layer ID (should be fully removed)
- `"coverage-heatmap"` — the MapLibre source/layer ID (should be fully removed, only `deck.HeatmapLayer` with `id: "coverage-heatmap"` should remain as a deck.gl layer ID)
- `setCoverageLineVisibility` — removed method
- `setHeatmapVisibility` — removed method
- `getPaddedBounds` — removed utility
- `inBounds` — removed utility

If any remain, remove them.

**Step 2: Verify the PlowMap Coverage section is clean**

The `/* ── Coverage ─── */` section should now contain only:

```js
  /* ── Coverage ───────────────────────────────────── */

  clearCoverage() {
    this.setDeckLayers([]);
  }

  setDeckLayers(layers) {
    if (this.deckOverlay) {
      this.deckOverlay.setProps({ layers });
    }
  }
```

**Step 3: Full manual smoke test**

1. Load the app — realtime mode works, vehicles visible, mini-trails visible
2. Click a vehicle — trail shows correctly
3. Switch to coverage mode — 24h coverage loads
4. Lines view: deck.gl TripsLayer renders with fade, rounded caps
5. Drag slider — lines update smoothly
6. Switch to heatmap — deck.gl HeatmapLayer renders
7. Drag slider in heatmap — updates
8. Start playback in lines view — smooth animation
9. Follow a vehicle during playback — camera follows
10. Toggle source checkboxes — coverage updates
11. Toggle type checkboxes — coverage updates
12. Switch presets (6h, 12h, 48h, date picker) — data reloads
13. Switch back to realtime — everything cleans up
14. Refresh the page — everything works from scratch
15. Check browser console — no errors or warnings

**Step 4: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "refactor: clean up dead MapLibre coverage code after deck.gl migration"
```
