# Region Video Export & Shareable Replay

**GitHub Issue:** #29 — Select a region, save a video of a "playback" of when plows visited that area, over a multi-day date range.

**Goal:** Let users draw a polygon on the map, select a multi-day date range, and either (a) export an MP4 video of the plow playback within that region, or (b) copy a shareable link that replays the same view in-browser.

---

## User Flow

1. **Enter export mode** — From coverage mode, click an "Export Region" button.
2. **Draw a region** — Mapbox Draw activates with polygon, rectangle, and trash tools. User draws a shape on the map.
3. **Select date range** — Reuse the existing date picker and time range controls, extended for multi-day ranges.
4. **Preview** — App fetches `/coverage` with spatial filter, loads data, user can preview playback with the existing slider/play system. Camera auto-fits to the drawn region but user can pan/zoom to adjust.
5. **Export MP4** — Mediabunny captures the MapLibre canvas frame-by-frame during a stepped (non-real-time) playback, compositing a timestamp + branding overlay. Downloads an MP4.
6. **Share link** — "Copy Link" button encodes region, date range, speed, and camera into URL params. Opening that link loads the app in replay mode and auto-plays.

---

## Technology Choices

### Region Drawing: `@mapbox/mapbox-gl-draw`

- Official MapLibre-compatible plugin (documented in MapLibre examples).
- Provides polygon + rectangle + trash tools.
- ~150kB from CDN, no build step needed.
- `draw.create` / `draw.update` events provide GeoJSON Feature with coordinates.

### Video Encoding: Mediabunny

- Pure TypeScript, zero dependencies, ~17kB for MP4 writing (vs ~25MB for FFmpeg WASM).
- `CanvasSource` API captures a canvas element directly into H.264/MP4.
- Hardware-accelerated encoding via WebCodecs API.
- **Browser support:** Chrome, Edge, Safari 16.4+. No Firefox (WebCodecs not supported). Firefox users see a "video export not supported in this browser" message but can still use the shareable link for in-browser replay.

### Spatial Filtering: DuckDB Spatial Extension

- Already in use (`geom` column, `ST_Point`, spatial index on `positions`).
- Add `ST_Intersects` / `ST_Within` filtering to the existing `/coverage` query.

---

## Backend Changes

### Extend `/coverage` with spatial filtering

Add two optional query parameters:

- `bbox=west,south,east,north` — Bounding box filter (standard GeoJSON bbox order). Uses `ST_Intersects(geom, ST_MakeEnvelope(west, south, east, north))`.
- `polygon=[[lng,lat],[lng,lat],...]` — URL-encoded GeoJSON coordinate ring. Uses `ST_Within(geom, ST_GeomFromGeoJSON(...))`. For shareable links reconstructing polygon-filtered views.

No new endpoints needed. The existing `/coverage` response format (per-vehicle LineString trails with timestamps) contains everything the frontend needs.

### Cache key extension

The file-based cache in `cache.py` currently keys on `(since, until, source)`. Extend the cache key to include a hash of the bbox/polygon parameter so spatially filtered queries get cached too.

---

## Frontend Architecture

### Recording Pipeline

MapLibre renders to a WebGL canvas. During recording, a controlled (non-real-time) playback loop:

1. Advances the coverage time to the next frame's timestamp.
2. Waits for deck.gl TripsLayer to render the updated state.
3. Composites the map canvas + overlay (timestamp + branding) onto an offscreen canvas.
4. Feeds the composited canvas to Mediabunny's `CanvasSource`.

**Stepped playback, not real-time:** During recording we do NOT use `requestAnimationFrame` at wall-clock speed. We step through time at the target framerate (30fps), render, capture, advance. This means:

- A 5-day range compressed to 60 seconds = each frame represents ~2.4 hours.
- Recording a 60-second video takes 30–90 seconds depending on rendering speed.
- User sees a progress bar ("Encoding: 45%...").

**Mediabunny setup (pseudocode):**

