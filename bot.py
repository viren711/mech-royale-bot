"""Mech Royale bot v2: kill hunters one at a time, break line of sight to regen, hold the zone."""
import heapq
import json
import math
import os
import random
import sys
from array import array

import mechfight as mf

TAU = math.tau
P = {
    "low_hp": 0.45,      # retreat to cover below this hp fraction (while threatened)
    "high_hp": 0.9,      # resume fighting above this
    "band_min": 35.0,    # preferred fight distance band
    "band_max": 110.0,
    "fire_range": 210.0,
    "loot_r": 70.0,      # detour radius for cubes / pickups when safe
    "goal_frac": 0.5,    # stay within this fraction of next zone radius
    "drops": 1.0,        # contest supply drops (1) or not (0)
    "dodge": 0.0,        # sidestep incoming bullets / charging lasers
    "stick": 0.0,        # keep the same target until it dies or is lost
    "plating": 0.0,      # prefer +HP plating over armor
    "endgame": 0.0,
    "farm": 0.0,         # shoot crates / NPC drones for cubes when no mech is around (until farm_until s)
    "farm_until": 330.0,
    "predict": 0.0,      # ML-lite: online acceleration estimate for target lead
    "predict_k": 0.5,
    "ml": 0.0,           # learned engage/retreat model (ml_model.json)
    "ml_thr": 0.5,
    "wpn": 1.0,          # pick up secondary weapons at all
    "wpn_r": 0.0,        # detour radius for weapon pickups (0 = loot_r)
    "no_mortar": 0.0, "no_laser": 0.0, "no_lightning": 0.0,
    "wpn_swap": 0.0,     # swap a held non-laser weapon for a laser pickup
    "wpn_threat": 0.0,   # allow weapon detours while threatened if hp is high
    "laser_hold": 0.97,  # release the laser at this fraction of full charge
    "laser_rng": 280.0,  # max distance to fire the laser
    "nav": 0.0,          # A* ground routing around buildings (4 m grid) instead of straight lines
    "opening": 0.0,      # first 40 s: sprint to the nearest laser/lightning pickup (radius 250 m)
    "zlead": 25.0,       # seconds before a shrink starts at which we already stand inside the NEXT circle
    "bandw": 0.0,        # distance band depends on loadout: lightning close, laser ~55-100 m
    "finish": 0.0,       # keep fighting a weak enemy (hp <= min(280, 0.52*my hp)) instead of retreating
    "burst": 0.0,        # retreat on burst damage: >240 hp lost in 1.7 s while below 74% hp
    "upg_dmg": 0.0,      # damage-first upgrade order (laser/gun damage, rate) instead of survival-first
    "boostclose": 0.0,   # boost to close distance on a visible target beyond the band
    "selective": 0.0,    # only fight mechs that are after us (hit us / aim at us / closing / charging); never wake idle house bots
    "iso": 0.0,          # fight from spots that see the target but are hidden from every other known mech
    "iso_watch": 30.0,   # penalty per other mech that can see a candidate spot
    "lethal": 0.0,       # release a partial laser charge once it already kills
    "dropheal": 0.0,     # below 70% hp go to a landed supply drop (alone in the ring) to heal
    "hunt": 0.0,         # walk toward a remembered enemy when healthy and nothing else to do
    "multi_flee": 0.0,   # retreat when >=2 enemies are close and hp < 85%
    "reload_cover": 0.0, # retreat to cover to reload when ammo is low and threatened
    "late_hold": 0.0,    # in the last rings, hold still in the centre unless an enemy is close      # after the last shrink starts, sit exactly on the zone centre
}
try:  # experiment overrides
    P.update(json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "params.json"))))
except Exception:
    pass
UPG_PREF = ["armor", "plating", "nanites", "gun_rate", "gun_damage", "laser_damage", "lightning_efficiency",
            "laser_charge", "gun_mag", "gun_velocity", "sensors", "gyros", "lightning_range", "mortar_reload",
            "lightning_chain", "servos", "capacitor", "reactor", "jets", "laser_pierce", "mortar_velocity", "mortar_splash"]


