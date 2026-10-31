"""Maakt goedkooptanken/data/landgrenzen.json: vereenvoudigde landgrenzen waarmee de app bepaalt in welk
land een station ligt.

Gebruik (eenmalig, of als je een land toevoegt):
    npm pack world-atlas@2.0.2 && tar xzf world-atlas-2.0.2.tgz
    python scripts/maak_landgrenzen.py package/countries-10m.json NL=Netherlands BE=Belgium DE=Germany

Elk argument na het bestand is LANDCODE=Engelse naam in Natural Earth (world-atlas). Bron van de
grenzen: Natural Earth (publiek domein), via het npm-pakket world-atlas (ISC-licentie).
"""
import json
import sys
from pathlib import Path

TOLERANCE = 0.0003  # graden (ca. 30 m) bij het vereenvoudigen
OUT = Path(__file__).resolve().parent.parent / "goedkooptanken" / "data" / "landgrenzen.json"


def decode_arcs(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def ring(arc_ids, arcs):
    pts = []
    for i in arc_ids:
        a = arcs[i] if i >= 0 else arcs[~i][::-1]
        pts.extend(a if not pts else a[1:])
    return pts


def dp(points, eps):
    """Douglas-Peucker, iteratief."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = points[a], points[b]
        dx, dy = x2 - x1, y2 - y1
        n = dx * dx + dy * dy
        best, idx = -1.0, None
        for i in range(a + 1, b):
            x, y = points[i]
            if n == 0:
                d = ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
            else:
                d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / n ** 0.5
            if d > best:
                best, idx = d, i
        if best > eps and idx is not None:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def main(path, pairs):
    topo = json.loads(Path(path).read_text(encoding="utf-8"))
    arcs = decode_arcs(topo)
    geoms = {g["properties"]["name"]: g for g in topo["objects"]["countries"]["geometries"]}
    result = {}
    for pair in pairs:
        code, name = pair.split("=", 1)
        g = geoms[name]
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        out = []
        for poly in polys:
            rings = [dp(ring(r, arcs), TOLERANCE) for r in poly]
            # alleen Europees vasteland en eilanden (geen overzeese gebieden)
            xs = [p[0] for p in rings[0]]
            ys = [p[1] for p in rings[0]]
            if min(ys) < 30 or max(xs) > 40 or min(xs) < -15:
                continue
            out.append([[[round(x, 4), round(y, 4)] for x, y in r] for r in rings])
        result[code] = out
        print(code, name, sum(len(r) for p in out for r in p), "punten")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    print("geschreven:", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
