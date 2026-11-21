"""Mech Royale bot: stay in the zone, face attackers, shoot with lead, grab cubes/drops/weapons."""
import math
import mechfight as mf

TAU = math.tau


def ang_diff(a, b):
    return (a - b + math.pi) % TAU - math.pi


def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Bot:
    name = "survivor-py"

    def __init__(self, hello):
        c = hello["config"]
        self.cfg = c
        self.pick_r = c["loot"]["pickup_radius"]
        self.gun_speed = c["weapons"]["gun"].get("speed", 252.0)
        self.mortar = c["weapons"]["mortar"]
        self.laser = c["weapons"]["laser"]
        self.lightning = c["weapons"]["lightning"]
        self.upgrades = {u.get("id"): u for u in c.get("upgrades", [])}
        self.last_pos = None
        self.stuck = 0
        self.strafe = 1
        self.last_damage_t = -99.0
        self.hit_bearing = None

    # ---- upgrades: prefer survivability ----
    def choose_upgrade(self, offer):
        pref = ["armor", "regen", "hp", "max_hp", "sensors", "gun_rate", "gun_damage"]
        best, score = 0, 99
        for i, ch in enumerate(offer.get("choices", [])):
            cid = ch.get("id", "")
            for r, p in enumerate(pref):
                if p in cid:
                    if r < score:
                        best, score = i, r
                    break
        return best

    def lead(self, me, t):
        mx, my, mz = me["pos"]
        d = math.dist(t["pos"], me["pos"])
        tt = d / self.gun_speed
        px = t["pos"][0] + t["vel"][0] * tt
        py = t["pos"][1] + t["vel"][1] * tt
        pz = t["pos"][2] + 4.5 + t["vel"][2] * tt
        dxy = math.hypot(px - mx, py - my)
        yaw = math.atan2(py - my, px - mx)
        pitch = math.atan2(pz - (mz + 7.0), max(dxy, 0.1))
        return yaw, pitch, dxy

    def act(self, obs):
        me = obs["self"]
        x, y, z = me["pos"]
        t = obs["t"]
        act = {"tick": obs["tick"]}
        zone = obs["zone"]

        if obs.get("offer"):
            act["pick"] = self.choose_upgrade(obs["offer"])

        for e in obs.get("events", []):
            if e["type"] == "damaged" and e.get("bearing") is not None:
                self.last_damage_t = t
                self.hit_bearing = e["bearing"]

        enemies = sorted((m for m in obs["mechs"] if m["kind"] == "mech"), key=lambda m: math.dist(m["pos"], me["pos"]))
        # --- navigation goal ---
        cx, cy = zone["center"]
        nx, ny = zone["next_center"]
        nr = zone["next_radius"]
        shrinking = t >= zone["shrink_start"]
        gx, gy = (nx, ny)
        gr = max(nr * 0.55, 4.0)
        d_goal = math.hypot(gx - x, gy - y)
        want = None  # (x, y) to move to
        urgent = (not me["in_zone"]) or math.hypot(x - cx, y - cy) > zone["radius"] * 0.85 or d_goal > nr * 0.9 and shrinking
        if d_goal > gr:
            want = (gx, gy)

        # opportunistic targets only when safe
        if not urgent and not enemies:
            best = None
            for c in obs.get("cubes", []):
                dd = dist2(c["pos"], (x, y))
                if dd < 40 and math.hypot(c["pos"][0] - nx, c["pos"][1] - ny) < nr * 0.9:
                    if best is None or dd < best[0]:
                        best = (dd, c["pos"])
            for dr in obs.get("drops", []):
                dd = dist2(dr["pos"], (x, y))
                if dr["lands_in"] < 6 and dd < 90 and not dr.get("holder") and math.hypot(dr["pos"][0] - nx, dr["pos"][1] - ny) < nr + 10:
                    if best is None or dd < best[0] + 30:
                        best = (dd - 30, dr["pos"])
            if best:
                want = (best[1][0], best[1][1])

        # weapon pickups
        slots = me["weapons"]
        empty = 1 if slots[1] is None else (0 if slots[0] is None else None)
        if empty is not None and not urgent:
            for p in obs.get("pickups", []):
                dd = dist2(p["pos"], (x, y))
                if p["kind"] == "gun":
                    continue
                if dd <= self.pick_r and abs(p["pos"][2] - z) < 4:
                    act["take"] = p["id"]
                    break
                if dd < 35 and not enemies:
                    want = (p["pos"][0], p["pos"][1])

        # --- combat ---
        yaw_now = me["aim"][0]
        aim = None
        fire = [False, False]
        target = enemies[0] if enemies else None
        if target:
            yaw, pitch, dxy = self.lead(me, target)
            aim = [yaw, pitch]
            err = abs(ang_diff(yaw, yaw_now))
            g = slots[0]
            if g and dxy < 200 and err < 0.12 and g.get("ammo", 1) > 0:
                fire[0] = True
            s1 = slots[1]
            if s1:
                k = s1["kind"]
                if k == "lightning" and dxy < 42 and err < 0.3:
                    fire[1] = True
                elif k == "laser" and dxy < 260:
                    ch = s1.get("charge", 0)
                    if err < 0.08 and ch < self.laser.get("charge", 0.75) * 0.95:
                        fire[1] = True
                    elif err < 0.08 and ch >= self.laser.get("charge", 0.75) * 0.95:
                        fire[1] = False
                elif k == "mortar" and 25 < dxy < 220 and err < 0.15:
                    v = self.mortar.get("speed", 72.0)
                    g_ = self.mortar.get("gravity", 22.0)
                    s = max(-1.0, min(1.0, dxy * g_ / (v * v)))
                    if dxy * g_ / (v * v) <= 1.0:
                        aim = [yaw, 0.5 * math.asin(s)]
                        fire[1] = True
            act["fire"] = fire
            # strafe around target, retreat if close
            ux, uy = math.cos(yaw), math.sin(yaw)
            if t % 2.0 < 0.1:
                self.strafe = -self.strafe
            sx, sy = -uy * self.strafe, ux * self.strafe
            mvx, mvy = sx * 0.8, sy * 0.8
            if dxy < 25:
                mvx -= ux * 0.6
                mvy -= uy * 0.6
            if want:
                wx, wy = want[0] - x, want[1] - y
                n = math.hypot(wx, wy) or 1
                mvx += wx / n * (1.2 if urgent else 0.5)
                mvy += wy / n * (1.2 if urgent else 0.5)
            move = (mvx, mvy)
        else:
            # no visible enemy: if hit recently, turn toward the attacker
            if t - self.last_damage_t < 2.0 and self.hit_bearing is not None:
                aim = [self.hit_bearing, 0.0]
            if want:
                move = (want[0] - x, want[1] - y)
            else:
                move = (0.0, 0.0)
            # reload when idle
            g = slots[0]
            if g and g.get("ammo", 99) < 12:
                act["reload"] = True

        if me.get("grounded") and g_ammo_empty(slots):
            act["reload"] = True

        n = math.hypot(*move)
        if n > 1e-6:
            move = [move[0] / n, move[1] / n]
        else:
            move = [0.0, 0.0]
        act["move"] = move
        if aim is None and n > 1e-6 and not enemies:
            aim = [math.atan2(move[1], move[0]), 0.0]
        if aim:
            act["aim"] = aim

        # stuck / outside zone handling
        speed = math.hypot(me["vel"][0], me["vel"][1])
        if n > 0.5 and speed < 1.0 and me.get("grounded"):
            self.stuck += 1
        else:
            self.stuck = 0
        boost = (not me["in_zone"]) and me["energy"] > 15
        if self.stuck >= 3 and me["energy"] > 10:
            act["jump"] = True
            boost = True
        if not me.get("grounded") and self.stuck == 0 and z < 1e9:
            boost = boost and me["energy"] > 15
        act["boost"] = boost
        return act


def g_ammo_empty(slots):
    g = slots[0]
    return bool(g) and g.get("ammo", 1) <= 0


mf.run(Bot)