def ang_diff(a, b):
    return (a - b + math.pi) % TAU - math.pi


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class World:
    """Static map: building prisms for line of sight / cover, terrain for ground height."""

    def __init__(self, mapdir):
        self.prisms = []
        self.terrain = None
        try:
            w = json.load(open(os.path.join(mapdir, "v2", "world.json")))
            for p in w["prisms"]:
                r = p["ring"]
                pts = [(r[i], r[i + 1]) for i in range(0, len(r) - 1, 2)]
                if len(pts) < 3:
                    continue
                xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
                self.prisms.append((min(xs), min(ys), max(xs), max(ys), p["base"], p["top"], pts))
            t = w["terrain"]
            self.tx, self.ty, self.tnx, self.tny = t["minX"], t["minY"], t["nx"], t["ny"]
            a = array("h")
            with open(os.path.join(mapdir, "v2", "terrain.i16"), "rb") as f:
                a.frombytes(f.read())
            if sys.byteorder != "little":
                a.byteswap()
            self.terrain = a
        except Exception as e:  # never die on map problems
            log("map load failed", e)

    def ground(self, x, y):
        if self.terrain is None:
            return 0.0
        i = int(round(x - self.tx)); j = int(round(y - self.ty))
        i = min(max(i, 0), self.tnx - 1); j = min(max(j, 0), self.tny - 1)
        return self.terrain[j * self.tnx + i] * 0.01

    def inside(self, x, y, z):
        for (x0, y0, x1, y1, b, t, pts) in self.prisms:
            if x0 <= x <= x1 and y0 <= y <= y1 and b - 1 <= z <= t and _pip(x, y, pts):
                return True
        return False

    def blocked(self, a, b):
        """True if the 3D segment a->b passes through a building/bridge prism."""
        ax, ay, az = a; bx, by, bz = b
        lx0, lx1 = (ax, bx) if ax < bx else (bx, ax)
        ly0, ly1 = (ay, by) if ay < by else (by, ay)
        dx, dy, dz = bx - ax, by - ay, bz - az
        for (x0, y0, x1, y1, base, top, pts) in self.prisms:
            if x1 < lx0 or x0 > lx1 or y1 < ly0 or y0 > ly1:
                continue
            if max(az, bz) < base or min(az, bz) > top:
                continue
            n = len(pts)
            px, py = pts[-1]
            for k in range(n):
                qx, qy = pts[k]
                ex, ey = qx - px, qy - py
                den = dx * ey - dy * ex
                if den != 0:
                    wx, wy = px - ax, py - ay
                    s = (wx * ey - wy * ex) / den
                    u = (wx * dy - wy * dx) / den
                    if 0 < s < 1 and 0 <= u <= 1:
                        z = az + dz * s
                        if base <= z <= top:
                            return True
                px, py = qx, qy
        return False


class Nav:
    """4 m walkability grid (buildings inflated by the mech radius) + capped A*."""
    CELL = 4.0

    def __init__(self, world):
        self.ox, self.oy = -513.0, -334.0
        self.nx, self.ny = int(1070 / self.CELL) + 1, int(724 / self.CELL) + 1
        self.blk = bytearray(self.nx * self.ny)
        infl = 3.2
        for (x0, y0, x1, y1, b, t, pts) in world.prisms:
            gx = (x0 + x1) / 2; gy = (y0 + y1) / 2
            if t - world.ground(gx, gy) < 1.5 or (b - world.ground(gx, gy) > 9.5):
                continue
            i0 = max(0, int((x0 - infl - self.ox) / self.CELL)); i1 = min(self.nx - 1, int((x1 + infl - self.ox) / self.CELL))
            j0 = max(0, int((y0 - infl - self.oy) / self.CELL)); j1 = min(self.ny - 1, int((y1 + infl - self.oy) / self.CELL))
            for j in range(j0, j1 + 1):
                cy = self.oy + (j + 0.5) * self.CELL
                for i in range(i0, i1 + 1):
                    cx = self.ox + (i + 0.5) * self.CELL
                    if self.blk[j * self.nx + i]:
                        continue
                    if _pip(cx, cy, pts) or _edge_dist(cx, cy, pts) < infl + self.CELL * 0.35:
                        self.blk[j * self.nx + i] = 1
        self.path = []
        self.goal = None
        self.t_plan = -99.0

    def cell(self, x, y):
        return (min(max(int((x - self.ox) / self.CELL), 0), self.nx - 1), min(max(int((y - self.oy) / self.CELL), 0), self.ny - 1))

    def free(self, i, j):
        return 0 <= i < self.nx and 0 <= j < self.ny and not self.blk[j * self.nx + i]

    def snap(self, i, j):
        if self.free(i, j):
            return i, j
        for r in range(1, 8):
            for di in range(-r, r + 1):
                for dj in range(-r, r + 1):
                    if max(abs(di), abs(dj)) == r and self.free(i + di, j + dj):
                        return i + di, j + dj
        return None

    def astar(self, a, b, cap=1800):
        s = self.snap(*self.cell(*a)); g = self.snap(*self.cell(*b))
        if s is None or g is None:
            return None
        if s == g:
            return [b]
        openq = [(0.0, 0.0, s)]
        came = {s: None}; cost = {s: 0.0}
        n = 0
        bestn = (1e18, s)
        while openq and n < cap:
            _, c, cur = heapq.heappop(openq)
            if c > cost.get(cur, 1e18):
                continue
            n += 1
            hh = max(abs(g[0] - cur[0]), abs(g[1] - cur[1])) + 0.414 * min(abs(g[0] - cur[0]), abs(g[1] - cur[1]))
            if hh < bestn[0]:
                bestn = (hh, cur)
            if cur == g:
                break
            ci, cj = cur
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                ni, nj = ci + di, cj + dj
                if not self.free(ni, nj):
                    continue
                if di and dj and not (self.free(ci + di, cj) and self.free(ci, cj + dj)):
                    continue
                nc = c + (1.414 if di and dj else 1.0)
                if nc < cost.get((ni, nj), 1e18):
                    cost[(ni, nj)] = nc; came[(ni, nj)] = cur
                    h = max(abs(g[0] - ni), abs(g[1] - nj)) + 0.414 * min(abs(g[0] - ni), abs(g[1] - nj))
                    heapq.heappush(openq, (nc + h, nc, (ni, nj)))
        if g not in came:
            g = bestn[1]          # cap hit: head for the explored cell closest to the goal
            if g == s:
                return None
        pth = []; cur = g
        while cur is not None:
            pth.append((self.ox + (cur[0] + 0.5) * self.CELL, self.oy + (cur[1] + 0.5) * self.CELL)); cur = came[cur]
        pth.reverse()
        return pth

    def waypoint(self, pos, goal, t):
        """Next point to steer to (a few cells ahead on the planned path); straight line if planning fails."""
        d = math.hypot(goal[0] - pos[0], goal[1] - pos[1])
        if d < 14:
            return goal
        if (self.goal is None or math.hypot(goal[0] - self.goal[0], goal[1] - self.goal[1]) > 12 or t - self.t_plan > 2.0 or not self.path):
            self.path = self.astar(pos, goal) or []
            self.goal = goal; self.t_plan = t
        if not self.path:
            return goal
        # drop passed points
        while len(self.path) > 1 and math.hypot(self.path[0][0] - pos[0], self.path[0][1] - pos[1]) < 6.0:
            self.path.pop(0)
        k = min(3, len(self.path) - 1)
        return self.path[k]


