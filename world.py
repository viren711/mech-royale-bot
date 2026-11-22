"""Static map model built from the arena files: walk grid, sight grid, line checks and A*.

Everything is 2D. Buildings are rasterised onto a 2 m "fine" grid (walk-blocking and sight-blocking
bitmaps); pathfinding runs on a 4 m "coarse" grid derived from it. Standard library only.
"""
from __future__ import annotations

import heapq
import json
import math
import os
import sys
from array import array

FINE = 2.0  # m per fine cell
COARSE = 4.0  # m per coarse cell (2x2 fine cells)
SQRT2 = math.sqrt(2.0)


class World:
    def __init__(self, map_dir: str, files: list) -> None:
        wj = next((f for f in files if f.endswith("world.json")), "v2/world.json")
        tf = next((f for f in files if f.endswith(".i16")), "v2/terrain.i16")
        with open(os.path.join(map_dir, wj)) as f:
            w = json.load(f)
        t = w["terrain"]
        self.minx, self.miny = float(t["minX"]), float(t["minY"])
        self.tnx, self.tny = int(t["nx"]), int(t["ny"])
        h = array("h")
        with open(os.path.join(map_dir, tf), "rb") as f:
            h.frombytes(f.read())
        if sys.byteorder == "big":
            h.byteswap()
        self.h = h
        self.fnx, self.fny = self.tnx // 2, self.tny // 2
        self.cnx, self.cny = self.fnx // 2, self.fny // 2
        fnx, fny = self.fnx, self.fny
        blocked = bytearray(fnx * fny)  # cannot walk here
        opaque = bytearray(fnx * fny)  # blocks sight and shots at mech height
        b = w.get("bounds") or {}
        bx0, bx1 = b.get("minX", self.minx) + 2, b.get("maxX", self.minx + self.tnx) - 2
        by0, by1 = b.get("minY", self.miny) + 2, b.get("maxY", self.miny + self.tny) - 2
        tnx = self.tnx
        # terrain: outside the bounds and slopes steeper than ~50 degrees are walls
        for j in range(fny):
            y = self.miny + (j + 0.5) * FINE
            row = (2 * j + 1) * tnx
            up = row + 2 * tnx if j + 1 < fny else row
            yout = y < by0 or y > by1
            base = j * fnx
            for i in range(fnx):
                x = self.minx + (i + 0.5) * FINE
                if yout or x < bx0 or x > bx1:
                    blocked[base + i] = 1
                    continue
                a = h[row + 2 * i + 1]
                if i + 1 < fnx and abs(h[row + 2 * i + 3] - a) > 260 or abs(h[up + 2 * i + 1] - a) > 260:
                    blocked[base + i] = 1
        for p in w.get("prisms", []):
            self._raster(p, blocked, opaque)
        self.blocked, self.opaque = blocked, opaque
        cnx, cny = self.cnx, self.cny
        cb = bytearray(cnx * cny)
        for cj in range(cny):
            r0, r1 = (2 * cj) * fnx, (2 * cj + 1) * fnx
            for ci in range(cnx):
                i = 2 * ci
                if blocked[r0 + i] or blocked[r0 + i + 1] or blocked[r1 + i] or blocked[r1 + i + 1]:
                    cb[cj * cnx + ci] = 1
        for ci in range(cnx):
            cb[ci] = cb[(cny - 1) * cnx + ci] = 1
        for cj in range(cny):
            cb[cj * cnx] = cb[cj * cnx + cnx - 1] = 1
        self.cb = cb
        # extra step cost next to walls, so paths keep a little clearance
        near = bytearray(cnx * cny)
        for cj in range(1, cny - 1):
            for ci in range(1, cnx - 1):
                c = cj * cnx + ci
                if not cb[c] and (cb[c - 1] or cb[c + 1] or cb[c - cnx] or cb[c + cnx]):
                    near[c] = 1
        self.near = near

    # ------------------------------------------------------------------ build
    def ground(self, x: float, y: float) -> float:
        i = min(self.tnx - 1, max(0, int(round(x - self.minx))))
        j = min(self.tny - 1, max(0, int(round(y - self.miny))))
        return self.h[j * self.tnx + i] * 0.01

    def _raster(self, p: dict, blocked: bytearray, opaque: bytearray) -> None:
        rings = [p["ring"]] + list(p.get("holes") or [])
        edges = []
        ymin, ymax = 1e9, -1e9
        for r in rings:
            n = len(r) // 2
            for k in range(n):
                x0, y0 = r[2 * k], r[2 * k + 1]
                x1, y1 = r[(2 * k + 2) % (2 * n)], r[(2 * k + 3) % (2 * n)]
                if y0 != y1:
                    edges.append((x0, y0, x1, y1))
                ymin, ymax = min(ymin, y0), max(ymax, y0)
        base, top = p.get("base", 0.0), p.get("top", 0.0)
        ring = p["ring"]
        cg = self.ground(sum(ring[0::2]) / (len(ring) / 2), sum(ring[1::2]) / (len(ring) / 2))
        simple = p.get("kind") == "building" and base - cg < 4
        fnx, fny = self.fnx, self.fny
        j0 = max(0, int((ymin - self.miny) / FINE - 0.5))
        j1 = min(fny - 1, int((ymax - self.miny) / FINE + 0.5))
        for j in range(j0, j1 + 1):
            y = self.miny + (j + 0.5) * FINE
            xs = sorted(x0 + (y - y0) * (x1 - x0) / (y1 - y0) for x0, y0, x1, y1 in edges if (y0 <= y < y1) or (y1 <= y < y0))
            for k in range(0, len(xs) - 1, 2):
                # widen each span by half a cell so thin walls are not lost between samples
                i0 = max(0, int(math.floor((xs[k] - self.minx) / FINE - 0.5 + 0.25)))
                i1 = min(fnx - 1, int(math.floor((xs[k + 1] - self.minx) / FINE - 0.5 + 0.75)))
                if i1 < i0:
                    continue
                if simple:
                    blocked[j * fnx + i0 : j * fnx + i1 + 1] = b"\x01" * (i1 - i0 + 1)
                    if top - cg > 6:
                        opaque[j * fnx + i0 : j * fnx + i1 + 1] = b"\x01" * (i1 - i0 + 1)
                else:  # bridges, stadium parts: decide per cell against the ground under them
                    for i in range(i0, i1 + 1):
                        g = self.h[(2 * j + 1) * self.tnx + 2 * i + 1] * 0.01
                        if top > g + 1.2 and base < g + 12:
                            blocked[j * fnx + i] = 1
                        if top > g + 6 and base < g + 6:
                            opaque[j * fnx + i] = 1

    # ------------------------------------------------------------------ queries
    def cell(self, x: float, y: float) -> int:
        ci = min(self.cnx - 1, max(0, int((x - self.minx) / COARSE)))
        cj = min(self.cny - 1, max(0, int((y - self.miny) / COARSE)))
        return cj * self.cnx + ci

    def center(self, c: int) -> tuple:
        return (self.minx + (c % self.cnx + 0.5) * COARSE, self.miny + (c // self.cnx + 0.5) * COARSE)

    def free(self, x: float, y: float) -> bool:
        """Fine-grid walkability of a point."""
        i = int((x - self.minx) / FINE)
        j = int((y - self.miny) / FINE)
        if i < 0 or j < 0 or i >= self.fnx or j >= self.fny:
            return False
        return not self.blocked[j * self.fnx + i]

    def _ray(self, grid: bytearray, x0: float, y0: float, x1: float, y1: float, skip: float) -> bool:
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return True
        n = int(d / 1.5) + 1
        sx, sy = dx / n / FINE, dy / n / FINE
        fx, fy = (x0 - self.minx) / FINE, (y0 - self.miny) / FINE
        fnx, fny = self.fnx, self.fny
        k0 = int(skip / (d / n)) if skip > 0 else 0
        for k in range(k0, n + 1):
            i = int(fx + sx * k)
            j = int(fy + sy * k)
            if i < 0 or j < 0 or i >= fnx or j >= fny or grid[j * fnx + i]:
                return False
        return True

    def los(self, x0: float, y0: float, x1: float, y1: float) -> bool:
        """No building between two points (2D)."""
        return self._ray(self.opaque, x0, y0, x1, y1, 0.0)

    def walk_clear(self, x0: float, y0: float, x1: float, y1: float, skip: float = 0.0) -> bool:
        """A straight walk between two points stays on walkable fine cells (ignoring the first `skip` m)."""
        return self._ray(self.blocked, x0, y0, x1, y1, skip)

    def nearest_free(self, x: float, y: float, max_ring: int = 12) -> int:
        """Nearest unblocked coarse cell to a point, or -1."""
        cnx, cny, cb = self.cnx, self.cny, self.cb
        ci = min(cnx - 1, max(0, int((x - self.minx) / COARSE)))
        cj = min(cny - 1, max(0, int((y - self.miny) / COARSE)))
        if not cb[cj * cnx + ci]:
            return cj * cnx + ci
        best, bd = -1, 1e18
        for r in range(1, max_ring + 1):
            for dj in range(-r, r + 1):
                jj = cj + dj
                if jj < 0 or jj >= cny:
                    continue
                edge = abs(dj) == r
                for di in range(-r, r + 1) if edge else (-r, r):
                    ii = ci + di
                    if 0 <= ii < cnx and not cb[jj * cnx + ii]:
                        px = self.minx + (ii + 0.5) * COARSE - x
                        py = self.miny + (jj + 0.5) * COARSE - y
                        d = px * px + py * py
                        if d < bd:
                            best, bd = jj * cnx + ii, d
            if best >= 0:
                return best
        return -1


class Search:
    """Resumable A* over the coarse grid. Call step() until `done`; then `path` is a list of (x, y) or None."""

    MAX_NODES = 40000

    def __init__(self, world: World, start: int, goal: int) -> None:
        self.w, self.start, self.goal = world, start, goal
        self.gi, self.gj = goal % world.cnx, goal // world.cnx
        self.g = {start: 0.0}
        self.parent = {start: -1}
        self.heap = [(self._h(start), start)]
        self.closed = set()
        self.done = False
        self.path = None
        self.nodes = 0

    def _h(self, c: int) -> float:
        dx = abs(c % self.w.cnx - self.gi)
        dy = abs(c // self.w.cnx - self.gj)
        return (dx + dy) + (SQRT2 - 2.0) * min(dx, dy)

    def step(self, budget: int) -> bool:
        if self.done:
            return True
        w = self.w
        cnx, cb, near = w.cnx, w.cb, w.near
        g, parent, heap, closed, goal = self.g, self.parent, self.heap, self.closed, self.goal
        gi, gj = self.gi, self.gj
        push, pop = heapq.heappush, heapq.heappop
        moves = ((1, 1.0), (-1, 1.0), (cnx, 1.0), (-cnx, 1.0), (cnx + 1, SQRT2), (cnx - 1, SQRT2), (-cnx + 1, SQRT2), (-cnx - 1, SQRT2))
        n = 0
        while heap and n < budget:
            _, c = pop(heap)
            if c in closed:
                continue
            if c == goal:
                out = []
                while c != -1:
                    out.append(w.center(c))
                    c = parent[c]
                out.reverse()
                self.path, self.done = out, True
                return True
            closed.add(c)
            n += 1
            gc = g[c]
            for d, cost in moves:
                nb = c + d
                if cb[nb] or nb in closed:
                    continue
                if cost > 1.0:  # no cutting corners
                    dj = cnx if d > 2 else -cnx
                    if cb[c + dj] or cb[c + d - dj]:
                        continue
                ng = gc + cost + (0.7 if near[nb] else 0.0)
                if ng < g.get(nb, 1e18):
                    g[nb] = ng
                    parent[nb] = c
                    dx = abs(nb % cnx - gi)
                    dy = abs(nb // cnx - gj)
                    push(heap, (ng + (dx + dy) + (SQRT2 - 2.0) * min(dx, dy), nb))
        self.nodes += n
        if not heap or self.nodes > self.MAX_NODES:
            self.done = True
        return self.done
