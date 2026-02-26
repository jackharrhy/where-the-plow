<!-- changelog-id: 13 -->
# Changelog

## 2026-02-26 - Paradise Plows Added
The Town of Paradise snowplow fleet is now tracked alongside St. John's, Mount
Pearl, and the Provincial fleet. Paradise runs on a different tracking platform
(HitechMaps), so this is a new data source rather than an extension of the
existing ones. Toggle it on and off from the legend like any other source.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/56df668...PLACEHOLDER)

## 2026-02-25 — Agent System Removed, Direct AVL Access Restored!
Someone lovely from the City of reached out and explained what had
happened with the plow tracking service.

While the service was down, I built a distributed agent system so volunteers
could help keep the data flowing by running a small Go binary that fetched plow
data from their systems.

ECDSA signature verification / admin panel / scheduling coordinator / multi-platform
system service configuration - roughly 6,300 lines of code across Go, Python,
HTML/CSS/JS, tests, CI pipelines, and docs.

Thankfully, **all of that can now be removed**. The plow tracker is back to
talking directly to the city's AVL server, the way it was always meant to work.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/cec8c88...4dfb8c9)

## 2026-02-24 - Faster Coverage Rendering
Coverage playback and the heatmap view are now powered by [deck.gl](https://deck.gl), a GPU-accelerated visualization library. Time-lapse playback is noticeably smoother — the map no longer rebuilds thousands of line segments every frame, it just tells the GPU what time it is. Coverage lines now have rounded caps and a fade trail. Most importantly, **playback now works with all sources enabled** instead of requiring you to select a single source first.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/ff2cbce...58db35a)

## 2026-02-24 - Stale Data Indicators
The St. John's data source is currently experiencing technical difficulties on
the city's end. To make situations like this visible, the map now shows an
orange warning icon next to any source that hasn't received fresh data in a
while. Hovering over it tells you how long it's been. Vehicles that haven't
reported a position recently are also hidden from the realtime view so the map
only shows what's actually moving.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/e32ec39...ff2cbce)

## 2026-02-23 - Ko-fi Support Button
A "Support me on Ko-fi" button now appears in the sidebar, if you'd like to
help keep the servers running.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/05efafa...07a2b6b)

## 2026-02-23 - Multi-Source Tracking
The map now tracks plows from Mount Pearl and the Provincial fleet alongside
St. John's. Toggle sources on and off from the legend, or zoom into a specific
city. Coverage playback is significantly faster.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/13e5aff...8bc5101)

## 2026-02-22 - Address Search
You can now search for a street address and jump directly to it on the map,
instead of scrolling and zooming manually.

**Contributors:** [@blossom2016](https://github.com/blossom2016)
[View changes](https://github.com/jackharrhy/where-the-plow/compare/c5672ad...42ddc1e)

## 2026-02-22 - Email Signups & About Modal
New welcome modal with information about the project and an email signup form.
Leave your email to get notified when street-level plow alerts are ready.
Social sharing images and SEO metadata added.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/ae41e5f...c5672ad)

## 2026-02-21 - Coverage Playback Controls
Play back coverage data as a time-lapse animation. Filter by vehicle type
using the legend checkboxes. Follow a specific vehicle during playback.
Improved time range slider and mobile layout.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/5036734...ae41e5f)

## 2026-02-19 - Map Legend & Geolocate
Collapsible legend showing vehicle types with color coding. "Locate me" button
to center the map on your position.

**Contributors:** [@AminTaheri23](https://github.com/AminTaheri23)
[View changes](https://github.com/jackharrhy/where-the-plow/compare/5036734...7f4db6c)

## 2026-02-19 - Coverage History & Heatmap
View which streets have been plowed over the last 6, 12, or 24 hours. Switch
between route lines and a heatmap view. Pick a specific date to review past
coverage. Time slider to scrub through the window.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/4402d55...54f335f)

## 2026-02-19 - Launch
Live map of St. John's snowplow fleet. Vehicles update every 6 seconds from
the City of St. John's AVL system. Click any vehicle to see its recent trail.
Data is stored for historical playback.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/2a08888...4402d55)
