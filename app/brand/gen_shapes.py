#!/usr/bin/env python3
"""Plasmie's shapes: one source of truth for the brand page (JSON) and the app (Swift).

Each state is built from clean primitives (circles, ellipses, rounded boxes,
capsules) joined with a smooth union, then sampled at N points by casting rays
from the shape's centre. Dense, evenly placed samples are what keep the outline
crisp: a Catmull-Rom curve through only a few hand-placed anchors wobbles.

Every state has the same N anchors on a 100x100 canvas, clockwise from 12
o'clock, so any two states morph by interpolating anchors.

  python3 app/brand/gen_shapes.py      # writes plasmie-shapes.json + ../Sources/PlasmieShapes.swift
"""
import json
import math
from pathlib import Path

N = 48
HERE = Path(__file__).resolve().parent


# --- signed distance primitives (negative inside) ---------------------------
def circle(cx, cy, r):
    return lambda x, y: math.hypot(x - cx, y - cy) - r


def ellipse(cx, cy, rx, ry):
    # scaled-circle approximation; exact on the boundary, which is all we sample
    return lambda x, y: (math.hypot((x - cx) / rx, (y - cy) / ry) - 1) * min(rx, ry)


def rbox(cx, cy, hw, hh, r):
    def d(x, y):
        qx, qy = abs(x - cx) - hw + r, abs(y - cy) - hh + r
        return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r
    return d


def capsule(ax, ay, bx, by, r):
    def d(x, y):
        px, py, vx, vy = x - ax, y - ay, bx - ax, by - ay
        h = max(0.0, min(1.0, (px * vx + py * vy) / (vx * vx + vy * vy)))
        return math.hypot(px - vx * h, py - vy * h) - r
    return d


def smooth_union(k, *fs):
    def d(x, y):
        out = fs[0](x, y)
        for f in fs[1:]:
            b = f(x, y)
            h = max(k - abs(out - b), 0) / k
            out = min(out, b) - h * h * k / 4
        return out
    return d


def smooth_cut(k, base, hole):
    def d(x, y):
        a, b = base(x, y), -hole(x, y)
        h = max(k - abs(a - b), 0) / k
        return max(a, b) + h * h * k / 4
    return d


def polar_star(cx, cy, r, amp, points):
    def d(x, y):
        t = math.atan2(y - cy, x - cx) + math.pi / 2
        return math.hypot(x - cx, y - cy) - r * (1 + amp * math.cos(points * t))
    return d


# --- sampling ---------------------------------------------------------------
def sample(sdf, cx, cy, reach=70.0):
    """N boundary points: for each ray from (cx, cy), bisect where the SDF crosses 0."""
    pts = []
    for i in range(N):
        a = math.radians(-90 + 360 * i / N)
        dx, dy = math.cos(a), math.sin(a)
        lo, hi = 0.0, reach
        for _ in range(40):
            mid = (lo + hi) / 2
            if sdf(cx + dx * mid, cy + dy * mid) < 0:
                lo = mid
            else:
                hi = mid
        pts.append((round(cx + dx * lo, 2), round(cy + dy * lo, 2)))
    return pts


MOCHI = ellipse(50, 56, 36, 32)

SHAPES = {
    # resting mochi
    "idle": sample(MOCHI, 50, 56),
    # catching: a round body with a deep, clean mouth scooped from the top
    "ingest": sample(smooth_cut(5, ellipse(50, 58, 38, 33), circle(50, 25, 17)), 50, 64),
    # kneading: a squat dumpling with three soft pleats on top
    "summarize": sample(smooth_union(7, ellipse(50, 68, 41, 19),
                                     circle(34, 54, 9), circle(50, 49, 10), circle(66, 54, 9)), 50, 64),
    # filing: a rounded box
    "promote": sample(rbox(50, 56, 32, 29, 10), 50, 56),
    # thinking: a lightbulb — round crown on a short neck with a base
    "ask": sample(smooth_union(5, circle(50, 42, 30), rbox(50, 79, 11, 10, 3)), 50, 52),
    # held: the mochi raises a hand
    "held": sample(smooth_union(8, MOCHI, capsule(70, 40, 79, 27, 8), circle(81, 22, 10.5)), 56, 52),
    # failing: a melting puddle with two drips
    "error": sample(smooth_union(9, ellipse(50, 66, 42, 17),
                                 capsule(36, 72, 36, 81, 6), capsule(63, 74, 63, 86, 6.5)), 50, 66),
    # busy: an hourglass with a soft waist
    "busy": sample(smooth_union(14, ellipse(50, 32, 24, 12), ellipse(50, 80, 24, 12),
                                capsule(50, 32, 50, 80, 9)), 50, 56),
    # quiet: a flat sleeping mochi
    "quiet": sample(ellipse(50, 72, 42, 15), 50, 72),
    # off: a small curled ball
    "off": sample(circle(50, 64, 21), 50, 64),
    # success: a soft five-point star
    "success": sample(polar_star(50, 54, 33, 0.2, 5), 50, 54),
}

# Face per state: eye style, mouth style, extra prop. Renderers own the drawing.
FACES = {
    "idle":      {"eyes": "dot",    "mouth": "smile", "prop": None},
    "ingest":    {"eyes": "dot",    "mouth": "o",     "prop": "dots"},
    "summarize": {"eyes": "happy",  "mouth": "flat",  "prop": None},
    "promote":   {"eyes": "wink",   "mouth": "smile", "prop": "card"},
    "ask":       {"eyes": "up",     "mouth": "small", "prop": "spark"},
    "held":      {"eyes": "dot",    "mouth": "o",     "prop": "bang"},
    "error":     {"eyes": "worried", "mouth": "wobble", "prop": "sweat"},
    "busy":      {"eyes": "flat",   "mouth": "flat",  "prop": "sand"},
    "quiet":     {"eyes": "closed", "mouth": "none",  "prop": "zzz"},
    "off":       {"eyes": "closed", "mouth": "none",  "prop": None},
    "success":   {"eyes": "happy",  "mouth": "grin",  "prop": "sparkles"},
}

if __name__ == "__main__":
    assert all(len(p) == N for p in SHAPES.values()) and set(SHAPES) == set(FACES)
    (HERE / "plasmie-shapes.json").write_text(json.dumps({"anchors": N, "shapes": SHAPES, "faces": FACES}, indent=1))
    lines = ["// GENERATED by app/brand/gen_shapes.py — edit that, not this.",
             f"// Plasmie's states as {N} anchors on a 100x100 canvas (clockwise from 12 o'clock).",
             "import CoreGraphics", "", "enum PlasmieShapes {",
             f"    static let count = {N}",
             "    static let anchors: [String: [CGPoint]] = ["]
    for k, pts in SHAPES.items():
        body = ", ".join(f"CGPoint(x: {x}, y: {y})" for x, y in pts)
        lines.append(f'        "{k}": [{body}],')
    lines += ["    ]", "}", ""]
    (HERE.parent / "Sources" / "PlasmieShapes.swift").write_text("\n".join(lines))
    print("ok:", ", ".join(SHAPES))