```js
const compositeCanvas = document.createElement('canvas');
const ctx = compositeCanvas.getContext('2d');

const videoSource = new CanvasSource(compositeCanvas, {
    codec: 'avc',        // H.264 for widest playback compatibility
    bitrate: 4_000_000,  // 4 Mbps, good for map content
});

const output = new Output({
    format: new Mp4OutputFormat(),
    target: new BufferTarget(),
});
output.addVideoTrack(videoSource, { frameRate: 30 });
await output.start();

for (let i = 0; i < totalFrames; i++) {
    const t = startTime + (i / totalFrames) * (endTime - startTime);
    updatePlaybackTime(t);          // advance TripsLayer currentTime
    await waitForRender();           // wait for deck.gl to paint
    ctx.drawImage(mapCanvas, 0, 0);  // copy map
    drawOverlay(ctx, t);             // timestamp + branding
    videoSource.add(i / 30, 1 / 30); // feed to encoder
    updateProgress(i / totalFrames);
}

await output.finalize();
downloadBlob(output.target.buffer, 'plow-coverage.mp4');
```

**Overlay:** `ctx.fillText()` on the compositing canvas. White text with dark shadow. Bottom-left: progressing timestamp. Bottom-right: `plow.jackharrhy.dev`.

**Resolution:** Match map canvas resolution, or offer 720p/1080p picker (resize map container temporarily during recording).

### Shareable Link

**URL structure:**

```
https://plow.jackharrhy.dev/?mode=replay&since=2026-02-20&until=2026-02-25&speed=10&center=47.56,-52.71&zoom=13&polygon=[[-52.8,47.5],[-52.7,47.5],[-52.7,47.6],[-52.8,47.6]]
```

Parameters:
- `mode=replay` — triggers replay mode on page load
- `since` / `until` — date range
- `speed` — animation duration in seconds
- `center` / `zoom` — camera position
- `polygon` — drawn region coordinates (URL-encoded)

**On load:**
1. Skip welcome modal.
2. Fetch `/coverage` with spatial filter params.
3. Set map camera to specified center/zoom.
4. Draw polygon outline on map for context.
5. Auto-start playback after data loads.
6. Minimal UI: map + play/pause + time label.

No server state. Links work as long as data exists in the database.

### UI Integration

**Entry point:** Sub-feature of coverage mode. "Export Region" button appears when in coverage mode.

**Export panel contents:**
- Mapbox Draw controls (polygon, rectangle, trash)
- Date range pickers
- Speed selector
- "Preview" button (uses existing playback system)
- "Export MP4" button (with WebCodecs support check)
- "Copy Share Link" button

**During recording:** Progress bar + "Cancel" button. Map locked, UI controls disabled.

**After recording:** Download prompt + share link option.

**Mobile:** Desktop-only or warning — video encoding is resource-intensive and polygon drawing on mobile is poor UX.

---

## Component Summary

| Component | Technology | Status |
|---|---|---|
| Region drawing | `@mapbox/mapbox-gl-draw` via CDN | New |
| Video encoding | Mediabunny (`CanvasSource` + `Mp4OutputFormat`) via CDN | New |
| Spatial data filtering | DuckDB `ST_Intersects` / `ST_Within` | Modified `/coverage` |
| Coverage cache | Extend cache key with bbox/polygon hash | Modified `cache.py` |
| Playback engine | Existing slider + TripsLayer | Modified (stepped mode for recording) |
| Shareable links | URL params, parsed on page load | New |
| Export UI panel | Vanilla JS/HTML/CSS | New |

---

## Open Questions / Future Work

- **Video duration control:** Should the user specify total video duration, or is speed (relative to real time) enough?
- **Audio:** Could add ambient/sound effects to the video in a future iteration.
- **Polygon simplification:** For complex polygons, simplify before encoding into URL to keep link length reasonable.
- **Data pruning:** What happens when old data is pruned? Shareable links for pruned ranges should show a clear "no data" message.
- **Rate limiting:** Should video export trigger any server-side concern? The `/coverage` call is cached, so probably not — but worth monitoring.
