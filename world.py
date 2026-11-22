"""Static map model for the mech bot: grids built once at hello from the arena files.

Standard library only. All grids are flat `array` objects indexed `j * nx + i` with cell size CELL m,
cell (i, j) centred at (x0 + (i + 0.5) * CELL, y0 + (j + 0.5) * CELL).

Layers
- ground : terrain height at the cell centre
- occ    : top of whatever blocks sight/shots in the cell (max of ground and building/stadium tops)
- floor  : standing height (terrain, or the top of a step/terrace/roof/low bridge deck)
- wall   : 1 if the cell is not standable or borders a rise taller than the step height
- nav    : 1 if walkable with body clearance (wall dilated by one cell); moving between cells
           additionally needs floor[next] - floor[here] <= rise (drops are always allowed)
- canopy : how deep (m) the cell sits inside tree crowns at mech-body height (vision cover only)
"""
from __future__ import annotations

import heapq
import json
import math
import os
import struct
import time
from array import array
from typing import List, Optional, Tuple

CELL = 2.0
SQ2 = math.sqrt(2.0)


def _pip(x: float, y: float, ring: List[float]) -> bool:
    inside = False
    n = len(ring) // 2
    j = n - 1
    for i in range(n):
        xi, yi = ring[2 * i], ring[2 * i + 1]
        xj, yj = ring[2 * j], ring[2 * j + 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


class World:
    def __init__(self, map_dir: str, step_up: float = 1.2, body_h: float = 9.0) -> None:
        with open(os.path.join(map_dir, "v2", "world.json"), encoding="utf-8") as f:
            w = json.load(f)
        b = w["bounds"]
        self.minX, self.maxX, self.minY, self.maxY = b["minX"], b["maxX"], b["minY"], b["maxY"]
        t = w["terrain"]
        self.tx0, self.ty0, self.tstep = t["minX"], t["minY"], t["step"]
        self.tnx, self.tny, tscale = int(t["nx"]), int(t["ny"]), t.get("scale", 0.01)
        with open(os.path.join(map_dir, "v2", t.get("file", "terrain.i16")), "rb") as f:
            raw = f.read()
        hs = array("h")
        hs.frombytes(raw[: 2 * self.tnx * self.tny])
        if struct.pack("=h", 1) != struct.pack("<h", 1):
            hs.byteswap()
        self.terr = array("f", (v * tscale for v in hs))

        self.x0, self.y0 = self.minX, self.minY
        self.nx = int(math.ceil((self.maxX - self.minX) / CELL))
        self.ny = int(math.ceil((self.maxY - self.minY) / CELL))
        n = self.nx * self.ny
        ground = array("f", bytes(4 * n))
        for j in range(self.ny):
            y = self.y0 + (j + 0.5) * CELL
            for i in range(self.nx):
                x = self.x0 + (i + 0.5) * CELL
                g = self.ground_at(x, y)
                ground[j * self.nx + i] = g
        self.ground = ground
        occ = array("f", ground)
        floor = array("f", ground)
        body = bytearray(n)  # a prism occupies the body volume above the floor
        spans = []  # per covered cell: (cell, base, top) for a second pass
        for p in w["prisms"]:
            kind = p.get("kind")
            ring = p["ring"]
            holes = p.get("holes") or []
            base, top = p["base"], p["top"]
            xs, ys = ring[0::2], ring[1::2]
            i0 = max(0, int((min(xs) - self.x0) / CELL))
            i1 = min(self.nx - 1, int((max(xs) - self.x0) / CELL))
            j0 = max(0, int((min(ys) - self.y0) / CELL))
            j1 = min(self.ny - 1, int((max(ys) - self.y0) / CELL))
            for j in range(j0, j1 + 1):
                y = self.y0 + (j + 0.5) * CELL
                for i in range(i0, i1 + 1):
                    x = self.x0 + (i + 0.5) * CELL
                    if not _pip(x, y, ring):
                        continue
                    if holes and any(_pip(x, y, h) for h in holes):
                        continue
                    c = j * self.nx + i
                    g = ground[c]
                    if kind == "bridge":
                        if top - g < 3.0 and top > floor[c]:
                            floor[c] = top  # low bridge deck: walk on it
                        elif base - g < body_h + 0.5 and top - g >= 3.0:
                            spans.append((c, base, top))
                        continue
                    if top > occ[c]:
                        occ[c] = top
                    if base - g < body_h + 0.5:
                        if top > floor[c]:
                            floor[c] = top  # stand on it (a step, a terrace, or a roof)
                    else:
                        spans.append((c, base, top))  # overhang high enough to walk under
        for (c, base, top) in spans:
            if base < floor[c] + body_h and top > floor[c]:
                body[c] = 1
        self.occ = occ
        self.floor = floor
        # wall[c]: cell is not standable, or a neighbour rises above the step height (a wall face)
        nx, ny = self.nx, self.ny
        rise = step_up + 0.3
        wall = bytearray(body)
        for j in range(1, ny - 1):
            row = j * nx
            for i in range(1, nx - 1):
                c = row + i
                fc = floor[c] + rise
                if floor[c - 1] > fc or floor[c + 1] > fc or floor[c - nx] > fc or floor[c + nx] > fc:
                    wall[c] = 1
        self.wall = wall
        # body clearance: navigable if no wall cell in the 3x3 block (wall cells mark faces only)
        nav = bytearray(n)
        for j in range(1, ny - 1):
            row = j * nx
            for i in range(1, nx - 1):
                c = row + i
                if wall[c] or wall[c - 1] or wall[c + 1] or wall[c - nx] or wall[c + nx]                         or wall[c - nx - 1] or wall[c - nx + 1] or wall[c + nx - 1] or wall[c + nx + 1]:
                    continue
                nav[c] = 1
        # keep away from the map edge wall
        m = int(4 / CELL) + 1
        for j in range(ny):
            for i in range(nx):
                if i < m or j < m or i >= nx - m or j >= ny - m:
                    nav[j * nx + i] = 0
        self.nav = nav
        self.rise = rise
        # canopy depth at mech body height (centre z+4.5 .. top z+9)
        canopy = array("f", bytes(4 * n))
        tr = w.get("trees") or {}
        fields = tr.get("fields") or []
        data = tr.get("data") or []
        if fields and data:
            k = len(fields)
            fi = {name: idx for idx, name in enumerate(fields)}
            for s in range(0, len(data) - k + 1, k):
                rec = data[s:s + k]
                tz, th, cr, cb = rec[fi["z"]], rec[fi["height"]], rec[fi["crownR"]], rec[fi["crownBase"]]
                cx = rec[fi["crownX"]] if "crownX" in fi else rec[fi["x"]]
                cy = rec[fi["crownY"]] if "crownY" in fi else rec[fi["y"]]
                if cr < 2.5:
                    continue
                ci = int((cx - self.x0) / CELL)
                cj = int((cy - self.y0) / CELL)
                rr = int(cr / CELL) + 1
                lo, hi = tz + cb, tz + th
                for j in range(max(0, cj - rr), min(ny, cj + rr + 1)):
                    y = self.y0 + (j + 0.5) * CELL
                    for i in range(max(0, ci - rr), min(nx, ci + rr + 1)):
                        x = self.x0 + (i + 0.5) * CELL
                        d = math.hypot(x - cx, y - cy)
                        if d >= cr:
                            continue
                        c = j * nx + i
                        g = ground[c]
                        # crown must cover the eye line band of the body (centre and top)
                        if lo > g + 5.0 or hi < g + 8.5:
                            continue
                        depth = cr - d
                        if depth > canopy[c]:
                            canopy[c] = depth
        self.canopy = canopy

    # ------------------------------------------------------------------ sampling
    def ground_at(self, x: float, y: float) -> float:
        fx = (x - self.tx0) / self.tstep
        fy = (y - self.ty0) / self.tstep
        i = int(fx)
        j = int(fy)
        if i < 0:
            i, fx = 0, 0.0
        if j < 0:
            j, fy = 0, 0.0
        if i >= self.tnx - 1:
            i, fx = self.tnx - 2, float(self.tnx - 1)
        if j >= self.tny - 1:
            j, fy = self.tny - 2, float(self.tny - 1)
        ax, ay = fx - i, fy - j
        t = self.terr
        nx = self.tnx
        h00 = t[j * nx + i]
        h10 = t[j * nx + i + 1]
        h01 = t[(j + 1) * nx + i]
        h11 = t[(j + 1) * nx + i + 1]
        return (h00 * (1 - ax) + h10 * ax) * (1 - ay) + (h01 * (1 - ax) + h11 * ax) * ay

    def cell(self, x: float, y: float) -> Tuple[int, int]:
        i = int((x - self.x0) / CELL)
        j = int((y - self.y0) / CELL)
        return (min(max(i, 0), self.nx - 1), min(max(j, 0), self.ny - 1))

    def idx(self, x: float, y: float) -> int:
        i, j = self.cell(x, y)
        return j * self.nx + i

    def center(self, c: int) -> Tuple[float, float]:
        j, i = divmod(c, self.nx)
        return (self.x0 + (i + 0.5) * CELL, self.y0 + (j + 0.5) * CELL)

    def walkable(self, x: float, y: float) -> bool:
        if x < self.minX or x > self.maxX or y < self.minY or y > self.maxY:
            return False
        return bool(self.nav[self.idx(x, y)])

    def canopy_at(self, x: float, y: float) -> float:
        return self.canopy[self.idx(x, y)]

    # ------------------------------------------------------------------ rays
    def line_clear(self, ax: float, ay: float, bx: float, by: float) -> bool:
        """Straight walk from a to b stays on navigable cells."""
        d = math.hypot(bx - ax, by - ay)
        nsteps = int(d / (CELL * 0.5)) + 1
        nav, nx, floor = self.nav, self.nx, self.floor
        prev = -1
        for s in range(1, nsteps + 1):
            f = s / nsteps
            x = ax + (bx - ax) * f
            y = ay + (by - ay) * f
            i = int((x - self.x0) / CELL)
            j = int((y - self.y0) / CELL)
            if i < 0 or j < 0 or i >= nx or j >= self.ny or not nav[j * nx + i]:
                return False
            c = j * nx + i
            if prev >= 0 and c != prev and floor[c] - floor[prev] > self.rise:
                return False
            prev = c
        return True

    def sight_blocked(self, a: Tuple[float, float, float], b: Tuple[float, float, float]) -> bool:
        """True if buildings/terrain block the segment a->b (3D, sampled on the occluder grid)."""
        ax, ay, az = a
        bx, by, bz = b
        d = math.hypot(bx - ax, by - ay)
        if d < 3.0:
            return False
        step = CELL
        nsteps = int(d / step)
        occ, nx, ny = self.occ, self.nx, self.ny
        for s in range(1, nsteps):
            f = s / nsteps
            if f * d < 2.5 or (1 - f) * d < 2.5:
                continue
            x = ax + (bx - ax) * f
            y = ay + (by - ay) * f
            i = int((x - self.x0) / CELL)
            j = int((y - self.y0) / CELL)
            if i < 0 or j < 0 or i >= nx or j >= ny:
                return True
            if occ[j * nx + i] > az + (bz - az) * f:
                return True
        return False

    # ------------------------------------------------------------------ path finding
    def nearest_nav(self, x: float, y: float, rmax: int = 6) -> Optional[int]:
        ci, cj = self.cell(x, y)
        nx = self.nx
        best = None
        bd = 1e9
        for r in range(0, rmax + 1):
            for j in range(cj - r, cj + r + 1):
                for i in range(ci - r, ci + r + 1):
                    if 0 <= i < nx and 0 <= j < self.ny and self.nav[j * nx + i]:
                        d = (i - ci) ** 2 + (j - cj) ** 2
                        if d < bd:
                            bd, best = d, j * nx + i
            if best is not None:
                return best
        return None


class AStar:
    """Incremental A* on the nav grid: call step(budget) every tick until done."""

    def __init__(self, world: World, start: Tuple[float, float], goal: Tuple[float, float],
                 max_expand: int = 40000) -> None:
        self.w = world
        self.done = False
        self.reached = False
        self.path: Optional[List[Tuple[float, float]]] = None
        self.goal_xy = goal
        s = world.nearest_nav(*start)
        g = world.nearest_nav(*goal, rmax=12)
        if s is None or g is None:
            self.done = True
            return
        self.s, self.g = s, g
        self.gj, self.gi = divmod(g, world.nx)
        self.open: list = [(0.0, 0.0, s)]
        self.came = {s: -1}
        self.cost = {s: 0.0}
        self.expanded = 0
        self.max_expand = max_expand
        self.best = s
        self.best_h = self._h(s)

    def _h(self, c: int) -> float:
        j, i = divmod(c, self.w.nx)
        dx = abs(i - self.gi)
        dy = abs(j - self.gj)
        return (dx + dy + (SQ2 - 2) * min(dx, dy)) * 1.001

    def step(self, budget: int, deadline: float = 0.0) -> bool:
        if self.done:
            return True
        w = self.w
        nx, nav, floor = w.nx, w.nav, w.floor
        rise = w.rise
        nb = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
              (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2))
        openl, came, cost = self.open, self.came, self.cost
        n = 0
        while openl and n < budget:
            f, gc, c = heapq.heappop(openl)
            if gc > cost.get(c, 1e18):
                continue
            n += 1
            self.expanded += 1
            if deadline and (n & 63) == 0 and time.perf_counter() > deadline:
                heapq.heappush(openl, (f, gc, c))  # not expanded yet: put it back
                break
            if c == self.g:
                self.reached = True
                self._finish(c)
                return True
            h = f - gc
            if h < self.best_h:
                self.best_h, self.best = h, c
            for di, dj, sc in nb:
                nc = c + di + dj * nx
                if not nav[nc]:
                    continue
                if di and dj and (not nav[c + di] or not nav[c + dj * nx]):
                    continue
                if floor[nc] - floor[c] > rise:
                    continue
                ng = gc + sc
                if ng < cost.get(nc, 1e18):
                    cost[nc] = ng
                    came[nc] = c
                    heapq.heappush(openl, (ng + self._h(nc), ng, nc))
        if not openl or self.expanded >= self.max_expand:
            self._finish(self.best)
            return True
        return False

    def _finish(self, c: int) -> None:
        out = []
        while c != -1:
            out.append(self.w.center(c))
            c = self.came[c]
        out.reverse()
        self.path = out
        self.done = True