def _edge_dist(x, y, pts):
    best = 1e9
    px, py = pts[-1]
    for qx, qy in pts:
        ex, ey = qx - px, qy - py
        L2 = ex * ex + ey * ey
        f = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, ((x - px) * ex + (y - py) * ey) / L2))
        d = math.hypot(x - (px + ex * f), y - (py + ey * f))
        if d < best:
            best = d
        px, py = qx, qy
    return best


def _pip(x, y, pts):
    c = False
    px, py = pts[-1]
    for qx, qy in pts:
        if (qy > y) != (py > y) and x < (px - qx) * (y - qy) / (py - qy) + qx:
            c = not c
        px, py = qx, qy
    return c


class Bot:
    name = "survivor-v2"

    def __init__(self, hello):
        c = hello["config"]
        self.c = c
        self.rng = random.Random(hello.get("seed", 1))
        mp = hello.get("map", {}).get("dir", "/arena")
        self.world = World(mp)
        self.mode = "fight"
        self.threats = {}       # id -> (pos, t_seen)
        self.last_hit_t = -99.0
        self.last_hit_bearing = None
        self.cover = None
        self.cover_t = -99.0
        self.strafe = 1
        self.strafe_t = 0.0
        self.stuck = 0
        self.unstick_until = -1.0
        self.unstick_dir = 1
        self.reach = c["loot"]["pickup_radius"]
        self.hist = {}
        self.dmg_log = []
        self.attackers = {}
        self.iso_pt = None
        self.iso_t = -99.0
        self.nav = None
        if P["nav"]:
            try:
                self.nav = Nav(self.world)
            except Exception as e:
                log("nav build failed", e)
        self.model = None
        self.last_feat = None
        try:
            self.model = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_model.json")))
        except Exception:
            pass

    # ---------- helpers ----------
    def upgrade_pick(self, offer):
        pref = (["plating", "armor"] + UPG_PREF[2:]) if P["plating"] else UPG_PREF
        if P["upg_dmg"]:
            pref = ["laser_damage", "gun_damage", "gun_rate", "lightning_efficiency", "laser_charge", "plating", "nanites",
                    "armor", "lightning_range", "gyros", "gun_velocity", "gun_mag", "lightning_chain", "sensors", "capacitor",
                    "reactor", "servos", "jets", "mortar_reload", "mortar_velocity", "mortar_splash", "laser_pierce"]
        best, rank = 0, 999
        for i, ch in enumerate(offer.get("choices", [])):
            cid = ch.get("id", "")
            r = pref.index(cid) if cid in pref else 500
            if r < rank:
                best, rank = i, r
        return best

    def hostile(self, m, me, t):
        """True if this mech is after us: it hit us recently, aims at us, is charging a laser, or is closing in fast."""
        if t - self.attackers.get(m["id"], -99.0) < 10.0:
            return True
        x, y = me["pos"][0], me["pos"][1]
        dx, dy = x - m["pos"][0], y - m["pos"][1]
        d = math.hypot(dx, dy)
        if d < 35.0 or m.get("charging"):
            return True
        if d < 230.0 and abs(ang_diff(m["aim"][0], math.atan2(dy, dx))) < 0.28:
            return True
        vx, vy = m["vel"][0], m["vel"][1]
        if d < 170.0 and (vx * dx + vy * dy) / max(d, 1.0) > 4.0:
            return True
        return False

    def iso_spot(self, obs, me, target, others, t):
        """Candidate positions around us: want LOS to target, hidden from all other known mechs, near the distance band."""
        x, y, z = me["pos"]
        eye = me["stats"].get("eye_height", 8.0)
        tp = target["pos"]
        best = None
        for rad in (0.0, 6.0, 12.0):
            for k in range(12 if rad else 1):
                a = k * TAU / 12
                cx, cy = x + rad * math.cos(a), y + rad * math.sin(a)
                if rad and not self.safe_point(obs, cx, cy):
                    continue
                g = self.world.ground(cx, cy)
                if rad and self.world.inside(cx, cy, g + 1.0):
                    continue
                if rad and self.world.blocked((x, y, z + 2.0), (cx, cy, g + 2.0)):
                    continue
                sc = -0.35 * rad
                if self.world.blocked((cx, cy, g + eye), (tp[0], tp[1], tp[2] + 4.5)):
                    sc -= 60.0
                for o in others:
                    if self.world.blocked((o[0], o[1], o[2] + 8.0), (cx, cy, g + 6.0)) is False:
                        sc -= P["iso_watch"]
                dd = math.hypot(tp[0] - cx, tp[1] - cy)
                if dd > P["band_max"]:
                    sc -= (dd - P["band_max"]) * 0.4
                elif dd < P["band_min"]:
                    sc -= (P["band_min"] - dd) * 0.8
                if self.iso_pt and math.hypot(cx - self.iso_pt[0], cy - self.iso_pt[1]) < 4.0:
                    sc += 6.0
                if best is None or sc > best[0]:
                    best = (sc, (cx, cy))
        return best[1] if best else None

    def drop_target(self, obs, x, y, mechs):
        for dr in obs.get("drops", []):
            if dr.get("lands_in", 99) > 3 or math.dist(dr["pos"][:2], (x, y)) > 150:
                continue
            if any(math.dist(m["pos"][:2], dr["pos"][:2]) < dr.get("radius", 8) + 20 for m in mechs):
                continue
            if self.safe_point(obs, dr["pos"][0], dr["pos"][1]):
                return (dr["pos"][0], dr["pos"][1])
        return None

    def want_kind(self, kind):
        return bool(P["wpn"]) and not P.get("no_" + kind, 0)

    def zone_goal(self, obs):
        z = obs["zone"]
        return z["next_center"], z["next_radius"]

    def safe_point(self, obs, x, y):
        (nx, ny), nr = self.zone_goal(obs)
        z = obs["zone"]
        t = obs["t"]
        # before shrink starts the current circle is safe; be inside next circle when shrink is close
        lim = nr * 0.92 if t > z["shrink_start"] - P["zlead"] else z["radius"] * 0.92
        cx, cy = (nx, ny) if t > z["shrink_start"] - P["zlead"] else z["center"]
        return math.hypot(x - cx, y - cy) < max(lim, 3.0)

    def aim_at(self, me, tgt, speed):
        mx, my, mz = me["pos"]
        mh = me["stats"].get("muzzle_height", 7.0)
        tx, ty, tz = tgt["pos"]
        vx, vy, vz = tgt["vel"]
        if abs(vz) < 1.0:
            vz = 0.0
        size = 1.0 + 0.05 * tgt.get("cubes", 0)
        th = 4.5 * size
        ax = ay = 0.0
        if P["predict"] and tgt.get("id") in self.hist:
            ax, ay = self.hist[tgt["id"]][2]
        t = 0.0
        for _ in range(3):
            tc = min(t, 0.7)
            px, py, pz = tx + vx * t + 0.5 * ax * tc * tc, ty + vy * t + 0.5 * ay * tc * tc, tz + th + vz * t
            d = math.dist((px, py, pz), (mx, my, mz + mh))
            t = d / speed
        dxy = math.hypot(px - mx, py - my)
        return math.atan2(py - my, px - mx), math.atan2(pz - (mz + mh), max(dxy, 0.1)), dxy, (px, py, pz)

    def los(self, me, p):
        mx, my, mz = me["pos"]
        return not self.world.blocked((mx, my, mz + me["stats"].get("eye_height", 8.0)), p)

    def find_cover(self, obs, me, threats):
        mx, my, mz = me["pos"]
        threats = sorted(threats, key=lambda p: math.dist(p[:2], (mx, my)))[:3]
        best = None
        for rad in (10.0, 20.0, 32.0, 48.0):
            for k in range(16):
                a = k * TAU / 16
                x, y = mx + rad * math.cos(a), my + rad * math.sin(a)
                if not self.safe_point(obs, x, y):
                    continue
                g = self.world.ground(x, y)
                if self.world.inside(x, y, g + 1.0):
                    continue
                if self.world.blocked((mx, my, mz + 2.0), (x, y, g + 2.0)):
                    continue  # not walkable in a straight line
                hidden = 0
                for tp in threats:
                    if self.world.blocked((tp[0], tp[1], tp[2] + 8.0), (x, y, g + 6.0)):
                        hidden += 1
                if hidden < len(threats):
                    continue
                cost = rad
                if best is None or cost < best[0]:
                    best = (cost, (x, y))
            if best:
                break
        return best[1] if best else None

    # ---------- main ----------
    def act(self, obs):
        me = obs["self"]
        x, y, z = me["pos"]
        t = obs["t"]
        hpf = me["hp"] / max(me["max_hp"], 1)
        act = {"tick": obs["tick"]}
        if obs.get("offer"):
            act["pick"] = self.upgrade_pick(obs["offer"])

        for e in obs.get("events", []):
            if e.get("type") == "damaged" and e.get("by") is not None:
                self.last_hit_t = t
                self.dmg_log.append((t, e.get("amount", 0.0)))
                self.attackers[e["by"]] = t
                self.last_hit_bearing = e.get("bearing")
                if e["by"] not in self.threats and e.get("bearing") is not None:
                    b = e["bearing"]
                    self.threats[e["by"]] = ((x + 70 * math.cos(b), y + 70 * math.sin(b), z), t)

        mechs = [m for m in obs.get("mechs", []) if m["kind"] == "mech"]
        for m in mechs:
            self.threats[m["id"]] = (tuple(m["pos"]), t)
        for k in [k for k, v in self.threats.items() if t - v[1] > 8.0]:
            del self.threats[k]
        for m in mechs:
            h = self.hist.get(m["id"])
            if h is not None and t > h[0]:
                dt = t - h[0]
                a = ((m["vel"][0] - h[1][0]) / dt, (m["vel"][1] - h[1][1]) / dt)
                a = (max(-25.0, min(25.0, a[0])), max(-25.0, min(25.0, a[1])))
                pa = h[2]
                k = P["predict_k"]
                self.hist[m["id"]] = (t, (m["vel"][0], m["vel"][1]), (pa[0] * (1 - k) + a[0] * k, pa[1] * (1 - k) + a[1] * k))
            elif h is None:
                self.hist[m["id"]] = (t, (m["vel"][0], m["vel"][1]), (0.0, 0.0))
        threat_pos = [v[0] for v in self.threats.values()]
        threatened = bool(threat_pos) and (t - self.last_hit_t < 6.0 or any(math.dist(p[:2], (x, y)) < 120 for p in threat_pos))

        # features for the learned engage/retreat model
        near = [p for p in threat_pos if math.dist(p[:2], (x, y)) < 150]
        nd = min([math.dist(p[:2], (x, y)) for p in threat_pos] or [250.0])
        rear = 0.0
        if threat_pos:
            tp0 = min(threat_pos, key=lambda p: math.dist(p[:2], (x, y)))
            rear = 1.0 if abs(ang_diff(math.atan2(tp0[1] - y, tp0[0] - x), me["aim"][0])) > math.pi / 2 else 0.0
        g0 = me["weapons"][0]
        evis = [m for m in mechs]
        ehp = (min(m.get("hp", 1400) / max(m.get("max_hp", 1400), 1) for m in evis) if evis else 1.0)
        self.last_feat = [hpf, min(len(near), 4) / 4.0, min(nd, 250.0) / 250.0, (g0.get("ammo", 12) if g0 else 0) / 12.0,
                          min(me["cubes"], 10) / 10.0, 1.0 if self.safe_point(obs, x, y) else 0.0, t / 480.0, rear,
                          1.0 if t - self.last_hit_t < 2.0 else 0.0, ehp, 1.0]
        ml_danger = False
        if P["ml"] and self.model and threatened:
            try:
                zz = sum(w * f for w, f in zip(self.model["w"], self.last_feat))
                ml_danger = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, zz)))) > P["ml_thr"]
            except Exception:
                pass

        # mode switching
        if P["ml"] and self.model:
            if self.mode == "fight" and ml_danger:
                self.mode = "retreat"; self.cover_t = -99
        elif self.mode == "fight" and hpf < P["low_hp"] and threatened:
            fin = False
            if P["finish"] and mechs:
                nm = min(mechs, key=lambda m: math.dist(m["pos"], me["pos"]))
                fin = math.dist(nm["pos"][:2], (x, y)) < 120 and nm.get("hp", 1400) <= min(280.0, me["hp"] * 0.52)
            if not fin:
                self.mode = "retreat"; self.cover_t = -99
        elif self.mode == "retreat" and (hpf >= P["high_hp"] or not threat_pos):
            self.mode = "fight"
        if P["multi_flee"] and self.mode == "fight" and hpf < 0.85:
            if sum(1 for p in threat_pos if math.dist(p[:2], (x, y)) < 150) >= 2:
                self.mode = "retreat"; self.cover_t = -99
        if P["burst"] and self.mode == "fight":
            self.dmg_log = [d for d in self.dmg_log if t - d[0] < 1.7]
            if sum(d[1] for d in self.dmg_log) > 240 and hpf < 0.74:
                self.mode = "retreat"; self.cover_t = -99
        _g = me["weapons"][0]
        if P["reload_cover"] and self.mode == "fight" and threatened and _g and _g.get("ammo", 12) <= 3:
            self.mode = "retreat"; self.cover_t = -99

        slots = me["weapons"]
        gun = slots[0] if slots[0] and slots[0]["kind"] == "gun" else None
        gspeed = (gun or {}).get("stats", {}).get("speed", 252.0)

        # ----- target selection (visible, line of sight) -----
        target = None
        best = None
        for m in mechs:
            yaw, pitch, dxy, aimp = self.aim_at(me, m, gspeed)
            if dxy > P["fire_range"] + 40:
                continue
            if P["selective"] and not self.hostile(m, me, t):
                continue
            vis = self.los(me, (m["pos"][0], m["pos"][1], m["pos"][2] + 4.5))
            score = dxy + (m.get("hp", 1400) / 15.0) + (0 if vis else 400)
            if P["stick"] and m["id"] == getattr(self, "last_target", None) and vis:
                score -= 150
            if best is None or score < best[0]:
                best = (score, m, yaw, pitch, dxy, vis)
        if best:
            _, target, tyaw, tpitch, tdist, tvis = best
        farm = None
        if (target is None and P["farm"] and t < P["farm_until"] and hpf > 0.6
                and not (self.mode == "retreat")):
            cands = [(m, 1.75) for m in obs.get("mechs", []) if m["kind"] == "npc"] + \
                    [(c, 0.8) for c in obs.get("crates", [])]
            fb = None
            for o, hh in cands:
                ox, oy, oz = o["pos"]
                d = math.hypot(ox - x, oy - y)
                if d > 140 or not self.safe_point(obs, ox, oy):
                    continue
                if not self.los(me, (ox, oy, oz + hh)):
                    continue
                if fb is None or d < fb[0]:
                    fb = (d, o, hh)
            if fb:
                d, o, hh = fb
                fake = {"pos": o["pos"], "vel": o.get("vel", [0, 0, 0]), "cubes": 0}
                yaw, pitch, dxy, _ = self.aim_at(me, fake, gspeed)
                # aim_at targets +4.5 m; correct pitch for the object's centre height
                mh = me["stats"].get("muzzle_height", 7.0)
                pitch = math.atan2(o["pos"][2] + hh - (z + mh), max(dxy, 0.1))
                farm = (o, yaw, pitch, dxy)

        # ----- movement goal -----
        (gx, gy), nr = self.zone_goal(obs)
        zone = obs["zone"]
        in_safe = self.safe_point(obs, x, y)
        d_goal = math.hypot(gx - x, gy - y)
        urgent = (not me["in_zone"]) or not in_safe
        move = [0.0, 0.0]
        want = None
        boost_close = False
        label = self.mode

        if urgent:
            want = (gx, gy); label = "zone"
        elif P["dropheal"] and hpf < 0.7 and self.drop_target(obs, x, y, mechs):
            want = self.drop_target(obs, x, y, mechs); label = "dropheal"
        elif self.mode == "retreat":
            if t - self.cover_t > 1.0:
                self.cover = self.find_cover(obs, me, threat_pos)
                self.cover_t = t
            if self.cover:
                want = self.cover
            elif threat_pos:
                # run directly away from the nearest threat, toward the zone centre
                tp = min(threat_pos, key=lambda p: math.dist(p[:2], (x, y)))
                ax, ay = x - tp[0], y - tp[1]
                n = math.hypot(ax, ay) or 1
                want = (x + ax / n * 30 + (gx - x) * 0.1, y + ay / n * 30 + (gy - y) * 0.1)
        elif P["late_hold"] and zone.get("next_radius", 99) <= 80 and (target is None or tdist > 70):
            want = (gx, gy) if d_goal > max(nr * 0.5, 4.0) else None
            label = "hold"
        elif target is not None:
            # fight: hold the distance band and strafe
            ux, uy = math.cos(tyaw), math.sin(tyaw)
            if t > self.strafe_t:
                self.strafe = -self.strafe
                self.strafe_t = t + self.rng.uniform(1.2, 2.8)
            mvx, mvy = -uy * self.strafe * 0.8, ux * self.strafe * 0.8
            bmin, bmax = P["band_min"], P["band_max"]
            if P["bandw"]:
                kinds_ = {w["kind"] for w in slots if w}
                if "lightning" in kinds_:
                    bmin, bmax = 15.0, 45.0
                elif "laser" in kinds_:
                    bmin, bmax = 55.0, 100.0
            if tdist > bmax or not tvis:
                mvx += ux; mvy += uy
                if P["boostclose"] and tvis and tdist > bmax + 15 and me["energy"] > 40:
                    boost_close = True
            elif tdist < bmin:
                mvx -= ux * 0.7; mvy -= uy * 0.7
            nx_, ny_ = x + mvx * 10, y + mvy * 10
            if not self.safe_point(obs, nx_, ny_):
                mvx += (gx - x) / max(d_goal, 1) * 1.5; mvy += (gy - y) / max(d_goal, 1) * 1.5
            move = [mvx, mvy]
            if P["iso"] and tvis and tdist <= bmax + 20:
                if t - self.iso_t > 0.3:
                    others = [p for i, p in ((k, v[0]) for k, v in self.threats.items()) if i != target["id"] and math.dist(p[:2], (x, y)) < 220]
                    self.iso_pt = self.iso_spot(obs, me, target, others, t)
                    self.iso_t = t
                if self.iso_pt and math.hypot(self.iso_pt[0] - x, self.iso_pt[1] - y) > 2.5:
                    move = [(self.iso_pt[0] - x) * 1.0 + mvx * 2.0, (self.iso_pt[1] - y) * 1.0 + mvy * 2.0]
                    if tdist < bmin:
                        move = [move[0] - ux * 6.0, move[1] - uy * 6.0]
        elif farm is not None and farm[3] > 35:
            want = (farm[0]["pos"][0], farm[0]["pos"][1]); label = "farm"
        else:
            # no visible enemy: loot, drops, or go to the zone goal
            best_l = None
            if P["opening"] and t < 40 and slots[1] is None and not urgent:
                for p in obs.get("pickups", []):
                    if p["kind"] not in ("laser", "lightning"):
                        continue
                    dd = math.dist(p["pos"][:2], (x, y))
                    if dd < 250 and self.safe_point(obs, p["pos"][0], p["pos"][1]):
                        sc = dd - (40 if p["kind"] == "laser" else 0)
                        if best_l is None or sc < best_l[0]:
                            best_l = (sc, p["pos"])
            if P["wpn_threat"] and threatened and hpf > 0.6 and not urgent:
                for p in obs.get("pickups", []):
                    if p["kind"] == "gun" or slots[1] is not None or not self.want_kind(p["kind"]):
                        continue
                    dd = math.dist(p["pos"][:2], (x, y))
                    if dd < (P["wpn_r"] or P["loot_r"]) and abs(p["pos"][2] - z) < 6 and self.safe_point(obs, p["pos"][0], p["pos"][1]):
                        if best_l is None or dd < best_l[0]:
                            best_l = (dd, p["pos"])
            if not threatened:
                for c in obs.get("cubes", []):
                    dd = math.dist(c["pos"][:2], (x, y))
                    if dd < P["loot_r"] and self.safe_point(obs, c["pos"][0], c["pos"][1]):
                        if best_l is None or dd < best_l[0]:
                            best_l = (dd, c["pos"])
                empty = slots[1] is None
                for p in obs.get("pickups", []):
                    if p["kind"] == "gun" or not empty or not self.want_kind(p["kind"]):
                        continue
                    dd = math.dist(p["pos"][:2], (x, y))
                    if dd < (P["wpn_r"] or P["loot_r"]) and abs(p["pos"][2] - z) < 6 and self.safe_point(obs, p["pos"][0], p["pos"][1]):
                        if best_l is None or dd - 20 < best_l[0]:
                            best_l = (dd - 20, p["pos"])
                if P["drops"] > 0:
                    for dr in obs.get("drops", []):
                        dd = math.dist(dr["pos"][:2], (x, y))
                        if dd < 150 and dr.get("lands_in", 99) < dd / 11.0 + 3 and self.safe_point(obs, dr["pos"][0], dr["pos"][1]):
                            if best_l is None or dd - 60 < best_l[0]:
                                best_l = (dd - 60, dr["pos"])
            if best_l:
                want = (best_l[1][0], best_l[1][1]); label = "loot"
            elif P["hunt"] and hpf > 0.75 and threat_pos and not urgent and \
                    min(math.dist(p[:2], (x, y)) for p in threat_pos) < 160:
                tp = min(threat_pos, key=lambda p: math.dist(p[:2], (x, y)))
                want = (tp[0], tp[1]); label = "hunt"
            elif d_goal > max(nr * P["goal_frac"], 3.0):
                want = (gx, gy)
            elif self.mode == "fight" and hpf < 0.99 and threatened:
                pass  # hold still (silent) and regen
        if want is not None:
            if self.nav is not None and label != "hunt":
                try:
                    wp = self.nav.waypoint((x, y), want, t)
                except Exception:
                    wp = want
                move = [wp[0] - x, wp[1] - y]
            else:
                move = [want[0] - x, want[1] - y]

        if target is not None:
            self.last_target = target["id"]

        # ----- dodge incoming fire -----
        if P["dodge"] and not urgent:
            mh = me["stats"].get("height", 9.0)
            for pr in obs.get("projectiles", []):
                px, py, pz = pr["pos"]; vx, vy, vz = pr["vel"]
                v2 = vx * vx + vy * vy
                if v2 < 1:
                    continue
                tc = ((x - px) * vx + (y - py) * vy) / v2
                if 0 < tc < 0.8:
                    cx_, cy_ = px + vx * tc - x, py + vy * tc - y
                    if math.hypot(cx_, cy_) < 4.0:
                        sgn = 1 if (cx_ * -vy + cy_ * vx) < 0 else -1
                        sp = math.sqrt(v2)
                        move = [move[0] * 0.3 + sgn * -vy / sp, move[1] * 0.3 + sgn * vx / sp]
                        break
            for m in mechs:
                if m.get("charging"):
                    ay = math.atan2(y - m["pos"][1], x - m["pos"][0])
                    if abs(ang_diff(m["aim"][0], ay)) < 0.08:
                        move = [move[0] * 0.3 - math.sin(ay) * self.strafe, move[1] * 0.3 + math.cos(ay) * self.strafe]
                        act["jump"] = True
                        break

        # ----- end game: sit on the final centre -----
        if P["endgame"] and zone.get("next_radius", 99) <= 0.5 and t > zone["shrink_start"] - 10:
            dd = math.hypot(gx - x, gy - y)
            move = [gx - x, gy - y] if dd > 1.0 else [0.0, 0.0]

        # ----- take weapons in reach -----
        for p in obs.get("pickups", []):
            if p["kind"] == "gun" or not self.want_kind(p["kind"]):
                continue
            if math.dist(p["pos"][:2], (x, y)) <= self.reach and abs(p["pos"][2] - z) < 4:
                if slots[1] is None:
                    act["take"] = p["id"]; break
                if P["wpn_swap"] and p["kind"] == "laser" and slots[1] and slots[1]["kind"] != "laser":
                    act["take"] = p["id"]; act["drop"] = 1; break

        # ----- aim and fire -----
        fire = [False, False]
        aim = None
        cur_yaw, cur_pitch = me["aim"]
        if target is not None:
            aim = [tyaw, tpitch]
            tol = math.atan2(2.2 * (1 + 0.05 * target.get("cubes", 0)), max(tdist, 1)) + 0.004
            err_y = abs(ang_diff(tyaw, cur_yaw)); err_p = abs(tpitch - cur_pitch)
            on = err_y < tol and err_p < tol * 1.5
            hold_fire = self.mode == "retreat" and tdist > 40 and t - self.last_hit_t > 1.0
            if tvis and not hold_fire:
                if gun and on and tdist < gun.get("stats", {}).get("range", 230) and gun.get("ammo", 1) > 0:
                    fire[0] = True
                s1 = slots[1]
                if s1:
                    st = s1.get("stats", {})
                    k = s1["kind"]
                    if k == "lightning":
                        if tdist < st.get("range", 45) * 0.95 and err_y < math.radians(st.get("cone_deg", 30)) * 0.4 and me["energy"] > 10:
                            fire[1] = True
                    elif k == "laser":
                        full = st.get("charge", 0.75)
                        ch = s1.get("charge", 0) or 0
                        if tdist < min(st.get("range", 280), P["laser_rng"]):
                            dmg_now = st.get("damage", 315.0) * (st.get("min_frac", 0.35) + (1 - st.get("min_frac", 0.35)) * min(1.0, ch / max(full, 0.01)))
                            if P["lethal"] and ch >= st.get("min_charge", 0.15) and on and dmg_now >= 1.15 * target.get("hp", 1400):
                                fire[1] = False
                            elif ch < full * P["laser_hold"]:
                                fire[1] = s1.get("cooldown", 0) <= 0.05 or ch > 0
                            else:
                                fire[1] = not on  # release when on target
                    elif k == "mortar" and 20 < tdist < 230:
                        v = st.get("speed", 72.0); g = st.get("gravity", 22.0)
                        h = target["pos"][2] - (z + 9.5)
                        disc = v ** 4 - g * (g * tdist * tdist + 2 * h * v * v)
                        if disc > 0:
                            th = math.atan((v * v - math.sqrt(disc)) / (g * tdist))
                            ft = tdist / (v * math.cos(th))
                            lx = target["pos"][0] + target["vel"][0] * ft
                            ly = target["pos"][1] + target["vel"][1] * ft
                            myaw = math.atan2(ly - y, lx - x)
                            if not fire[0] and gun is None or (gun and gun.get("ammo", 0) == 0) or tdist > 120:
                                aim = [myaw, th]
                                if abs(ang_diff(myaw, cur_yaw)) < 0.04 and abs(th - cur_pitch) < 0.05:
                                    fire[1] = True
        elif farm is not None:
            o, fyaw, fpitch, fd = farm
            aim = [fyaw, fpitch]
            tol = math.atan2(1.2, max(fd, 1)) + 0.004
            if gun and abs(ang_diff(fyaw, cur_yaw)) < tol and abs(fpitch - cur_pitch) < tol * 1.5 and gun.get("ammo", 1) > 0:
                fire[0] = True
            s1 = slots[1]
            if s1 and s1["kind"] == "lightning" and fd < 40 and abs(ang_diff(fyaw, cur_yaw)) < 0.2 and me["energy"] > 30:
                fire[1] = True
        else:
            # face the most recent threat to protect the rear, else look where we walk
            if threat_pos:
                tp = min(threat_pos, key=lambda p: math.dist(p[:2], (x, y)))
                aim = [math.atan2(tp[1] - y, tp[0] - x), 0.0]
            elif self.last_hit_bearing is not None and t - self.last_hit_t < 4:
                aim = [self.last_hit_bearing, 0.0]
            else:
                heard = [s for s in obs.get("sounds", []) if s.get("kind") in ("gun", "laser", "lightning", "step", "boost", "laser_charge") and s.get("dist") != "far"]
                if heard:
                    aim = [heard[0]["bearing"], 0.0]
                elif math.hypot(*move) > 0.1:
                    aim = [math.atan2(move[1], move[0]), 0.0]
            # reload while nobody is in sight
            if gun and gun.get("ammo", 99) < gun.get("stats", {}).get("mag", 12) and gun.get("reload", 0) <= 0:
                act["reload"] = True
        if gun and gun.get("ammo", 1) <= 0 and gun.get("reload", 0) <= 0:
            act["reload"] = True
        if self.mode == "retreat" and gun and gun.get("ammo", 12) < gun.get("stats", {}).get("mag", 12) and gun.get("reload", 0) <= 0 and (target is None or tdist > 60):
            act["reload"] = True
        act["fire"] = fire

        # ----- movement output, unstick -----
        n = math.hypot(*move)
        if n > 1e-6:
            move = [move[0] / n, move[1] / n]
        else:
            move = [0.0, 0.0]
        speed = math.hypot(me["vel"][0], me["vel"][1])
        if n > 0.3 and speed < 1.5 and me.get("grounded", True):
            self.stuck += 1
        else:
            self.stuck = max(0, self.stuck - 1)
        boost = False
        if self.stuck >= 4:
            act["jump"] = True
            boost = True
            if self.stuck >= 8 and t > self.unstick_until:
                self.unstick_until = t + 1.2
                self.unstick_dir = -self.unstick_dir
        if t < self.unstick_until:
            a = math.atan2(move[1], move[0]) + self.unstick_dir * 1.2
            move = [math.cos(a), math.sin(a)]
        if not me.get("grounded", True) and self.stuck >= 4:
            boost = me["energy"] > 5
        if urgent or self.mode == "retreat":
            boost = boost or me["energy"] > 25
        if boost_close:
            boost = True
        act["move"] = move
        act["boost"] = boost
        if aim:
            act["aim"] = [aim[0], max(-0.69, min(1.29, aim[1]))]
        mf.draw.label(f"{label} hp{hpf:.2f} th{len(threat_pos)}")
        return act


if __name__ == "__main__":
    mf.run(Bot)
