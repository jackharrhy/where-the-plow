# Smart Video Playback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform video export from uniform-speed playback into a storytelling visualization with variable speed (fast-forward gaps, steady active sessions) and a color-coded footer timeline.

**Architecture:** New `/coverage/segments` backend endpoint returns activity segments (active/gap) for a bbox+time range. Frontend recording loop iterates segments instead of linear time, allocating video time proportionally. Footer with timeline bar is drawn on a taller composite canvas.

**Tech Stack:** Python/FastAPI + DuckDB (backend), vanilla JS + MapLibre + deck.gl + Mediabunny (frontend)

---

### Task 1: Backend — `get_activity_segments()` DB method

**Files:**
- Modify: `src/where_the_plow/db.py` (add method after `get_coverage_trails` ~line 361)
- Test: `tests/test_db.py` (add test at end of file)

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_get_activity_segments():
    db, path = make_db()
    try:
        now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
        db.upsert_vehicles([
            {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "SA PLOW TRUCK", "source": "st_johns"},
        ])
        # Session 1: 3 positions at 30s intervals starting at now
        # Gap: 20 minutes (> 15min threshold)
        # Session 2: 2 positions at 30s intervals starting at now+20min
        positions = [
            {"vehicle_id": "v1", "timestamp": now, "longitude": -52.73, "latitude": 47.56, "source": "st_johns"},
            {"vehicle_id": "v1", "timestamp": now + timedelta(seconds=30), "longitude": -52.74, "latitude": 47.57, "source": "st_johns"},
            {"vehicle_id": "v1", "timestamp": now + timedelta(seconds=60), "longitude": -52.75, "latitude": 47.58, "source": "st_johns"},
            # 20 minute gap
            {"vehicle_id": "v1", "timestamp": now + timedelta(minutes=20), "longitude": -52.73, "latitude": 47.56, "source": "st_johns"},
            {"vehicle_id": "v1", "timestamp": now + timedelta(minutes=20, seconds=30), "longitude": -52.74, "latitude": 47.57, "source": "st_johns"},
        ]
        db.insert_positions(positions)

        since = now - timedelta(minutes=5)
        until = now + timedelta(minutes=25)
        bbox = (-52.80, 47.50, -52.70, 47.60)

        segments = db.get_activity_segments(since, until, bbox, gap_threshold_minutes=15)

        # Expect: leading gap, session 1, gap, session 2, trailing gap
        assert len(segments) == 5
        assert segments[0]["type"] == "gap"     # since → first position
        assert segments[1]["type"] == "active"   # session 1
        assert segments[2]["type"] == "gap"      # between sessions
        assert segments[3]["type"] == "active"   # session 2
        assert segments[4]["type"] == "gap"      # last position → until

        # Active segments should have correct boundaries
        assert segments[1]["start"] == now.isoformat()
        assert segments[1]["end"] == (now + timedelta(seconds=60)).isoformat()
        assert segments[3]["start"] == (now + timedelta(minutes=20)).isoformat()
        assert segments[3]["end"] == (now + timedelta(minutes=20, seconds=30)).isoformat()

        # No activity → no segments (just one big gap)
        far_bbox = (-50.0, 48.0, -49.0, 49.0)
        segments_empty = db.get_activity_segments(since, until, far_bbox, gap_threshold_minutes=15)
        assert len(segments_empty) == 1
        assert segments_empty[0]["type"] == "gap"
    finally:
        db.close()
        os.unlink(path)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_get_activity_segments -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'get_activity_segments'`

**Step 3: Implement `get_activity_segments` in `db.py`**

Add after `get_coverage_trails` method (~line 361):

```python
def get_activity_segments(
    self,
    since: datetime,
    until: datetime,
    bbox: tuple[float, float, float, float],
    gap_threshold_minutes: int = 15,
) -> list[dict]:
    """Detect active/gap segments within a bbox for a time range.

    Returns a list of {"start": iso, "end": iso, "type": "active"|"gap"}.
    Active = positions present within gap_threshold. Gap = no positions.
    Leading gap (since→first pos) and trailing gap (last pos→until) included.
    """
    west, south, east, north = bbox
    rows = self.conn.execute(
        """
        SELECT timestamp
        FROM positions
        WHERE timestamp >= $1
          AND timestamp <= $2
          AND ST_Intersects(geom, ST_MakeEnvelope($3, $4, $5, $6))
        ORDER BY timestamp
        """,
        [since, until, west, south, east, north],
    ).fetchall()

    if not rows:
        return [{"start": since.isoformat(), "end": until.isoformat(), "type": "gap"}]

    threshold = timedelta(minutes=gap_threshold_minutes)
    segments = []

    # Leading gap: since → first position
    first_ts = rows[0][0]
    if first_ts > since:
        segments.append({"start": since.isoformat(), "end": first_ts.isoformat(), "type": "gap"})

    # Walk through timestamps, group into active sessions
    session_start = rows[0][0]
    session_end = rows[0][0]

    for i in range(1, len(rows)):
        ts = rows[i][0]
        if ts - session_end > threshold:
            # End current active session
            segments.append({"start": session_start.isoformat(), "end": session_end.isoformat(), "type": "active"})
            # Add gap between sessions
            segments.append({"start": session_end.isoformat(), "end": ts.isoformat(), "type": "gap"})
            session_start = ts
        session_end = ts

    # Final active session
    segments.append({"start": session_start.isoformat(), "end": session_end.isoformat(), "type": "active"})

    # Trailing gap: last position → until
    last_ts = rows[-1][0]
    if last_ts < until:
        segments.append({"start": last_ts.isoformat(), "end": until.isoformat(), "type": "gap"})

    return segments
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py::test_get_activity_segments -v`
Expected: PASS

**Step 5: Commit**

```
git add src/where_the_plow/db.py tests/test_db.py
git commit -m "feat: add get_activity_segments DB method for plow session detection (#29)"
```

---

### Task 2: Backend — `/coverage/segments` route

**Files:**
- Modify: `src/where_the_plow/routes.py` (add endpoint after `/coverage`)
- Modify: `src/where_the_plow/models.py` (add response model)
- Test: `tests/test_routes.py` (add route tests)

**Step 1: Add Pydantic models in `models.py`**

Add after `CoverageFeatureCollection` class:

```python
class ActivitySegment(BaseModel):
    start: str = Field(..., description="ISO 8601 start time")
    end: str = Field(..., description="ISO 8601 end time")
    type: str = Field(..., description="'active' or 'gap'")

