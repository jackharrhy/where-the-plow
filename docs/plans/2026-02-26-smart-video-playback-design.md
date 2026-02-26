# Smart Video Playback — Design

## Problem

The current video export plays coverage trails at a uniform speed across the
entire time range. This makes it hard to see _when_ plows were active vs idle.
Multi-day ranges produce videos where most of the runtime shows nothing
happening, and plow sessions fly by too fast.

## Solution

A "storytelling" video export that detects plow activity sessions within the
selected region and plays them at variable speed:

- **Active sessions** (plow in region) → steady pace showing trails
- **Gap periods** (no plow) → fast-forward with elapsed counter, capped at 5s
- **Footer** → color-coded timeline bar, timestamp, status, branding

The video clearly communicates: when did plows come, how long did they stay,
and how long were the gaps between visits.

## Backend: Activity Segments Endpoint

**`GET /coverage/segments`** — returns time segments for a bbox + time range.

Query params:
- `since` / `until` — ISO 8601 time range (same as /coverage)
- `bbox` — required, `west,south,east,north`
- `gap_threshold` — minutes, default 15

Response:
```json
{
  "segments": [
    { "start": "...", "end": "...", "type": "gap" },
    { "start": "...", "end": "...", "type": "active" }
  ],
  "gap_threshold_minutes": 15
}
```

Logic: query all position timestamps within bbox + time range, sort, walk
through — any gap > threshold starts a new segment. Leading/trailing gaps
are included (from `since` to first position, last position to `until`).

## Frontend: Smart Playback Engine

### Time budget allocation

User picks total video duration (e.g. 30s). Each segment gets allocated video
time:

- Active segments: proportional to real duration
- Gap segments: proportional to real duration but at 100x speed, capped at 5s

This means most of the video runtime shows actual plow activity.

### During active segments

- Map shows trails being drawn via existing `renderCoverage()`
- Footer shows green dot + "Plow active" + session duration counter
- Timestamp ticks at steady pace

### During gap segments

- Trails from previous session clear (renderCoverage with matching from/to
  so trailLength=0, or clear layers entirely)
- Footer shows grey "No plow — Xh Ym" with fast-ticking elapsed counter
- Timestamp visibly fast-forwards
- Timeline playhead races across the grey segment

## Footer Visual Design

80px tall bar drawn on the composite canvas below the map. Three rows:

```
┌─────────────────────────────────────────────────────┐
│                    MAP AREA                          │
├─────────────────────────────────────────────────────┤
│ Feb 24 3:15 PM          ● Plow active    30m so far │
│ [██████████░░░░░░▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░] │
│ plow.jackharrhy.dev           Feb 24 – Feb 26, 2026 │
└─────────────────────────────────────────────────────┘
```

- Row 1: current timestamp (left), status with colored dot (center), duration (right)
- Row 2: timeline bar — green segments = active, dark grey = gaps, white playhead
- Row 3: branding (left), date range (right)

Colors: green `#4ade80`, dark grey `#374151`, white playhead.

Composite canvas is map height + 80px. Map drawn into top portion, footer
drawn into bottom 80px.
