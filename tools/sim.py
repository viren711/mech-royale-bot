"""Rough local sandbox, for catching bugs only. NOT the official simulator.

It drives bot.Bot through a whole match of made-up physics on the real map: walking with wall
sliding, the real zone schedule, scripted "hunter" mechs with guns (some with lasers), crates, cubes
and weapon pickups. Its numbers say nothing about placement; it exists to exercise every branch of
the bot, count exceptions, zone damage and time per decision.

    python3 tools/sim.py <kit dir> [seed] [hunters]
"""
import gzip
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot as botmod  # noqa: E402
import mechfight as mf  # noqa: E402

DT = 0.05


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class Mech:
    def __init__(self, i, pos, cfg):
        self.id, self.pos, self.vel = i, list(pos), [0.0, 0.0, 0.0]
        self.aim = [0.0, 0.0]
        self.hp = self.max_hp = cfg["mech"]["hp"]
        self.energy = 100.0
        self.alive = True
        self.cubes = 0
        self.gun_cd, self.ammo, self.reload = 0.0, 12, 0.0
        self.laser_cd, self.charge = 0.0, 0.0
        self.has_laser = False
        self.last_dmg = -99.0
        self.strafe, self.strafe_until = 1.0, 0.0
        self.skill = 0.5


def main():
    kit = sys.argv[1]
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    n_hunters = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    rng = random.Random(seed)
    with gzip.open(os.path.join(kit, "check", "stream.jsonl.gz"), "rt") as f:
        hello = json.loads(f.readline())
    hello["map"]["dir"] = os.path.join(kit, "arena")
    cfg = hello["config"]
    b = botmod.Bot(hello)
    w = b.world
    zc0, zr0 = cfg["zone"]["start_center"], cfg["zone"]["start_radius"]

    def spawn():
        while True:
            a, r = rng.random() * 6.283, zr0 * 0.8 * math.sqrt(rng.random())
            x, y = zc0[0] + r * math.cos(a), zc0[1] + r * math.sin(a)
            if w.free(x, y) and w.nearest_free(x, y, 0) >= 0:
                return [x, y, w.ground(x, y)]

    me = Mech(0, spawn(), cfg)
    hunters = [Mech(i + 1, spawn(), cfg) for i in range(n_hunters)]
    for h in hunters:
        h.has_laser = rng.random() < 0.4
        h.skill = rng.choice([0.3, 0.5, 0.7, 0.9])
    weapons = [{"kind": "gun"}, None]
    pickups = {8000 + i: (rng.choice(["mortar", "laser", "lightning"]), spawn()) for i in range(40)}
    crates = {1000 + i: [spawn(), 300.0] for i in range(36)}
    cubes = {}
    next_cube = [5000]
    # zone schedule
    phases = []
    tcur, c, r = 0.0, list(zc0), zr0
    for ph in cfg["zone"]["phases"]:
        a, rr = rng.random() * 6.283, (r - ph["radius"]) * math.sqrt(rng.random())
        nc = [c[0] + rr * math.cos(a), c[1] + rr * math.sin(a)]
        phases.append((tcur + ph["hold_s"], tcur + ph["hold_s"] + ph["shrink_s"], c, r, nc, ph["radius"], ph["dps"]))
        tcur += ph["hold_s"] + ph["shrink_s"]
        c, r = nc, ph["radius"]

    def zone_at(t):
        for s, e, c0, r0, c1, r1, dps in phases:
            if t < e:
                f = max(0.0, min(1.0, (t - s) / (e - s)))
                return {"center": [c0[0] + (c1[0] - c0[0]) * f, c0[1] + (c1[1] - c0[1]) * f], "radius": r0 + (r1 - r0) * f,
                        "next_center": c1, "next_radius": r1, "shrink_start": s, "shrink_end": e, "dps": dps}
        s, e, c0, r0, c1, r1, dps = phases[-1]
        return {"center": c1, "radius": 0.0, "next_center": c1, "next_radius": 0.0, "shrink_start": s, "shrink_end": e, "dps": dps}

    def step_mech(m, mv, speed):
        acc = cfg["mech"]["ground_accel"] * DT
        for k in (0, 1):
            d = mv[k] * speed - m.vel[k]
            m.vel[k] += max(-acc, min(acc, d))
        nx, ny = m.pos[0] + m.vel[0] * DT, m.pos[1] + m.vel[1] * DT
        if w.free(nx, ny):
            m.pos[0], m.pos[1] = nx, ny
        elif w.free(nx, m.pos[1]):
            m.pos[0], m.vel[1] = nx, 0.0
        elif w.free(m.pos[0], ny):
            m.pos[1], m.vel[0] = ny, 0.0
        else:
            m.vel[0] = m.vel[1] = 0.0
        m.pos[2] = w.ground(m.pos[0], m.pos[1])

    bullets = []  # [pos, vel, owner, ttl, dmg]
    events = []
    stats = {"zone_dmg": 0.0, "dealt": 0.0, "taken": 0.0, "errors": 0, "max_ms": 0.0, "kills": 0, "stuck": 0, "took": []}
    act = {}
    times = []
    t, tick = 0.0, 0
    place = None
    prev_pos = list(me.pos)
    while t < 480 and me.alive:
        zone = zone_at(t)
        if tick % 2 == 0:
            # ---- observation
            seen = []
            for h in hunters:
                if not h.alive:
                    continue
                d = math.dist(h.pos[:2], me.pos[:2])
                yaw_to = math.atan2(h.pos[1] - me.pos[1], h.pos[0] - me.pos[0])
                if w.los(me.pos[0], me.pos[1], h.pos[0], h.pos[1]) and (d < 45 or (d < 200 and abs(wrap(yaw_to - me.aim[0])) < math.pi / 3)):
                    seen.append({"id": h.id, "kind": "mech", "pos": [round(v, 2) for v in h.pos], "vel": [round(v, 2) for v in h.vel],
                                 "aim": h.aim, "hp": h.hp, "max_hp": h.max_hp, "cubes": h.cubes,
                                 "weapons": ["gun"] + (["laser"] if h.has_laser else []), "charging": h.charge > 0})

            def vis(pos, rr=120):
                return math.dist(pos[:2], me.pos[:2]) < rr and w.los(me.pos[0], me.pos[1], pos[0], pos[1])

            wobs = []
            for wp in weapons:
                if wp is None:
                    wobs.append(None)
                elif wp["kind"] == "gun":
                    wobs.append({"kind": "gun", "cooldown": me.gun_cd, "ammo": me.ammo, "reload": me.reload, "stats": dict(cfg["weapons"]["gun"])})
                elif wp["kind"] == "laser":
                    wobs.append({"kind": "laser", "cooldown": me.laser_cd, "charge": me.charge, "stats": dict(cfg["weapons"]["laser"])})
                else:
                    wobs.append({"kind": wp["kind"], "cooldown": 0.0, "stats": dict(cfg["weapons"][wp["kind"]])})
            obs = {"type": "obs", "tick": tick, "t": round(t, 2), "alive": 1 + sum(h.alive for h in hunters),
                   "self": {"id": 0, "pos": [round(v, 2) for v in me.pos], "vel": [round(v, 2) for v in me.vel], "aim": list(me.aim),
                            "hp": me.hp, "max_hp": me.max_hp, "energy": me.energy, "max_energy": 100, "grounded": True,
                            "cubes": me.cubes, "upgrades": [], "weapons": wobs,
                            "in_zone": math.dist(me.pos[:2], zone["center"]) <= zone["radius"], "stats": dict(cfg["mech"])},
                   "mechs": seen,
                   "projectiles": [{"id": i, "kind": "gun", "pos": bl[0][:], "vel": bl[1][:]} for i, bl in enumerate(bullets) if bl[2] != 0 and vis(bl[0], 200)],
                   "crates": [{"id": i, "pos": c[0], "hp": c[1]} for i, c in crates.items() if vis(c[0])],
                   "cubes": [{"id": i, "pos": p} for i, p in cubes.items() if vis(p)],
                   "pickups": [{"id": i, "kind": k, "pos": p} for i, (k, p) in pickups.items() if vis(p)],
                   "sounds": [], "beams": [], "events": events, "zone": zone, "offer": None, "drops": []}
            events = []
            obs = json.loads(json.dumps(obs))
            t0 = time.perf_counter()
            try:
                act = b.act(obs)
            except Exception:
                import traceback
                stats["errors"] += 1
                if stats["errors"] <= 3:
                    traceback.print_exc()
            ms = (time.perf_counter() - t0) * 1000
            times.append(ms)
            mf.draw.take()
            json.dumps(act)
            # weapon pickup
            if "take" in act and act["take"] in pickups:
                k, p = pickups[act["take"]]
                if math.dist(p[:2], me.pos[:2]) < 4:
                    del pickups[act["take"]]
                    if weapons[1] is not None:
                        pickups[9000 + tick] = (weapons[1]["kind"], list(me.pos))
                    weapons[1] = {"kind": k}
                    stats["took"].append((round(t), k))
                    events.append({"type": "took", "id": act["take"], "kind": k, "slot": 1})
            if tick % 20 == 0:
                if math.dist(prev_pos[:2], me.pos[:2]) < 0.5 and math.hypot(*act.get("move", [0, 0])) > 0.5:
                    stats["stuck"] += 1
                prev_pos = list(me.pos)
        # ---- my mech
        mv = act.get("move", [0, 0])
        charging = me.charge > 0
        speed = cfg["mech"]["boost_speed"] if act.get("boost") and me.energy > 1 else cfg["mech"]["walk_speed"]
        if act.get("boost") and me.energy > 1 and math.hypot(*mv) > 0.1:
            me.energy = max(0.0, me.energy - cfg["mech"]["boost_drain"] * DT)
        else:
            me.energy = min(100.0, me.energy + cfg["mech"]["energy_regen"] * DT)
        step_mech(me, mv, speed * (0.5 if charging else 1.0))
        a = act.get("aim", me.aim)
        me.aim[0] = wrap(me.aim[0] + max(-4 * DT, min(4 * DT, wrap(a[0] - me.aim[0]))))
        me.aim[1] += max(-3 * DT, min(3 * DT, a[1] - me.aim[1]))
        fire = act.get("fire", [False, False])
        me.gun_cd = max(0.0, me.gun_cd - DT)
        me.laser_cd = max(0.0, me.laser_cd - DT)
        if me.reload > 0:
            me.reload -= DT
            if me.reload <= 0:
                me.ammo = 12
        if act.get("reload") and me.reload <= 0 and me.ammo < 12:
            me.reload = 2.4
        dirv = [math.cos(me.aim[1]) * math.cos(me.aim[0]), math.cos(me.aim[1]) * math.sin(me.aim[0]), math.sin(me.aim[1])]
        muzzle = [me.pos[0], me.pos[1], me.pos[2] + 7]
        for s, wp in enumerate(weapons):
            if wp is None:
                continue
            if wp["kind"] == "gun" and fire[s] and me.gun_cd <= 0 and me.reload <= 0:
                sp = rng.gauss(0, math.radians(0.6))
                d2 = [math.cos(me.aim[1]) * math.cos(me.aim[0] + sp), math.cos(me.aim[1]) * math.sin(me.aim[0] + sp), math.sin(me.aim[1])]
                bullets.append([muzzle[:], [v * 252 for v in d2], 0, 230 / 252, 45])
                me.gun_cd = 0.24
                me.ammo -= 1
                if me.ammo <= 0:
                    me.reload = 2.4
            elif wp["kind"] == "laser":
                if fire[s] and me.laser_cd <= 0:
                    me.charge = min(0.75, me.charge + DT)
                elif me.charge > 0:  # released
                    for h in hunters:
                        if not h.alive:
                            continue
                        rel = [h.pos[0] - muzzle[0], h.pos[1] - muzzle[1], h.pos[2] + 4.5 - muzzle[2]]
                        along = sum(rel[k] * dirv[k] for k in range(3))
                        perp = math.sqrt(max(0.0, sum(v * v for v in rel) - along * along))
                        if 0 < along < 280 and perp < 2.5 and w.los(me.pos[0], me.pos[1], h.pos[0], h.pos[1]):
                            dmg = 315 * (0.35 + 0.65 * me.charge / 0.75)
                            h.hp -= dmg
                            stats["dealt"] += dmg
                            events.append({"type": "hit", "target": h.id, "amount": dmg, "weapon": "laser"})
                            break
                    me.charge, me.laser_cd = 0.0, 1.65
            elif wp["kind"] == "lightning" and fire[s] and me.gun_cd <= 0.2 and tick % 5 == 0 and me.energy > 3:
                me.energy -= 3
                for h in hunters:
                    if h.alive and math.dist(h.pos[:2], me.pos[:2]) < 45 and abs(wrap(math.atan2(h.pos[1] - me.pos[1], h.pos[0] - me.pos[0]) - me.aim[0])) < 0.5:
                        h.hp -= 60
                        stats["dealt"] += 60
                        break
        # ---- hunters: walk toward me, strafe when they see me, shoot with imperfect lead
        for h in hunters:
            if not h.alive:
                continue
            if h.hp <= 0:
                h.alive = False
                stats["kills"] += 1
                events.append({"type": "kill", "target": h.id})
                for _ in range(2):
                    cubes[next_cube[0]] = [h.pos[0] + rng.uniform(-2, 2), h.pos[1] + rng.uniform(-2, 2), h.pos[2]]
                    next_cube[0] += 1
                continue
            dx, dy = me.pos[0] - h.pos[0], me.pos[1] - h.pos[1]
            d = math.hypot(dx, dy) + 1e-6
            see = d < 200 and w.los(h.pos[0], h.pos[1], me.pos[0], me.pos[1])
            if t > h.strafe_until:
                h.strafe, h.strafe_until = rng.choice([-1, 1]), t + rng.uniform(0.3, 1.0)
            if see and d < 110:
                mvh = [-dy / d * h.strafe + dx / d * (0.5 if d > 80 else -0.3), dx / d * h.strafe + dy / d * (0.5 if d > 80 else -0.3)]
            else:
                c = w.nearest_free(h.pos[0], h.pos[1])
                mvh = [dx / d, dy / d]
                if not w.free(h.pos[0] + mvh[0] * 4, h.pos[1] + mvh[1] * 4):
                    mvh = [-dy / d * h.strafe, dx / d * h.strafe]
            n = math.hypot(*mvh) + 1e-6
            step_mech(h, [mvh[0] / n, mvh[1] / n], cfg["mech"]["walk_speed"])
            h.gun_cd = max(0.0, h.gun_cd - DT)
            h.laser_cd = max(0.0, h.laser_cd - DT)
            if see:
                tof = d / 252
                tx, ty = me.pos[0] + me.vel[0] * tof - h.pos[0], me.pos[1] + me.vel[1] * tof - h.pos[1]
                h.aim = [math.atan2(ty, tx), 0.0]
                if h.gun_cd <= 0 and d < 220:
                    err = rng.gauss(0, math.radians(2.5 * (1.1 - h.skill)))
                    yaw = h.aim[0] + err
                    pitch = math.atan2(me.pos[2] + 4.5 - h.pos[2] - 7, d)
                    bullets.append([[h.pos[0], h.pos[1], h.pos[2] + 7], [252 * math.cos(yaw) * math.cos(pitch), 252 * math.sin(yaw) * math.cos(pitch), 252 * math.sin(pitch)], h.id, 230 / 252, 45])
                    h.gun_cd = 0.24 if rng.random() < 0.8 else 2.4
                if h.has_laser and h.laser_cd <= 0:
                    h.charge += DT
                    if h.charge >= 0.75:
                        h.charge, h.laser_cd = 0.0, 1.65
                        if rng.random() < h.skill:
                            me.hp -= 315
                            stats["taken"] += 315
                            me.last_dmg = t
                            events.append({"type": "damaged", "amount": 315, "weapon": "laser", "bearing": math.atan2(-dy, -dx), "by": h.id})
            else:
                h.charge = 0.0
        # ---- bullets
        keep = []
        for bl in bullets:
            p, v = bl[0], bl[1]
            hit = False
            for sub in range(3):
                for k in range(3):
                    p[k] += v[k] * DT / 3
                if not w.los(p[0], p[1], p[0], p[1]):
                    hit = True
                    break
                targets = hunters if bl[2] == 0 else [me]
                for m in targets:
                    if m.alive and math.hypot(p[0] - m.pos[0], p[1] - m.pos[1]) < 2.8 and m.pos[2] - 0.3 < p[2] < m.pos[2] + 9.3:
                        m.hp -= bl[4]
                        hit = True
                        if m is me:
                            stats["taken"] += bl[4]
                            me.last_dmg = t
                            events.append({"type": "damaged", "amount": bl[4], "weapon": "gun", "bearing": math.atan2(-v[1], -v[0]), "by": bl[2]})
                        else:
                            stats["dealt"] += bl[4]
                            events.append({"type": "hit", "target": m.id, "amount": bl[4], "weapon": "gun"})
                        break
                if not hit and bl[2] == 0:
                    for cid, c in list(crates.items()):
                        if math.hypot(p[0] - c[0][0], p[1] - c[0][1]) < 1.6 and c[0][2] - 0.3 < p[2] < c[0][2] + 2.7:
                            c[1] -= bl[4]
                            hit = True
                            if c[1] <= 0:
                                del crates[cid]
                                cubes[next_cube[0]] = list(c[0])
                                next_cube[0] += 1
                            break
                if hit:
                    break
            bl[3] -= DT
            if not hit and bl[3] > 0:
                keep.append(bl)
        bullets = keep
        # ---- cubes, zone, regen
        for cid, p in list(cubes.items()):
            if math.dist(p[:2], me.pos[:2]) < 3.5:
                del cubes[cid]
                me.cubes += 1
                me.max_hp *= 1.04
                events.append({"type": "pickup", "cubes": me.cubes})
        for m in [me] + hunters:
            if m.alive and math.dist(m.pos[:2], zone["center"]) > zone["radius"]:
                m.hp -= zone["dps"] * DT
                if m is me:
                    stats["zone_dmg"] += zone["dps"] * DT
                    me.last_dmg = t
        if t - me.last_dmg > 5:
            me.hp = min(me.max_hp, me.hp + 45 * DT)
        if me.hp <= 0:
            me.alive = False
            place = 1 + sum(h.alive for h in hunters)
        t += DT
        tick += 1
    times.sort()
    print(json.dumps({"seed": seed, "end_t": round(t, 1), "alive": me.alive, "place": place, "hp": round(me.hp), "cubes": me.cubes,
                      "hunters_left": sum(h.alive for h in hunters), "kills": stats["kills"], "dealt": round(stats["dealt"]), "taken": round(stats["taken"]),
                      "zone_dmg": round(stats["zone_dmg"]), "errors": stats["errors"], "stuck_s": stats["stuck"], "took": stats["took"][:4],
                      "ms_p50": round(times[len(times) // 2], 2), "ms_p99": round(times[int(len(times) * 0.99)], 2), "ms_max": round(times[-1], 2)}))


if __name__ == "__main__":
    main()