class ActivitySegmentsResponse(BaseModel):
    segments: list[ActivitySegment]
    gap_threshold_minutes: int
```

**Step 2: Write the failing route test**

Add to `tests/test_routes.py`:

```python
def test_get_coverage_segments(test_client):
    """Segments endpoint returns activity/gap segments."""
    client = test_client
    # Use the seeded data: v1 has 3 positions at 30s intervals at 2026-02-19T12:00
    # bbox around v1's area
    resp = client.get(
        "/coverage/segments",
        params={
            "since": "2026-02-19T11:00:00Z",
            "until": "2026-02-19T13:00:00Z",
            "bbox": "-52.80,47.50,-52.70,47.60",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "segments" in data
    assert "gap_threshold_minutes" in data
    # Should have at least: leading gap, active session, trailing gap
    types = [s["type"] for s in data["segments"]]
    assert "active" in types
    assert "gap" in types

def test_get_coverage_segments_requires_bbox(test_client):
    """Segments endpoint requires bbox parameter."""
    client = test_client
    resp = client.get(
        "/coverage/segments",
        params={"since": "2026-02-19T11:00:00Z", "until": "2026-02-19T13:00:00Z"},
    )
    assert resp.status_code == 422
```

**Step 3: Run tests to verify failure**

Run: `uv run pytest tests/test_routes.py::test_get_coverage_segments tests/test_routes.py::test_get_coverage_segments_requires_bbox -v`
Expected: FAIL — 404

**Step 4: Implement the route**

Add to `routes.py` after the `/coverage` endpoint:

```python
@router.get(
    "/coverage/segments",
    response_model=ActivitySegmentsResponse,
    summary="Activity segments",
    description="Detect plow activity sessions and gaps within a bounding box.",
    tags=["coverage"],
)
def get_coverage_segments(
    request: Request,
    since: datetime | None = Query(None, description="Start of time range (ISO 8601). Default: 24 hours ago."),
    until: datetime | None = Query(None, description="End of time range (ISO 8601). Default: now."),
    bbox: str = Query(..., description="Required bounding box: west,south,east,north"),
    gap_threshold: int = Query(15, description="Gap threshold in minutes", ge=1, le=120),
):
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
    if until is None:
        until = datetime.now(timezone.utc)

    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=422, detail="bbox must have 4 comma-separated values: west,south,east,north")
    try:
        bbox_tuple = tuple(float(p) for p in parts)
    except ValueError:
        raise HTTPException(status_code=422, detail="bbox values must be numbers")

    west, south, east, north = bbox_tuple
    if west >= east or south >= north:
        raise HTTPException(status_code=422, detail="bbox must have west < east and south < north")

    segments = db.get_activity_segments(since, until, bbox_tuple, gap_threshold_minutes=gap_threshold)
    return ActivitySegmentsResponse(
        segments=[ActivitySegment(**s) for s in segments],
        gap_threshold_minutes=gap_threshold,
    )
```

Add necessary imports: `ActivitySegment`, `ActivitySegmentsResponse` from models.

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_routes.py::test_get_coverage_segments tests/test_routes.py::test_get_coverage_segments_requires_bbox -v`
Expected: PASS

**Step 6: Commit**

```
git add src/where_the_plow/routes.py src/where_the_plow/models.py tests/test_routes.py
git commit -m "feat: add /coverage/segments endpoint for activity detection (#29)"
```

---

### Task 3: Frontend — Fetch segments and compute video timeline

**Files:**
- Modify: `src/where_the_plow/static/app.js` — modify `startRecording()` setup

**Step 1: Add segment fetch + time allocation logic**

In `startRecording()`, after the existing `await output.start()` and before the frame loop, replace the simple linear time calculation with:

```javascript
// Fetch activity segments for this region + time range
const segResp = await fetch(
  `/coverage/segments?since=${this.coverageSince.toISOString()}&until=${this.coverageUntil.toISOString()}&bbox=${this._exportBbox}`
);
const segData = await segResp.json();
const segments = segData.segments;

// Compute video time allocation per segment
const GAP_SPEED = 100;    // gaps play 100x faster than real time
const GAP_CAP_SEC = 5;    // max 5 video-seconds per gap
const fps = 30;

// Calculate raw video seconds per segment
const totalRangeMs = untilMs - sinceMs;
let rawSegments = segments.map(seg => {
  const startMs = new Date(seg.start).getTime();
  const endMs = new Date(seg.end).getTime();
  const realDurationMs = endMs - startMs;
  let videoSec;
  if (seg.type === 'gap') {
    videoSec = Math.min(realDurationMs / 1000 / GAP_SPEED, GAP_CAP_SEC);
  } else {
    // Active segments: proportional share of user-chosen duration
    videoSec = realDurationMs; // placeholder, will normalize
  }
  return { ...seg, startMs, endMs, realDurationMs, videoSec, type: seg.type };
});

// Normalize: fit everything into the user-chosen total duration
const durationSec = parseInt(document.getElementById('export-speed').value);
const totalGapVideoSec = rawSegments
  .filter(s => s.type === 'gap')
  .reduce((sum, s) => sum + s.videoSec, 0);
const activeRealMs = rawSegments
  .filter(s => s.type === 'active')
  .reduce((sum, s) => sum + s.realDurationMs, 0);
const activeVideoBudget = Math.max(1, durationSec - totalGapVideoSec);

rawSegments = rawSegments.map(seg => {
  if (seg.type === 'active' && activeRealMs > 0) {
    seg.videoSec = activeVideoBudget * (seg.realDurationMs / activeRealMs);
  }
  seg.frameCount = Math.max(1, Math.round(seg.videoSec * fps));
  return seg;
});

const totalFrames = rawSegments.reduce((sum, s) => sum + s.frameCount, 0);
```

**Step 2: Replace the frame loop**

Replace the existing linear `for (let i = 0; ...)` frame loop with a segment-aware loop:

```javascript
let globalFrame = 0;
for (const seg of rawSegments) {
  if (this.recording.cancelled) break;

  for (let f = 0; f < seg.frameCount; f++) {
    if (this.recording.cancelled) break;

    const segProgress = f / seg.frameCount;
    const currentTimeMs = seg.startMs + segProgress * seg.realDurationMs;

    // Map the time to slider value (0-1000)
    const sliderVal = ((currentTimeMs - sinceMs) / totalRangeMs) * 1000;

    // During gaps, clear trails; during active, show coverage
    if (seg.type === 'gap') {
      this.map.setDeckLayers([]);
    } else {
      timeSliderEl.noUiSlider.set([0, sliderVal]);
      this.renderCoverage(0, sliderVal);
    }

    // Wait for MapLibre render
    this.map.map.triggerRepaint();
    await new Promise(r => this.map.map.once('render', r));
    await new Promise(r => requestAnimationFrame(r));

    // Composite: map + footer
    ctx.drawImage(mapCanvas, 0, 0);
    this._drawVideoFooter(ctx, width, compositeHeight, {
      currentTimeMs,
      segments: rawSegments,
      sinceMs,
      untilMs,
      segment: seg,
      segProgress,
    });

    // Feed frame
    const timestamp = globalFrame / fps;
    const duration = 1 / fps;
    await videoSource.add(timestamp, duration);

    // Progress
    const pct = Math.round((globalFrame / totalFrames) * 100);
    progressFill.style.width = pct + '%';
    progressText.textContent = `Encoding: ${pct}%`;
    globalFrame++;
  }
}
```

**Step 3: Commit**

```
git add src/where_the_plow/static/app.js
git commit -m "feat: segment-aware recording loop with variable playback speed (#29)"
```

---

### Task 4: Frontend — Footer drawing method

**Files:**
- Modify: `src/where_the_plow/static/app.js` — replace `_drawRecordingOverlay` with `_drawVideoFooter`

**Step 1: Update composite canvas sizing**

In `startRecording()`, change the composite canvas setup to be taller:

```javascript
const FOOTER_H = 80;
const compositeHeight = height + FOOTER_H;
const composite = document.createElement('canvas');
composite.width = width;
composite.height = compositeHeight;
const ctx = composite.getContext('2d', { willReadFrequently: true });
```

Update the `CanvasSource` to use the larger canvas (it already does since it's passed `composite`).

**Step 2: Implement `_drawVideoFooter`**

Replace `_drawRecordingOverlay` with:

```javascript
_drawVideoFooter(ctx, width, compositeHeight, state) {
  const { currentTimeMs, segments, sinceMs, untilMs, segment, segProgress } = state;
  const FOOTER_H = 80;
  const footerY = compositeHeight - FOOTER_H;
  const totalRangeMs = untilMs - sinceMs;

  // Footer background
  ctx.fillStyle = '#1a1a2e';
  ctx.fillRect(0, footerY, width, FOOTER_H);

  // Border line at top of footer
  ctx.strokeStyle = 'rgba(255,255,255,0.15)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, footerY);
  ctx.lineTo(width, footerY);
  ctx.stroke();

  const pad = 12;
  const fontSize = Math.max(12, Math.round(FOOTER_H / 6));

  // Row 1: timestamp (left), status (center-right), duration (right)
  ctx.font = `${fontSize}px sans-serif`;
  ctx.textBaseline = 'top';
  ctx.fillStyle = '#e2e8f0';

  const time = new Date(currentTimeMs);
  const timeStr = time.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
  ctx.textAlign = 'left';
  ctx.fillText(timeStr, pad, footerY + 6);

  // Status indicator
  const isActive = segment.type === 'active';
  const dotColor = isActive ? '#4ade80' : '#6b7280';
  const statusText = isActive
    ? 'Plow active'
    : `No plow — ${this._formatDuration(segment.realDurationMs)}`;

  const statusX = width / 2;
  ctx.textAlign = 'center';
  // Draw dot
  ctx.fillStyle = dotColor;
  ctx.beginPath();
  const dotY = footerY + 6 + fontSize / 2;
  const dotR = fontSize / 3;
  const textMetrics = ctx.measureText(statusText);
  const dotOffsetX = statusX - textMetrics.width / 2 - dotR - 6;
  ctx.arc(dotOffsetX, dotY, dotR, 0, Math.PI * 2);
  ctx.fill();
  // Status text
  ctx.fillStyle = isActive ? '#4ade80' : '#9ca3af';
  ctx.fillText(statusText, statusX, footerY + 6);

  // Session elapsed (right side)
  if (isActive) {
    const elapsed = currentTimeMs - segment.startMs;
    ctx.textAlign = 'right';
    ctx.fillStyle = '#e2e8f0';
    ctx.fillText(this._formatDuration(elapsed) + ' so far', width - pad, footerY + 6);
  }

  // Row 2: Timeline bar
  const barY = footerY + 6 + fontSize + 6;
  const barH = 10;
  const barX = pad;
  const barW = width - 2 * pad;

  // Draw segment colors
  for (const seg of segments) {
    const x0 = barX + ((seg.startMs - sinceMs) / totalRangeMs) * barW;
    const x1 = barX + ((seg.endMs - sinceMs) / totalRangeMs) * barW;
    ctx.fillStyle = seg.type === 'active' ? '#4ade80' : '#374151';
    ctx.fillRect(x0, barY, x1 - x0, barH);
  }

  // Playhead
  const playX = barX + ((currentTimeMs - sinceMs) / totalRangeMs) * barW;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(playX - 1, barY - 2, 2, barH + 4);

  // Row 3: branding (left), date range (right)
  const row3Y = barY + barH + 6;
  ctx.font = `${Math.max(10, fontSize - 2)}px sans-serif`;
  ctx.fillStyle = '#9ca3af';
  ctx.textAlign = 'left';
  ctx.fillText('plow.jackharrhy.dev', pad, row3Y);

  ctx.textAlign = 'right';
  const sinceDate = new Date(sinceMs);
  const untilDate = new Date(untilMs);
  const rangeStr = sinceDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' – ' + untilDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  ctx.fillText(rangeStr, width - pad, row3Y);
}

_formatDuration(ms) {
  const totalMin = Math.floor(ms / 60000);
  const hours = Math.floor(totalMin / 60);
  const mins = totalMin % 60;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}
```

**Step 3: Commit**

```
git add src/where_the_plow/static/app.js
git commit -m "feat: add video footer with color-coded timeline bar and status (#29)"
```

---

### Task 5: Frontend — Clean up old overlay, update README

**Files:**
- Modify: `src/where_the_plow/static/app.js` — remove old `_drawRecordingOverlay` if not used elsewhere
- Modify: `README.md` — add `/coverage/segments` to API table

**Step 1: Remove `_drawRecordingOverlay`**

Delete the old method (lines ~2042-2065) since it's replaced by `_drawVideoFooter`.

**Step 2: Update README API table**

Add to the API endpoint table:

```
| GET    | `/coverage/segments` | Activity segments for a region | `since`, `until`, `bbox` (required), `gap_threshold` |
```

**Step 3: Run all tests**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 4: Commit**

```
git add src/where_the_plow/static/app.js README.md
git commit -m "chore: remove old overlay method, document /coverage/segments endpoint (#29)"
```

---

### Task 6: Integration pass — test full flow manually

This is a manual testing task:

1. Load the app, enter export mode, draw a polygon
2. Set a multi-day date range and click Preview
3. Click Record — verify:
   - Video shows footer with timeline bar
   - Gaps fast-forward visibly (timestamp jumps)
   - Active sessions show trails being drawn at readable pace
   - Footer status indicator toggles green/grey
   - Playhead moves along timeline bar
   - Branding and date range visible
4. Download video and verify it plays correctly

No code changes unless issues found.
