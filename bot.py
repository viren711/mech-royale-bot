"""Team Inventors' Mech Royale bot (protocol mechfight/1).

Legs and torso are decided separately every observation:
  legs  - zone safety > dodging shells > retreat to cover > fight dance > loot > roam
  torso - aim (with lead) and fire at the best visible target, else look around
All rule numbers come from hello.config / the observation; the map comes from hello.map.
"""
from __future__ import annotations

import gc
import math
import random

import mechfight as mf
from world import Search, World

PI = math.pi
STYLE = "berserk"  # "berserk" (never retreats), "normal", "smart" (disengage only when clearly losing), "pacifist"
RANGE = "far"  # fight distance: "far" (FAR_M, scored best), "auto" (by loadout) or "close" (35 m)
FAR_M = 110.0
LOOT_IN_FIGHT = True  # walk to a known better weapon even while enemies are in sight
FETCH_M = 110.0  # how far to go for a better weapon mid-fight
FARM_HP = 0.75  # shoot crates and drones only above this HP fraction
GREEDY = False  # mid-fight, walk to crates and spend gun fire on crates/drones for cubes while the enemy is far
JINK = False  # flip strafe direction once per enemy bullet flight time, instead of at random 0.3-0.9 s
LEAD_EMA = True  # lead far targets by their averaged velocity; False = always their current velocity
PEACE_T = 0.0  # diagnostic only: hide and hold fire at mechs until this many seconds, then fight normally
STOP_T = None  # diagnostic only: stand still after this many seconds, so the score shows kills made by then
CUBE_M = 30.0  # mid-fight, go for visible cubes within this distance
KILL_LOOT = False  # after a kill, run to where the victim died to collect its cubes (and weapons)
CORNER = False  # with several enemies in sight, stand where buildings hide us from all but the target
DROPS = "smart"  # supply drops: "on" (go early, wait in the ring), "smart" (no long waits, give up if stuck), "off"
ZONE_JET = False  # outside the zone and not closing on it: fly straight in over whatever is in the way
SEEK = False  # nobody in sight: walk toward the last weapon sound heard instead of farming or roaming
LASER_FIRST = True  # take laser upgrades before HP and armor (scored best)
REST = False  # between fights: no crate/drone shooting (it resets regen), hold still out of sight until healed
REST_HP = 0.92
GATE = False  # only fight house bots that are already engaging us (close, hit us, closing in, aiming at us, nearly dead)
FINISH = False  # close to 20 m on a weak target; release the laser early once the charge already kills
IDLE_STILL = False  # nothing to fetch: stand still (silent) and spin the torso for all-round vision instead of roaming
FIGHT_BOOST = False  # boost-strafe in fights, with energy hysteresis (stop at 28%, resume at 70%)
CUBE_HURT_M = 30.0  # mid-fight cube radius when at or below half HP
LASER_DODGE = False  # an enemy laser is charging at us: boost sideways out of its line, reversing halfway
LASER_FIRST_TARGET = False  # prefer shooting enemies that carry a laser (lasers did ~3/4 of damage taken in the recorded match)
PURSUE = False  # walk to where a mech was last seen instead of roaming
WEAPON_RANK = {"laser": 3, "lightning": 2, "mortar": 1}
if RANGE == "close":
    WEAPON_RANK = {"lightning": 3, "laser": 2, "mortar": 1}
UPGRADE_ORDER = [
    "plating", "armor", "laser_damage", "gun_damage", "nanites", "laser_charge", "gun_rate",
    "lightning_efficiency", "servos", "gun_velocity", "gyros", "gun_mag", "lightning_chain",
    "reactor", "lightning_range", "capacitor", "mortar_reload", "mortar_splash", "mortar_velocity",
    "sensors", "jets", "laser_pierce",
]


def wrap(a: float) -> float:
    return (a + PI) % (2 * PI) - PI


def intercept(dx, dy, dz, vx, vy, vz, speed):
    """Time for a straight shot at `speed` to meet a target at offset d moving at v (0 if none)."""
    a = vx * vx + vy * vy + vz * vz - speed * speed
    b = 2 * (dx * vx + dy * vy + dz * vz)
    c = dx * dx + dy * dy + dz * dz
    if abs(a) < 1e-6:
        return -c / b if b < 0 else 0.0
    disc = b * b - 4 * a * c
    if disc < 0:
        return 0.0
    r = math.sqrt(disc)
    t1, t2 = (-b - r) / (2 * a), (-b + r) / (2 * a)
    ts = [t for t in (t1, t2) if t > 0]
    return min(ts) if ts else 0.0


class Bot:
    name = "inventors"

    def __init__(self, hello: mf.Hello):
        cfg = hello["config"]
        self.cfg = cfg
        self.rng = random.Random(hello.get("seed", 1))
        self.take_r = cfg["loot"]["pickup_radius"]
        self.cube_r = cfg["cubes"]["pickup_radius"]
        self.size_per_cube = cfg["cubes"].get("size_per_cube", 0.05)
        self.mech_h = cfg["mech"]["height"]
        self.mech_r = cfg["mech"]["radius"]
        self.npc_h = cfg["npc"].get("height", 3.5)
        self.npc_r = cfg["npc"].get("radius", 1.8)
        self.crate_h = cfg["crates"].get("height", 2.4)
        self.crate_r = cfg["crates"].get("radius", 1.4)
        self.world = None
        try:
            self.world = World(hello["map"]["dir"], hello["map"].get("files", []))
        except Exception as e:  # no map: steer straight, still a legal bot
            mf.log(f"map not loaded ({e!r}); navigating blind")
        self.tracks = {}  # id -> dict for mechs and NPCs
        self.pickups = {}  # id -> (kind, pos, t_seen)
        self.crates = {}  # id -> (pos, t_seen)
        self.bad_pickups = set()
        self.path = None
        self.path_goal = None
        self.path_t = -1e9
        self.search = None
        self.search_goal = None
        self.strafe = 1.0
        self.strafe_until = 0.0
        self.retreat = False
        self.cover = None
        self.cover_t = -1e9
        self.look_yaw = None
        self.look_until = -1.0
        self.roam = None
        self.roam_t = -1e9
        self.stuck_t = 0.0
        self.unstick_until = -1.0
        self.unstick_dir = (0.0, 0.0)
        self.last_threat_t = -1e9
        self.last_hurt_t = -1e9
        self.laser_hold_t = None
        self.jink_tof = 0.0
        self.kill_spots = []
        self.spot = None
        self.hit_by = {}  # mech id -> last time it damaged us
        self.charge_seen = {}  # mech id -> time we first saw its laser charging
        self.dodge_side = 1.0
        self.boost_ok = True
        self.heard = None  # (x, y, t, rank) of the best recent sound made by someone we cannot see
        self.drop_ring_t = 0.0
        self.bad_drops = set()
        self.out_since = None
        self.out_d0 = 0.0
        self.spot_t = -1e9
        gc.collect()
        gc.freeze()

    # ------------------------------------------------------------------ navigation
    def nav(self, x, y, gx, gy, t):
        """Unit move vector that walks around buildings toward (gx, gy)."""
        w = self.world
        dx, dy = gx - x, gy - y
        d = math.hypot(dx, dy)
        if d < 0.5:
            return 0.0, 0.0
        if w is None or (d < 60 and w.walk_clear(x, y, gx, gy, 3.0)):
            return dx / d, dy / d
        pg = self.path_goal
        need = self.path is None or pg is None or math.hypot(pg[0] - gx, pg[1] - gy) > max(8.0, 0.15 * d) or t - self.path_t > 4.0
        if need and self.search is None:
            a, b = w.nearest_free(x, y), w.nearest_free(gx, gy)
            if a >= 0 and b >= 0:
                self.search, self.search_goal = Search(w, a, b), (gx, gy)
        if self.search is not None and self.search.step(700):
            if self.search.path:
                self.path = self.search.path
            elif need:
                self.path = None
            self.path_goal, self.path_t, self.search = self.search_goal, t, None
        path = self.path
        if not path:
            return dx / d, dy / d
        # drop waypoints already reached, then head for the furthest one in a straight clear walk
        while len(path) > 1 and math.hypot(path[0][0] - x, path[0][1] - y) < 3.5:
            path.pop(0)
        best = 0
        for k in range(min(len(path) - 1, 7), 0, -1):
            if w.walk_clear(x, y, path[k][0], path[k][1], 3.0):
                best = k
                break
        if best > 0:
            del path[:best]
        tx, ty = path[0]
        dd = math.hypot(tx - x, ty - y)
        if len(path) == 1 and dd < 2.0 and not w.free(gx, gy):
            return 0.0, 0.0  # the goal itself is inside a wall: this is as close as it gets
        if dd < 1e-6:
            return dx / d, dy / d
        return (tx - x) / dd, (ty - y) / dd

    def hidden_from(self, px, py, threats):
        w = self.world
        return w is not None and all(not w.los(e["pos"][0], e["pos"][1], px, py) for e in threats)

    def find_cover(self, x, y, threats, zone_ok):
        """Nearest walkable spot no threat can see, or None."""
        w = self.world
        if w is None or not threats:
            return None
        best, bs = None, 1e18
        ex, ey = threats[0]["pos"][0], threats[0]["pos"][1]
        for r in (6.0, 12.0, 20.0, 30.0, 42.0, 56.0):
            n = 8 if r < 10 else 14
            off = self.rng.random() * 2 * PI
            for k in range(n):
                a = off + 2 * PI * k / n
                px, py = x + r * math.cos(a), y + r * math.sin(a)
                if not w.free(px, py) or not zone_ok(px, py) or not self.hidden_from(px, py, threats):
                    continue
                s = r + (0.0 if w.walk_clear(x, y, px, py, 3.0) else 0.6 * r) - 0.25 * math.hypot(px - ex, py - ey)
                if s < bs:
                    best, bs = (px, py), s
            if best is not None and r >= 20.0:
                break
        return best

    # ------------------------------------------------------------------ aiming
    def aim_at(self, mx, my, mz, tr, speed, t_lead=None):
        """[yaw, pitch], distance and time of flight to hit track `tr` from muzzle (mx, my, mz)."""
        px, py, pz = tr["pos"]
        pz += tr["ch"]
        dx, dy, dz = px - mx, py - my, pz - mz
        if speed is None:
            tof = t_lead or 0.0
            vx, vy, vz = tr["vel"]
        else:
            vx, vy, vz = tr["vel"]
            tof = intercept(dx, dy, dz, vx, vy, 0.0, speed)
            if LEAD_EMA and tof > 0.3:  # far: targets jink, so lead by their average velocity instead
                vx, vy, vz = tr["ev"]
                tof = intercept(dx, dy, dz, vx, vy, 0.0, speed)
        if abs(vz) > 3.0:
            vz *= 0.5
        else:
            vz = 0.0
        dx, dy, dz = dx + vx * tof, dy + vy * tof, dz + vz * tof
        h = math.hypot(dx, dy)
        return [math.atan2(dy, dx), math.atan2(dz, max(h, 1e-6))], h, tof

    def mortar_aim(self, mx, my, mz, tr, st):
        """Low-arc ballistic solution with lead, or None when out of reach."""
        v, g = st.get("speed", 72.0), st.get("gravity", 22.0)
        px, py, pz = tr["pos"]
        vx, vy, _ = tr["ev"]
        tof = 0.0
        sol = None
        for _ in range(3):
            dx, dy, dz = px + vx * tof - mx, py + vy * tof - my, pz - mz
            d = math.hypot(dx, dy)
            disc = v ** 4 - g * (g * d * d + 2 * dz * v * v)
            if disc < 0 or d < 1e-3:
                return None
            th = math.atan2(v * v - math.sqrt(disc), g * d)
            tof = d / (v * math.cos(th))
            sol = ([math.atan2(dy, dx), th], d, tof)
        return sol

    # ------------------------------------------------------------------ the decision
    def act(self, obs: mf.Observation) -> mf.Action:
        me = obs["self"]
        t = obs["t"]
        if STOP_T is not None and t > STOP_T:
            return {"tick": obs["tick"]}
        x, y, z = me["pos"]
        st = me["stats"]
        w = self.world
        rng = self.rng
        act: mf.Action = {"tick": obs["tick"]}
        hp, max_hp = me["hp"], max(1.0, me["max_hp"])
        hpf = hp / max_hp
        energy = me["energy"]
        walk = st.get("walk_speed", 11.7)
        weapons = me["weapons"]
        kinds = [wp["kind"] if wp else None for wp in weapons]

        # ---- remember what we see
        seen_now = set()
        for m in obs["mechs"]:
            i = m["id"]
            seen_now.add(i)
            tr = self.tracks.get(i)
            v = m["vel"]
            if tr is None:
                tr = self.tracks[i] = {"ev": list(v)}
            else:
                ev = tr["ev"]
                tr["ev"] = [ev[0] * 0.7 + v[0] * 0.3, ev[1] * 0.7 + v[1] * 0.3, ev[2] * 0.7 + v[2] * 0.3]
            npc = m["kind"] == "npc"
            scale = 1.0 + self.size_per_cube * m.get("cubes", 0)
            tr.update(id=i, pos=m["pos"], vel=v, t=t, npc=npc, aim=m.get("aim", (0.0, 0.0)), hp=m.get("hp", 1400.0), max_hp=m.get("max_hp", 1400.0),
                      weapons=m.get("weapons", ()), charging=m.get("charging", False),
                      ch=(self.npc_h * 0.5 if npc else self.mech_h * 0.5 * scale),
                      r=(self.npc_r if npc else self.mech_r * scale))
        for i in [i for i, tr in self.tracks.items() if t - tr["t"] > (3.0 if tr["npc"] else 8.0)]:
            del self.tracks[i]
        for p in obs["pickups"]:
            self.pickups[p["id"]] = (p["kind"], p["pos"], t)
        for c in obs["crates"]:
            self.crates[c["id"]] = (c["pos"], t)
        vis_crates = {c["id"] for c in obs["crates"]}
        vis_pick = {p["id"] for p in obs["pickups"]}
        for i in [i for i, (pos, ts) in self.crates.items() if i not in vis_crates and math.hypot(pos[0] - x, pos[1] - y) < 35]:
            del self.crates[i]  # we are close and it is no longer listed: destroyed
        for i in [i for i, (k, pos, ts) in self.pickups.items() if i not in vis_pick and math.hypot(pos[0] - x, pos[1] - y) < 30]:
            del self.pickups[i]

        for e in obs["events"]:
            et = e["type"]
            if et == "damaged":
                if e.get("weapon") != "zone":
                    self.last_hurt_t = t
                    if e.get("by") is not None:
                        self.hit_by[e["by"]] = t
                if e.get("bearing") is not None:
                    self.look_yaw, self.look_until = e["bearing"], t + 1.5
            elif et == "take_failed" and e.get("reason") in ("gone", "have"):
                self.bad_pickups.add(e["id"])
                self.pickups.pop(e["id"], None)
            elif et == "kill" and KILL_LOOT:
                vt = self.tracks.get(e.get("target"))
                if vt is not None:
                    self.kill_spots.append((vt["pos"][0], vt["pos"][1], vt["pos"][2], t))
            elif et == "took":
                self.pickups.pop(e["id"], None)

        if SEEK:
            rank_of = {"near": 3, "mid": 2, "far": 1}
            guess = {"near": 40.0, "mid": 110.0, "far": 230.0}
            for sd_ in obs["sounds"]:
                if sd_["kind"] not in ("gun", "laser", "laser_charge", "mortar", "lightning", "crate", "boost", "step", "jet", "reload"):
                    continue
                b = sd_["bearing"]
                # skip sounds that a mech we already track could have made
                if any(not tr["npc"] and abs(wrap(math.atan2(tr["pos"][1] - y, tr["pos"][0] - x) - b)) < 0.35 for tr in self.tracks.values()):
                    continue
                r = rank_of.get(sd_["dist"], 1)
                if self.heard is None or t - self.heard[2] > 6.0 or r >= self.heard[3]:
                    g_ = guess.get(sd_["dist"], 230.0)
                    self.heard = (x + g_ * math.cos(b), y + g_ * math.sin(b), t, r)
                    if not seen_now:
                        self.look_yaw, self.look_until = b, t + 1.2
        threats = sorted((tr for tr in self.tracks.values() if not tr["npc"] and tr["id"] in seen_now),
                         key=lambda tr: math.hypot(tr["pos"][0] - x, tr["pos"][1] - y))
        ghosts = [tr for tr in self.tracks.values() if not tr["npc"] and tr["id"] not in seen_now]
        npcs = [tr for tr in self.tracks.values() if tr["npc"] and tr["id"] in seen_now]
        if threats:
            self.last_threat_t = t

        # ---- zone
        zone = obs["zone"]
        zc, zr = zone["center"], zone["radius"]
        nc, nr = zone["next_center"], zone["next_radius"]
        d_cur = math.hypot(x - zc[0], y - zc[1])
        d_next = math.hypot(x - nc[0], y - nc[1])
        margin = min(15.0, nr * 0.3)
        over = d_next - (nr - margin)
        outside = (not me["in_zone"]) or d_cur > zr - 4.0
        must_go = over > 0 and t + over / walk * 1.4 + 8.0 >= zone["shrink_start"]
        shrinking = t >= zone["shrink_start"] - 6.0

        def zone_ok(px, py):
            if math.hypot(px - zc[0], py - zc[1]) > zr - 6.0:
                return False
            return not shrinking or math.hypot(px - nc[0], py - nc[1]) <= nr - min(4.0, nr * 0.2) or nr < 8

        # ---- pick the target for the torso
        mh = st.get("muzzle_height", 7.0)
        mx, my, mz = x, y, z + mh

        def can_see(tr):
            px, py, pz = tr["pos"]
            return w is None or abs(pz - z) > 6.0 or w.los(x, y, px, py)

        endgame = obs["alive"] <= 3 or nr <= 70.0

        def engaging(tr):
            """Is this house bot already in a fight with us? Shooting the others only pulls more hunters in."""
            px, py = tr["pos"][0], tr["pos"][1]
            d = math.hypot(px - x, py - y)
            if d > 240.0:
                return False
            if endgame or d < 60.0 or t - self.hit_by.get(tr["id"], -1e9) < 6.0:
                return True
            closing = -((px - x) * tr["vel"][0] + (py - y) * tr["vel"][1]) / (d + 1e-6)
            if closing > 3.0 and d < 180.0:
                return True
            if tr["hp"] < 0.4 * tr["max_hp"] and d < 160.0:
                return True
            return d < 190.0 and abs(wrap(tr["aim"][0] - math.atan2(y - py, x - px))) < 0.22

        target = None
        best_score = 1e18
        for tr in threats:  # the threat we can finish soonest: low HP and close, with a clear line
            if GATE and not engaging(tr):
                continue
            if can_see(tr):
                sc = tr["hp"] * (1.0 + math.hypot(tr["pos"][0] - x, tr["pos"][1] - y) / 120.0)
                if LASER_FIRST_TARGET and "laser" in tr["weapons"]:
                    sc *= 0.5
                if sc < best_score:
                    target, best_score = tr, sc

        def crate_target(limit):
            best, bd = None, limit
            for cid, (pos, ts) in self.crates.items():
                d = math.hypot(pos[0] - x, pos[1] - y)
                if d < bd and cid in vis_crates and abs(pos[2] - z) < 6 and (w is None or w.los(x, y, pos[0], pos[1])):
                    best, bd = pos, d
            if best is None:
                return None
            return {"id": -1, "pos": best, "vel": (0.0, 0.0, 0.0), "ev": (0.0, 0.0, 0.0), "ch": self.crate_h * 0.5,
                    "r": self.crate_r, "npc": False, "hp": 300.0, "weapons": (), "crate": True}

        side = None  # a crate or drone the gun can work on while the real enemy is too far to hit reliably
        if GREEDY and target is not None and math.hypot(target["pos"][0] - x, target["pos"][1] - y) > 60.0:
            side = crate_target(70.0)
            if side is None:
                cand = [tr for tr in npcs if can_see(tr) and math.hypot(tr["pos"][0] - x, tr["pos"][1] - y) < 70.0]
                if cand:
                    side = min(cand, key=lambda tr: tr["hp"])
        farm_ok = hpf > (max(FARM_HP, REST_HP) if REST else FARM_HP) and not threats and t - self.last_threat_t > 3.0
        farm = None
        if target is None:
            near_npcs = [tr for tr in npcs if can_see(tr)]
            if near_npcs:
                tr = min(near_npcs, key=lambda tr: math.hypot(tr["pos"][0] - x, tr["pos"][1] - y))
                d = math.hypot(tr["pos"][0] - x, tr["pos"][1] - y)
                if (farm_ok and d < 90) or (d < 50 and t - self.last_hurt_t < 2.0 and not threats):
                    farm = tr
            if farm is None and farm_ok and self.crates:
                farm = crate_target(70.0)
        peace = STYLE == "pacifist" or t < PEACE_T
        shoot = (target if not peace else None) or farm

        # ---- torso: aim and triggers
        fire = [False, False]
        aim = None
        label = "roam"
        if shoot is not None:
            sd = math.hypot(shoot["pos"][0] - x, shoot["pos"][1] - y)
            cur_yaw, cur_pitch = me["aim"]
            gun_aim = None
            for s, wp in enumerate(weapons):
                if wp is None:
                    continue
                k, ws = wp["kind"], wp["stats"]
                if k == "gun":
                    gt = side or shoot
                    a, h, tof = self.aim_at(mx, my, mz, gt, ws.get("speed", 252.0))
                    gun_aim = a
                    if aim is None:
                        aim = a
                    tol = math.atan2(gt["r"] * 0.9, max(h, 1.0)) + 0.015
                    if (h < ws.get("range", 230.0) * 0.97 and abs(wrap(a[0] - cur_yaw)) < tol
                            and abs(a[1] - cur_pitch) < tol + 0.02 and wp.get("reload", 0) <= 0):
                        fire[s] = True
                elif k == "lightning":
                    rngm = ws.get("range", 45.0)
                    cone = math.radians(ws.get("cone_deg", 30.0)) * 0.45
                    yaw_to = math.atan2(shoot["pos"][1] - y, shoot["pos"][0] - x)
                    if sd < rngm - 1.0 and abs(wrap(yaw_to - cur_yaw)) < cone and energy > ws.get("energy", 3.0) + 2:
                        fire[s] = True
                elif k == "laser":
                    a, h, _ = self.aim_at(mx, my, mz, shoot, None, 0.08)
                    charge = wp.get("charge", 0.0)
                    full = ws.get("charge", 0.75)
                    in_range = h < ws.get("range", 280.0) * 0.97
                    tol = math.atan2(shoot["r"] * 0.7, max(h, 1.0)) + 0.004
                    lined = abs(wrap(a[0] - cur_yaw)) < tol and abs(a[1] - cur_pitch) < tol + 0.01
                    if charge > 0:
                        if self.laser_hold_t is None:
                            self.laser_hold_t = t
                        if charge >= full - 0.11:
                            aim = a  # line the beam up for the release
                        # hold until full and lined up; never hold into the automatic discharge
                        release = charge >= full - 0.01 and (lined or t - self.laser_hold_t > full + ws.get("hold_s", 2.0) - 0.5)
                        if FINISH and lined and not release and charge >= ws.get("min_charge", 0.15):
                            mn = ws.get("min_frac", 0.35)
                            est = ws.get("damage", 315.0) * (mn + (1.0 - mn) * min(1.0, charge / full))
                            est *= 1.0 + 0.04 * min(me["cubes"], 10)
                            if "mortar" in shoot.get("weapons", ()):
                                est *= 1.0 + ws.get("cookoff", 0.6)
                            release = 0.85 * est >= shoot["hp"]
                        fire[s] = not release
                        if release:
                            aim = a
                    else:
                        self.laser_hold_t = None
                        if wp.get("cooldown", 0) <= 0.15 and in_range and not shoot.get("crate"):
                            fire[s] = True
                elif k == "mortar":
                    if wp.get("cooldown", 0) <= 0.2 and 14.0 < sd < 110.0 and not shoot.get("crate") and not shoot["npc"]:
                        sol = self.mortar_aim(mx, my, z + st.get("height", 9.0) + 0.5, shoot, ws)
                        if sol is not None:
                            a = sol[0]
                            aim = a
                            if abs(wrap(a[0] - cur_yaw)) < 0.03 and abs(a[1] - cur_pitch) < 0.03:
                                fire[s] = True
            if aim is None:
                aim = gun_aim or [math.atan2(shoot["pos"][1] - y, shoot["pos"][0] - x), 0.0]
            label = f"shoot {shoot['id']}"
        else:
            if "laser" in kinds:
                # a charge in progress with no target: keep holding a while in case they reappear
                s = kinds.index("laser")
                wp = weapons[s]
                if wp.get("charge", 0) > 0:
                    if self.laser_hold_t is None:
                        self.laser_hold_t = t
                    fire[s] = t - self.laser_hold_t < wp["stats"].get("charge", 0.75) + 1.2
                else:
                    self.laser_hold_t = None
            for s, wp in enumerate(weapons):
                if wp and wp["kind"] == "gun" and wp.get("ammo", 99) < wp["stats"].get("mag", 12) and wp.get("reload", 0) <= 0:
                    if not threats and (not ghosts or wp.get("ammo", 0) <= 3):
                        act["reload"] = True

        # ---- legs
        move = None
        boost = False
        jump = False

        # retreat state (hysteresis)
        near = [tr for tr in threats if math.hypot(tr["pos"][0] - x, tr["pos"][1] - y) < 160]
        danger = near + [g for g in ghosts if t - g["t"] < 6.0 and math.hypot(g["pos"][0] - x, g["pos"][1] - y) < 120]
        if STYLE != "smart":
            if not self.retreat:
                if danger and target is not None:
                    weak = hpf < 0.42 and target["hp"] > hp * 0.75
                    swarmed = len(near) >= 2 and hpf < 0.7
                    if weak or swarmed:
                        self.retreat = True
                elif danger and hpf < 0.5:
                    self.retreat = True
            else:
                if hpf > 0.85 or (not danger and t - self.last_threat_t > 8.0) or (target is not None and target["hp"] < 200 and hpf > 0.2):
                    self.retreat = False
        if STYLE == "smart":
            if not self.retreat:
                losing = target is not None and hpf < 0.35 and target["hp"] > hp
                swarmed = len(near) >= 2 and hpf < 0.5
                self.retreat = bool(danger) and (losing or swarmed)
            elif hpf > 0.9 or (not danger and t - self.last_threat_t > 10.0) or (target is not None and target["hp"] < 150):
                self.retreat = False
        if peace:
            self.retreat = bool(danger)
        elif STYLE == "berserk":
            self.retreat = False
        if must_go or outside:
            self.cover = None

        # mortar shells about to land on us
        flee_shell = None
        g = self.cfg["weapons"]["mortar"].get("gravity", 22.0)
        splash = self.cfg["weapons"]["mortar"].get("splash_radius", 7.0) * 1.3 + st.get("radius", 2.5) + 2
        for p in obs["projectiles"]:
            if p["kind"] != "mortar":
                continue
            px, py, pz = p["pos"]
            vx, vy, vz = p["vel"]
            dz = pz - z
            disc = vz * vz + 2 * g * max(dz, 0.0)
            tl = (vz + math.sqrt(disc)) / g
            if tl > 2.5:
                continue
            lx, ly = px + vx * tl, py + vy * tl
            dd = math.hypot(lx - x, ly - y)
            if dd < splash:
                flee_shell = ((x - lx) / dd, (y - ly) / dd) if dd > 0.5 else (-vy / (math.hypot(vx, vy) + 1e-6), vx / (math.hypot(vx, vy) + 1e-6))

        drop_goal = None
        bd = 150.0 if threats else 280.0
        for dr in obs["drops"] if DROPS != "off" else ():
            pos = dr["pos"]
            d = math.hypot(pos[0] - x, pos[1] - y)
            if dr.get("holder") not in (None, me["id"]) and dr.get("progress", 0) > 1.5 and d > 30:
                continue  # someone else has nearly got it
            if DROPS == "smart":
                # do not stand waiting under a falling drop, and do not go back to one we failed to hold
                if dr["id"] in self.bad_drops or d / walk < dr["lands_in"] - 5.0 or (len(near) >= 3 and hpf > 0.5):
                    continue
            if d < bd and d / walk < dr["lands_in"] + 20.0 and zone_ok(pos[0], pos[1]):
                drop_goal, bd = dr, d
        if DROPS == "smart":
            if drop_goal is not None and bd < drop_goal.get("radius", 8.0) and drop_goal["lands_in"] <= 0:
                self.drop_ring_t += 0.1
                if self.drop_ring_t > drop_goal.get("capture_s", 4.0) + 5.0:  # contested: stop being a sitting target
                    self.bad_drops.add(drop_goal["id"])
                    self.drop_ring_t, drop_goal = 0.0, None
            else:
                self.drop_ring_t = 0.0
        near_cube = None
        if hpf > 0.3 or KILL_LOOT:
            cd = CUBE_M if hpf > 0.5 else min(CUBE_M, CUBE_HURT_M)
            for c in obs["cubes"]:
                d = math.hypot(c["pos"][0] - x, c["pos"][1] - y)
                if d < cd and abs(c["pos"][2] - z) < 4.0 and zone_ok(c["pos"][0], c["pos"][1]):
                    near_cube, cd = c["pos"], d
            if near_cube is None and self.kill_spots:
                # no cube in sight yet: head for where the last victim fell
                self.kill_spots = [k for k in self.kill_spots if t - k[3] < 25.0 and math.hypot(k[0] - x, k[1] - y) > 6.0]
                for k in self.kill_spots:
                    d = math.hypot(k[0] - x, k[1] - y)
                    if d < 170.0 and abs(k[2] - z) < 8.0 and zone_ok(k[0], k[1]):
                        near_cube = (k[0], k[1], k[2])
                        break

        if not outside:
            self.out_since = None
        elif self.out_since is None:
            self.out_since, self.out_d0 = t, d_cur
        if outside:
            move = self.nav(x, y, nc[0], nc[1], t)
            boost = True
            if ZONE_JET and t - self.out_since > 2.5 and self.out_d0 - d_cur < 4.0 * (t - self.out_since):
                # the path is not getting us in: jump and jet straight at the zone centre
                dd = d_cur + 1e-6
                move = ((zc[0] - x) / dd, (zc[1] - y) / dd)
                jump = bool(me["grounded"])
            label += " |zone!"
        elif flee_shell is not None:
            move = flee_shell
            boost = True
            label += " |shell"
        elif must_go:
            gx, gy = nc[0], nc[1]
            if d_next > 1 and nr > 20:
                gx, gy = nc[0] + (x - nc[0]) / d_next * nr * 0.55, nc[1] + (y - nc[1]) / d_next * nr * 0.55
            move = self.nav(x, y, gx, gy, t)
            boost = over / walk > max(0.0, zone["shrink_end"] - t) * 0.7 or (bool(threats) and energy > 50)
            label += " |zone"
        elif drop_goal is not None and (danger or hpf < 0.95 or drop_goal["lands_in"] < 12.0 or bd < 60.0):
            pos, ring = drop_goal["pos"], drop_goal.get("radius", 8.0)
            if bd < ring - 2.0:  # inside the ring: keep moving in a small circle while it captures
                move = self.nav(x, y, pos[0] + ring * 0.45 * math.cos(t * 1.3), pos[1] + ring * 0.45 * math.sin(t * 1.3), t)
            else:
                move = self.nav(x, y, pos[0], pos[1], t)
                boost = energy > 40 and (bool(danger) or drop_goal["lands_in"] <= 0)
            label += " |drop"
        elif self.retreat and danger:
            hid = self.hidden_from(x, y, danger[:3])
            closest = min(math.hypot(e["pos"][0] - x, e["pos"][1] - y) for e in danger)
            if hid and closest > 35:
                move = (0.0, 0.0)  # hold still behind cover and heal
                self.cover = None
            else:
                if self.cover is None or t - self.cover_t > 0.5 or not self.hidden_from(self.cover[0], self.cover[1], danger[:3]):
                    self.cover = self.find_cover(x, y, danger[:3], zone_ok)
                    self.cover_t = t
                if self.cover is not None:
                    move = self.nav(x, y, self.cover[0], self.cover[1], t)
                else:  # nothing to hide behind: run away, zigzagging
                    e = danger[0]
                    ax, ay = x - e["pos"][0], y - e["pos"][1]
                    ad = math.hypot(ax, ay) + 1e-6
                    move = self.fight_step(x, y, ax / ad, ay / ad, 1.0, t, obs, zone_ok, zc)
                boost = energy > 15
            label += " |retreat"
        elif near_cube is not None and (target is not None or danger):
            move = self.nav(x, y, near_cube[0], near_cube[1], t)
            if KILL_LOOT:
                boost = energy > 30 and math.hypot(near_cube[0] - x, near_cube[1] - y) > 25.0
            label += " |cube"
        elif LOOT_IN_FIGHT and target is not None and self.weapon_goal(x, y, z, kinds, zone_ok, FETCH_M) is not None:
            wg = self.weapon_goal(x, y, z, kinds, zone_ok, FETCH_M)
            move = self.nav(x, y, wg[0], wg[1], t)
            if math.hypot(wg[0] - x, wg[1] - y) > 12.0:  # weave on the way so we are not a straight-line target
                side = self.strafe * 0.5 * (1.0 if int(t * 2.0) % 2 else -1.0)
                move = (move[0] - move[1] * side, move[1] + move[0] * side)
            label += " |arm"
        elif GREEDY and target is not None and len(near) <= 2 and hpf > 0.35 and self.crate_goal(x, y, z, zone_ok, 120.0) is not None:
            cg = self.crate_goal(x, y, z, zone_ok, 120.0)
            move = self.nav(x, y, cg[0], cg[1], t)
            side_w = self.strafe * 0.5 * (1.0 if int(t * 2.0) % 2 else -1.0)
            move = (move[0] - move[1] * side_w, move[1] + move[0] * side_w)
            label += " |crate"
        elif CORNER and target is not None and self.corner_spot(x, y, target, threats, zone_ok, t) is not None:
            sp = self.spot
            move = self.nav(x, y, sp[0], sp[1], t)
            side_w = self.strafe * 0.4 * (1.0 if int(t * 2.0) % 2 else -1.0)
            move = (move[0] - move[1] * side_w, move[1] + move[0] * side_w)
            boost = energy > 40
            label += " |corner"
        elif target is not None:
            td = math.hypot(target["pos"][0] - x, target["pos"][1] - y)
            tw = target["weapons"]
            if "lightning" in kinds and energy > 25:
                want = 30.0
            elif "lightning" in tw:
                want = 75.0
            elif "laser" in kinds and "laser" not in tw:
                want = 125.0
            else:
                want = 60.0
            if RANGE == "close":
                want = 35.0 if "lightning" not in kinds else 28.0
            elif RANGE == "far":
                want = FAR_M
            if target["hp"] < 300 and hpf > 0.3:
                want = min(want, 40.0)
            if FINISH and target["hp"] < 0.38 * target["max_hp"] and hpf > 0.42 and len(near) <= 2:
                want = 20.0
            bx, by = (target["pos"][0] - x) / (td + 1e-6), (target["pos"][1] - y) / (td + 1e-6)
            radial = max(-1.0, min(1.0, (td - want) / 15.0))
            self.jink_tof = td / self.cfg["weapons"]["gun"].get("speed", 252.0)
            move = self.fight_step(x, y, bx, by, radial, t, obs, zone_ok, zc)
            boost = energy > 60 and abs(radial) > 0.9 and ("lightning" in kinds or RANGE == "close")
            if FIGHT_BOOST:
                emax = max(1.0, me.get("max_energy", 100.0))
                if energy < 0.28 * emax:
                    self.boost_ok = False
                elif energy > 0.70 * emax:
                    self.boost_ok = True
                boost = self.boost_ok and td < 130.0
            label += " |fight"
        else:
            goal = self.loot_goal(obs, x, y, z, t, kinds, hpf, zone_ok, farm, ghosts)
            if SEEK and hpf > 0.5 and not obs["cubes"] and self.weapon_goal(x, y, z, kinds, zone_ok, FETCH_M) is None:
                hunt = None
                if ghosts:
                    gtr = min(ghosts, key=lambda tr: t - tr["t"])
                    hunt = (gtr["pos"][0], gtr["pos"][1])
                elif self.heard is not None and t - self.heard[2] < 25.0:
                    hunt = (self.heard[0], self.heard[1])
                    if math.hypot(hunt[0] - x, hunt[1] - y) < 25.0:
                        self.heard, hunt = None, None  # got there and nobody is here
                if hunt is not None and math.hypot(hunt[0] - zc[0], hunt[1] - zc[1]) < zr - 10.0:
                    goal = hunt
                    label += " |seek"
            if PURSUE and ghosts and hpf > 0.4 and not obs["cubes"]:
                gtr = min(ghosts, key=lambda tr: t - tr["t"])
                if zone_ok(gtr["pos"][0], gtr["pos"][1]):
                    goal = (gtr["pos"][0], gtr["pos"][1])
            if goal is None:
                if (self.roam is None or t - self.roam_t > 30.0 or math.hypot(self.roam[0] - x, self.roam[1] - y) < 8.0
                        or math.hypot(self.roam[0] - nc[0], self.roam[1] - nc[1]) > max(nr - 10.0, 0.0)):
                    a, r = rng.random() * 2 * PI, nr * 0.65 * math.sqrt(rng.random())
                    rx, ry = nc[0] + r * math.cos(a), nc[1] + r * math.sin(a)
                    if w is not None:
                        c = w.nearest_free(rx, ry)
                        if c >= 0:
                            rx, ry = w.center(c)
                    self.roam, self.roam_t = (rx, ry), t
                goal = self.roam
                if hpf < 0.8 and t - self.last_threat_t < 15.0 and not shrinking:
                    goal = None  # hurt and nobody in sight: stand still (silent) and heal
            if IDLE_STILL and goal is self.roam and nr > 35.0:
                goal = None
                label += " |hold"
            if REST and hpf < REST_HP and not shrinking and not must_go:
                cube_close = goal is not None and any(math.hypot(c["pos"][0] - x, c["pos"][1] - y) < 20.0 for c in obs["cubes"])
                if not cube_close:
                    goal = None
                    watchers = [g_ for g_ in ghosts if t - g_["t"] < 8.0]
                    if watchers and not self.hidden_from(x, y, watchers[:3]):
                        if self.cover is None or t - self.cover_t > 1.0:
                            self.cover, self.cover_t = self.find_cover(x, y, watchers[:3], zone_ok), t
                        goal = self.cover
                    label += " |rest"
            move = self.nav(x, y, goal[0], goal[1], t) if goal else (0.0, 0.0)

        # ---- laser dodge: a charging beam is about to fire along its aim, which is locked on us
        if LASER_DODGE and not outside:
            for k_ in [k_ for k_ in self.charge_seen if not (k_ in self.tracks and self.tracks[k_]["charging"] and self.tracks[k_]["t"] == t)]:
                del self.charge_seen[k_]
            worst = None
            for tr in threats:
                if not tr["charging"] or "laser" not in tr["weapons"]:
                    continue
                ex, ey = tr["pos"][0], tr["pos"][1]
                d = math.hypot(x - ex, y - ey)
                if d > 290.0 or (w is not None and not w.los(ex, ey, x, y)):
                    continue
                miss = abs(wrap(tr["aim"][0] - math.atan2(y - ey, x - ex))) * d  # metres the aim line passes from us
                if miss > 8.0:
                    continue
                if tr["id"] not in self.charge_seen:
                    self.charge_seen[tr["id"]] = t
                    self.dodge_side = 1.0 if rng.random() < 0.5 else -1.0
                if worst is None or d < worst[1]:
                    worst = (tr, d)
            if worst is not None:
                tr, d = worst
                age = t - self.charge_seen[tr["id"]]
                full = self.cfg["weapons"]["laser"].get("charge", 0.75)
                side = self.dodge_side * (1.0 if age < 0.55 * full else -1.0)  # reverse to beat a shooter that leads us
                ux, uy = (x - tr["pos"][0]) / (d + 1e-6), (y - tr["pos"][1]) / (d + 1e-6)
                cand = (-uy * side, ux * side)
                if w is not None and not (w.free(x + cand[0] * 5.0, y + cand[1] * 5.0) and zone_ok(x + cand[0] * 5.0, y + cand[1] * 5.0)):
                    cand = (-cand[0], -cand[1])
                move = cand
                boost = energy > 5.0
                label += " |dodge"

        # ---- unstick: commanded to move but not moving
        speed = math.hypot(me["vel"][0], me["vel"][1])
        if move and (abs(move[0]) + abs(move[1])) > 0.3 and speed < 1.2:
            self.stuck_t += 0.1
        else:
            self.stuck_t = 0.0
        if self.stuck_t > 0.8 and t > self.unstick_until:
            a = rng.random() * 2 * PI
            self.unstick_dir, self.unstick_until, self.stuck_t = (math.cos(a), math.sin(a)), t + 0.7, 0.0
            self.path = None
        if t < self.unstick_until:
            move = (move[0] * 0.5 + self.unstick_dir[0], move[1] * 0.5 + self.unstick_dir[1])
            jump = bool(me["grounded"])
            boost = True

        # ---- torso when there is nothing to shoot: look where trouble is, else sweep ahead
        if aim is None:
            if ghosts and t - self.last_threat_t < 6.0:
                gtr = min(ghosts, key=lambda tr: t - tr["t"])
                aim = [math.atan2(gtr["pos"][1] - y, gtr["pos"][0] - x), 0.0]
            elif self.look_yaw is not None and t < self.look_until:
                aim = [self.look_yaw, 0.0]
            elif move and (abs(move[0]) + abs(move[1])) > 0.3:
                aim = [math.atan2(move[1], move[0]) + 1.0 * math.sin(t * 1.6), 0.0]
            else:
                aim = [wrap(t * (3.5 if IDLE_STILL else 1.4)), 0.0]

        # ---- loot interactions
        if obs["offer"]:
            choices = obs["offer"]["choices"]
            rank = {u: i for i, u in enumerate(UPGRADE_ORDER)}
            if LASER_FIRST and "laser" in kinds:
                rank["laser_damage"], rank["laser_charge"] = -2, -1
            act["pick"] = min(range(len(choices)), key=lambda i: rank.get(choices[i]["id"], 99))
        slot1_rank = WEAPON_RANK.get(kinds[1], 0) if len(kinds) > 1 else 0
        for p in obs["pickups"]:
            if p["id"] in self.bad_pickups or p["kind"] in kinds or WEAPON_RANK.get(p["kind"], 0) <= slot1_rank:
                continue
            if math.hypot(p["pos"][0] - x, p["pos"][1] - y) < self.take_r - 0.3 and abs(p["pos"][2] - z) < 3.7:
                if len(kinds) > 1 and kinds[1] is not None:
                    if kinds[1] == "laser" and weapons[1].get("charge", 0) > 0:
                        continue
                    act["drop"] = 1
                act["take"] = p["id"]
                break

        n = math.hypot(move[0], move[1])
        if n > 1.0:
            move = (move[0] / n, move[1] / n)
        act["move"] = [round(move[0], 3), round(move[1], 3)]
        act["aim"] = [round(wrap(aim[0]), 4), round(max(st.get("min_pitch", -0.7), min(st.get("max_pitch", 1.3), aim[1])), 4)]
        act["fire"] = fire
        act["boost"] = bool(boost)
        act["jump"] = bool(jump)
        mf.draw.label(f"{label} hp{hp:.0f}")
        return act

    # ------------------------------------------------------------------ helpers for legs
    def fight_step(self, x, y, bx, by, radial, t, obs, zone_ok, zc):
        """Strafe across the line to the enemy (bx, by), flipping at random, sidestepping bullets and walls."""
        rng = self.rng
        if t > self.strafe_until:
            if JINK and self.jink_tof > 0:
                # a shooter leading by our velocity misses if we reverse during the bullet's flight
                self.strafe = -self.strafe
                self.strafe_until = t + max(0.3, 1.25 * self.jink_tof) * rng.uniform(0.7, 1.3)
            else:
                if rng.random() < 0.6:
                    self.strafe = -self.strafe
                self.strafe_until = t + rng.uniform(0.3, 0.9)
        # incoming bullets: step off their line
        ox = oy = 0.0
        me = obs["self"]
        cz = me["pos"][2] + 4.5
        rad = me["stats"].get("radius", 2.5) + 1.8
        for p in obs["projectiles"]:
            if p["kind"] == "mortar":
                continue
            px, py, pz = p["pos"]
            vx, vy, vz = p["vel"]
            vv = vx * vx + vy * vy + vz * vz
            if vv < 1.0:
                continue
            tc = ((x - px) * vx + (y - py) * vy + (cz - pz) * vz) / vv
            if tc < 0 or tc > 0.7:
                continue
            qx, qy = x - (px + vx * tc), y - (py + vy * tc)
            miss = math.hypot(qx, qy)
            if miss < rad:
                if miss > 0.3:
                    ox, oy = ox + qx / miss, oy + qy / miss
                else:
                    vh = math.hypot(vx, vy) + 1e-6
                    ox, oy = ox - vy / vh * self.strafe, oy + vx / vh * self.strafe
        w = self.world
        on = math.hypot(ox, oy)
        cands = []
        if on > 0.3:
            cands.append((ox / on + bx * radial * 0.3, oy / on + by * radial * 0.3))
        for s in (self.strafe, -self.strafe):
            cands.append((-by * s + bx * radial * 0.8, bx * s + by * radial * 0.8))
        cands.append((bx * radial, by * radial))
        for k, (mx, my) in enumerate(cands):
            n = math.hypot(mx, my)
            if n < 1e-6:
                continue
            mx, my = mx / n, my / n
            px, py = x + mx * 6.0, y + my * 6.0
            if (w is None or (w.free(px, py) and w.free(x + mx * 3.0, y + my * 3.0))) and zone_ok(px, py):
                if on <= 0.3 and k == 1:  # the preferred strafe side was blocked: remember the flip
                    self.strafe = -self.strafe
                return mx, my
        d = math.hypot(zc[0] - x, zc[1] - y) + 1e-6
        return (zc[0] - x) / d, (zc[1] - y) / d

    def corner_spot(self, x, y, target, threats, zone_ok, t):
        """A nearby spot where fewer of the other enemies can see us (None = stay and fight here)."""
        w = self.world
        if w is None:
            return None
        if t - self.spot_t < 0.4:
            sp = self.spot
            return sp if sp is not None and math.hypot(sp[0] - x, sp[1] - y) > 4.0 else None
        self.spot_t, self.spot = t, None
        others = [e for e in threats if e is not target and math.hypot(e["pos"][0] - x, e["pos"][1] - y) < 230.0][:5]
        if not others:
            return None
        tx, ty = target["pos"][0], target["pos"][1]

        def cost(px, py):
            c = 0.0
            for e in others:
                if w.los(e["pos"][0], e["pos"][1], px, py):
                    c += 150.0 if "laser" in e["weapons"] else 100.0
            if not w.los(tx, ty, px, py):
                c += 50.0
            return c + abs(math.hypot(px - tx, py - ty) - FAR_M) * 0.15

        cur = cost(x, y)
        if cur < 60.0:
            return None
        best, bc = None, cur - 40.0
        off = self.rng.random() * 2 * PI
        for r in (8.0, 16.0, 26.0, 38.0):
            for k in range(10):
                a = off + 2 * PI * k / 10
                px, py = x + r * math.cos(a), y + r * math.sin(a)
                if not w.free(px, py) or not zone_ok(px, py):
                    continue
                c = cost(px, py) + r * (0.6 if w.walk_clear(x, y, px, py, 3.0) else 1.2)
                if c < bc:
                    best, bc = (px, py), c
        self.spot = best
        return best

    def crate_goal(self, x, y, z, zone_ok, limit):
        """Nearest known ground-level crate further than shooting distance, or None."""
        w = self.world
        best, bd = None, limit
        for cid, (pos, ts) in self.crates.items():
            d = math.hypot(pos[0] - x, pos[1] - y)
            if d < 22.0 and (w is None or w.los(x, y, pos[0], pos[1])):
                return None  # already close enough to one: shoot it from here
            if w is not None and abs(pos[2] - w.ground(pos[0], pos[1])) > 3.5:
                continue
            if d < bd and zone_ok(pos[0], pos[1]):
                best, bd = pos, d
        return best

    def weapon_goal(self, x, y, z, kinds, zone_ok, limit):
        """Position of the best known weapon pickup worth swapping to within `limit` m, or None."""
        w = self.world
        slot1_rank = WEAPON_RANK.get(kinds[1], 0) if len(kinds) > 1 else 0
        best, bd = None, 1e9
        for pid, (kind, pos, ts) in self.pickups.items():
            gain = WEAPON_RANK.get(kind, 0) - slot1_rank
            if pid in self.bad_pickups or kind in kinds or gain <= 0:
                continue
            if w is not None and abs(pos[2] - w.ground(pos[0], pos[1])) > 3.5 and abs(pos[2] - z) > 3.5:
                continue  # on a roof
            d = math.hypot(pos[0] - x, pos[1] - y)
            if d < limit and d / (1.0 + 0.5 * gain) < bd and zone_ok(pos[0], pos[1]):
                best, bd = pos, d / (1.0 + 0.5 * gain)
        return best

    def loot_goal(self, obs, x, y, z, t, kinds, hpf, zone_ok, farm, ghosts):
        """Where to walk when nobody is in sight: cubes, a better weapon, a supply drop, a crate or NPC."""
        w = self.world

        def reachable(pos, limit):
            if abs(pos[2] - (w.ground(pos[0], pos[1]) if w else z)) > 3.5 and abs(pos[2] - z) > 3.5:
                return False  # on a roof: skip
            return math.hypot(pos[0] - x, pos[1] - y) < limit and zone_ok(pos[0], pos[1])

        best, bd = None, 1e9
        for c in obs["cubes"]:
            d = math.hypot(c["pos"][0] - x, c["pos"][1] - y)
            if d < bd and reachable(c["pos"], 90.0):
                best, bd = c["pos"], d
        if best is not None:
            return best
        slot1_rank = WEAPON_RANK.get(kinds[1], 0) if len(kinds) > 1 else 0
        for pid, (kind, pos, ts) in self.pickups.items():
            if pid in self.bad_pickups or kind in kinds:
                continue
            gain = WEAPON_RANK.get(kind, 0) - slot1_rank
            if gain <= 0:
                continue
            d = math.hypot(pos[0] - x, pos[1] - y) / (1.0 + 0.5 * gain)
            if d < bd and reachable(pos, 220.0 if slot1_rank == 0 else 110.0):
                best, bd = pos, d
        if best is not None:
            return best
        for dr in obs["drops"]:  # nothing better to do: wait at a drop that is still falling
            pos = dr["pos"]
            d = math.hypot(pos[0] - x, pos[1] - y)
            if d < 280 and zone_ok(pos[0], pos[1]) and d < bd:
                best, bd = pos, d
        if best is not None:
            return best
        if farm is not None:
            fx, fy = farm["pos"][0], farm["pos"][1]
            d = math.hypot(fx - x, fy - y)
            keep = 40.0 if farm["npc"] else 14.0
            if d > keep + 4:
                return (fx, fy)
            if farm["npc"]:  # orbit the drone so its slow bullets miss
                s = self.strafe
                if t > self.strafe_until:
                    self.strafe, self.strafe_until = -s if self.rng.random() < 0.5 else s, t + self.rng.uniform(0.6, 1.4)
                px, py = x - (fy - y) / (d + 1e-6) * 10 * s, y + (fx - x) / (d + 1e-6) * 10 * s
                if (w is None or w.free(px, py)) and zone_ok(px, py):
                    return (px, py)
            return (x, y)
        if hpf > 0.75:
            for cid, (pos, ts) in self.crates.items():
                d = math.hypot(pos[0] - x, pos[1] - y)
                if d < bd and reachable(pos, 150.0):
                    best, bd = pos, d
        return best


if __name__ == "__main__":
    mf.run(Bot)
