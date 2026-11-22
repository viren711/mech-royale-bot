"""Hackermen duelist: practice-squad play on top of the survivor base (base.py).

Practice (house squad): the 15 house bots never hurt each other, so every point is a house bot that
dies before us. The bot therefore takes fights instead of hiding, and makes each one lopsided:
  - fight at the range our loadout wins (lightning close, laser far, gun middle) and strafe;
  - one target at a time, stick to it, finish anything low;
  - back off to cover only when actually losing (low HP or outnumbered), heal, come back;
  - grab cubes and better weapons, even mid-fight when they are close;
  - walk at full speed (quiet walking cost other teams 0.1-0.25 on the board).
Free-for-all (the final), detected when a mech takes damage we did not deal: hand over to the
survival-first base bot, which hides, heals and only finishes weakened enemies.
"""
from __future__ import annotations

import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import mechfight as mf
import base
from base import hyp, wrap

# Laser first: hitscan to 280 m, and house guns rarely hit past ~100 m.
base.WEAPON_RANK.update({"laser": 3, "lightning": 2, "mortar": 1, "gun": 0})
# No mortar: real-server recordings show 0 hits in 9 shots, v9 held one 15% of the time, and a mech
# holding a mortar takes +60% from lasers (cook-off). Rank it below an empty slot so we never take it,
# and drop one if we are holding it (frees the slot for a laser or lightning).
NO_MORTAR = True
RNG_SALT = 0
if NO_MORTAR:
    base.WEAPON_RANK["mortar"] = -1
# Farm from farther: shoot drones and crates in sight out to 130 m (gun spread 0.6 deg is ~1.4 m at
# 130 m, inside a drone's 1.8 m radius), and walk toward ones seen within 170 m.
base.PARAMS.update({"farm_range": 130.0, "farm_seek_range": 170.0})
# Arm up: 9 of 20 real-server deaths came with only a gun (or gun + mortar). After the opening, still go
# for a laser or lightning remembered within 300 m (was 150 m).
base.PARAMS["arm_late_range"] = 300.0
# Free-for-all switch: one "a mech lost HP and it was not us" event also happens in practice (drones,
# splash), and the squad simulator flipped 5 of 48 practice matches into hiding on it. Ask for three.
base.PARAMS["ffa_ev_needed"] = 3
FARM_STAND_DRONE = 55.0   # m: outside the drone's 45 m aggro range, close enough for accurate fire
FARM_STAND_CRATE = 12.0

DUEL = {
    # preferred fight range by best weapon held (m), and the dead band around it
    "range_lightning": 28.0,
    "range_laser": 125.0,
    "range_gun": 75.0,
    "range_band": 15.0,
    # retreat when losing: HP fraction thresholds by the number of mechs with a line of sight to us
    "retreat_hp_1": 0.35,
    "retreat_hp_2": 0.55,
    "retreat_hp_3": 0.80,
    # finish a target below this HP fraction even when we would otherwise retreat (if we are above 20%)
    "finish_frac": 0.25,
    # heal in place after a fight until this HP fraction, starting below heal_start
    "heal_start": 0.60,
    "heal_until": 0.90,
    # strafe flip interval (s)
    "strafe_min": 0.35,
    "strafe_max": 1.05,
    # mid-fight detours: cubes when healthy / hurt, a better weapon while gun-only / armed
    "fight_cube_m": 70.0,
    "fight_cube_hurt_m": 40.0,
    "fight_weapon_gun_m": 120.0,
    "fight_weapon_armed_m": 35.0,
    # farm drones and crates above this HP fraction
    "farm_hp": 0.45,
    # chase a target that broke line of sight while we are at least this much healthier (fraction)
    "chase_margin": 0.1,
    "chase_range": 150.0,
    # supply drops: take one within drop_range when nothing hostile for drop_quiet_s and no mech known
    # within drop_clear_m of it
    "drops": True,
    "drop_range": 220.0,
    "drop_quiet_s": 6.0,
    "drop_clear_m": 100.0,
    # shoot only mechs that are after us: hit us lately, close, closing in, or nearly dead
    "only_hunters": True,
    "hunt_recent_s": 10.0,
    "hunt_close_m": 60.0,
    "hunt_closing_mps": 3.0,
    "hunt_low_frac": 0.3,
    # target choice: "cost" = least expected HP lost to kill it (absolute HP, both sides' damage rates);
    # "frac" = distance + HP fraction (v1-v9)
    "target_mode": "frac",
    # explore instead of idling: walk to unvisited spots inside the next circle (cells of explore_cell_m)
    "explore": True,
    # v17 candidates: focus the lowest-HP shooter when 2+ shoot at us; fight from a spot only the target sees
    "multi_focus": False,
    # full-strength theme: upgrade order ("plating_first" = v13), keep healing with only non-hunters in
    # sight, explore hop distances
    "upgrade_mode": "plating_first",
    # kill speed: release a partial laser charge when it already kills; close to finish_m on a weak target
    "lethal_laser": True,
    "finish_in": True,
    "finish_m": 14.0,
    "heal_ignore_wanderers": False,
    "explore_r": [90.0, 160.0],
    "isolate": False,
    "spot_radius": 14.0,
    "spot_every_s": 1.0,
    "explore_cell_m": 50.0,
    # last stand: when we would retreat but this many enemies are already within 150 m, retreating rarely
    # saves us (we die with our back turned); fight the weakest instead (99 = off)
    "last_stand_n": 99,
}

PARAMS = DUEL  # simulator overrides ("bot+key=value") land here

UPGRADES = ["plating", "armor", "nanites", "laser_damage", "laser_charge", "gun_damage", "gun_rate",
            "reactor", "lightning_efficiency", "lightning_range", "servos", "gyros", "sensors", "capacitor",
            "gun_mag", "gun_velocity", "lightning_chain", "jets", "laser_pierce", "mortar_reload",
            "mortar_splash", "mortar_velocity"]


class Duelist(base.Bot):
    name = "hackermen-duelist"

    def __init__(self, hello: Dict[str, Any]) -> None:
        super().__init__(hello)
        # RNG salt: identical logic, different random stream per submitted copy (board-noise sampling)
        self.rng.seed((hello.get("seed") or 0) + RNG_SALT)
        self.tgt_id: Optional[int] = None
        self.tgt_t = -99.0
        self.strafe_sign = 1.0
        self.strafe_next = 0.0
        self.healing = False
        self.dead: set = set()
        self.goal_hist: List[Tuple[float, float]] = []
        self.spot: Optional[Tuple[float, float]] = None
        self.spot_t = -99.0
        self.visited: Dict[Tuple[int, int], int] = {}
        self.explore_wp: Optional[Tuple[float, float]] = None
        self.explore_t = -99.0

    # ------------------------------------------------------------------ inputs
    def ingest(self, obs, me, x, y, z, eye_h, t) -> None:
        for e in obs.get("events") or []:
            et = e.get("type")
            if et == "damaged":
                if e.get("weapon") != "zone":
                    self.last_damage_t = t
                    self.last_hostile_t = t
                    if e.get("bearing") is not None:
                        self.dmg_bearing = e["bearing"]
                    if e.get("by") is None:
                        self.last_dmg_anon_t = t
                    else:
                        self.attackers[int(e["by"])] = t
                        self.dmg_by = e["by"]
            elif et == "hit":
                tg = e.get("target")
                if isinstance(tg, int) and tg < 100:
                    self.focus_id, self.focus_t = tg, t
            elif et == "kill":
                tg = e.get("target")
                if isinstance(tg, int):
                    self.attackers.pop(tg, None)
                    self.mem_crate.pop(tg, None)
                    if tg < 100:
                        # forget the dead mech at once: its cubes are ours to collect, not a contested spot
                        self.dead.add(tg)
                        ml = self.mech_last.pop(tg, None)
                        if ml is not None and t - ml[3] < 3.0:
                            self.corpse = (ml[0], ml[1], ml[2], t)
                    if tg == self.focus_id:
                        self.focus_id = None
                    if tg == self.tgt_id:
                        self.tgt_id = None
            elif et == "take_failed":
                self.taken_fail[int(e.get("id", -1))] = t
                if e.get("reason") == "gone":
                    self.mem_pick.pop(int(e.get("id", -1)), None)
            elif et == "took":
                self.mem_pick.pop(int(e.get("id", -1)), None)
        self.update_memory(obs, me, x, y, z, eye_h, t)
        for k in self.dead:
            self.mech_last.pop(k, None)
        for s in obs.get("sounds") or []:
            if s.get("kind") in base.HOSTILE_SOUNDS and s.get("age", 0) < 1.0 and "bearing" in s:
                dd = base.SOUND_DIST.get(s.get("dist"), 110.0)
                b = s["bearing"]
                self.pseudo.append((x + dd * math.cos(b), y + dd * math.sin(b), 0.6, t))
        self.pseudo = [p for p in self.pseudo if t - p[3] < 6.0][-12:]
        self.detect_ffa(obs, t)

    def drop_mortar(self, obs, act: Dict[str, Any]) -> Dict[str, Any]:
        """Drop a held mortar (slot 1) unless this action already takes or drops something."""
        if NO_MORTAR and "take" not in act and "drop" not in act:
            ws = (obs.get("self") or {}).get("weapons") or [None, None]
            w1 = ws[1] if len(ws) > 1 else None
            if w1 and w1.get("kind") == "mortar":
                act["drop"] = 1
        return act

    def pick_spot(self, obs, x, y, z, target, others, t, muz_h) -> Optional[Tuple[float, float]]:
        """A spot within spot_radius on our level from which we still hit the target but that the fewest
        other known enemies can see (their eye to our body centre and top), with a small walk cost."""
        W = self.world
        tx, ty, tz = target["pos"]
        deadline = self.tick_t0 + 0.004
        best, bs = None, -1e9
        cands = [(x, y)] + [(x + r * math.cos(k * math.pi / 6), y + r * math.sin(k * math.pi / 6))
                            for r in (DUEL["spot_radius"] * 0.5, DUEL["spot_radius"]) for k in range(12)]
        for (px, py) in cands:
            if time.perf_counter() > deadline:
                break
            if (px, py) != (x, y):
                if not W.walkable(px, py) or not W.line_clear(x, y, px, py) or self.safe_point(obs, px, py, t) >= 1:
                    continue
            gz = W.floor[W.idx(px, py)]
            if abs(gz - z) > W.rise:
                continue
            if W.sight_blocked((px, py, gz + muz_h), (tx, ty, tz + 4.5)):
                continue  # must keep shooting the target
            seen = 0
            for o in others:
                ox, oy, oz = o["pos"]
                eye = (ox, oy, oz + 8.0)
                if not (W.sight_blocked(eye, (px, py, gz + 4.5)) and W.sight_blocked(eye, (px, py, gz + 8.5))):
                    seen += 1
            sc = -10.0 * seen - hyp(x, y, px, py) / 6.0 + (1.0 if (px, py) == (x, y) else 0.0)
            if sc > bs:
                bs, best = sc, (px, py)
        return best

    def is_hunting(self, m, x, y, dm, frac, t) -> bool:
        """Is this mech after us? (attacked us lately, already our target, close, closing in, or weak)"""
        mid = int(m["id"])
        if t - self.attackers.get(mid, -99) < DUEL["hunt_recent_s"] or (mid == self.tgt_id and t - self.tgt_t < 3.0):
            return True
        if dm < DUEL["hunt_close_m"] or frac < DUEL["hunt_low_frac"]:
            return True
        v = m.get("vel") or [0.0, 0.0, 0.0]
        d = max(1.0, hyp(x, y, m["pos"][0], m["pos"][1]))
        closing = (v[0] * (x - m["pos"][0]) + v[1] * (y - m["pos"][1])) / d
        return closing > DUEL["hunt_closing_mps"]

    def explore_goal(self, obs, x, y, t, me_id) -> Optional[Tuple[float, float]]:
        """Nothing to do: walk to the least-visited reachable spot 90-160 m away that stays inside the next
        circle (and the current one), away from known mechs, so the torso sweep finds drones, crates and
        weapons instead of idling at the zone goal."""
        W = self.world
        cell = DUEL["explore_cell_m"]
        k0 = (int(x // cell), int(y // cell))
        self.visited[k0] = self.visited.get(k0, 0) + 1
        if self.explore_wp is not None and hyp(x, y, *self.explore_wp) > 8 and t - self.explore_t < 20 \
                and self.safe_point(obs, *self.explore_wp, t) < 1:
            return self.explore_wp
        zn = obs["zone"]
        ncx, ncy, nr = zn["next_center"][0], zn["next_center"][1], zn["next_radius"]
        cx, cy, cr = zn["center"][0], zn["center"][1], zn["radius"]
        known = self.known_mechs(t, me_id)
        best, bs = None, -1e9
        for k in range(16):
            a = k * math.pi / 8 + (0.2 if int(t) % 2 else 0.0)
            for r in DUEL["explore_r"]:
                px, py = x + r * math.cos(a), y + r * math.sin(a)
                if hyp(px, py, ncx, ncy) > max(10.0, nr - 15.0) or hyp(px, py, cx, cy) > cr - 15.0:
                    continue
                if W is not None and not W.walkable(px, py):
                    continue
                ci, cj = int(px // cell), int(py // cell)
                seen = sum(self.visited.get((ci + i, cj + j), 0) for i in (-1, 0, 1) for j in (-1, 0, 1))
                sc = -seen - r / 100.0 - 3.0 * self.safe_point(obs, px, py, t)
                sc -= 20.0 * sum(1 for (kx, ky) in known if hyp(kx, ky, px, py) < 120.0)
                if sc > bs:
                    bs, best = sc, (px, py)
        self.explore_wp, self.explore_t = best, t
        return best

    def farm_seek(self, obs, x, y, z) -> Optional[Tuple[float, float]]:
        """Walk toward the nearest seen drone (2 cubes) or crate (1 cube) in the safe zone, stopping
        outside drone aggro range (they only chase when shot) or next to a crate."""
        best, bd = None, base.PARAMS["farm_seek_range"]
        t = obs["t"]
        for m in obs.get("mechs") or []:
            if m.get("kind") == "npc":
                px, py, pz = m["pos"]
                d = hyp(x, y, px, py)
                if d < bd and abs(pz - z) < 5 and self.safe_point(obs, px, py, t) < 1:
                    best, bd = (px, py, FARM_STAND_DRONE), d
        for c in obs.get("crates") or []:
            px, py, pz = c["pos"]
            d = hyp(x, y, px, py)
            if d < bd and abs(pz - z) < 4 and self.safe_point(obs, px, py, t) < 1:
                best, bd = (px, py, FARM_STAND_CRATE), d
        if best is None:
            return None
        px, py, stand = best
        if bd <= stand:
            return None
        f = (bd - stand) / bd
        return (x + (px - x) * f, y + (py - y) * f)

    def drop_goal(self, obs, x, y, t, me_id) -> Optional[Tuple[float, float]]:
        """The nearest supply drop worth taking: in range, landed or landing by the time we arrive, inside
        the zone a while longer, not held by another mech, no mech known near it, nothing hostile lately.
        Standing alone in its ring for capture_s gives +3 cubes, full HP and full energy."""
        if t - self.last_hostile_t < DUEL["drop_quiet_s"]:
            return None
        known = self.known_mechs(t, me_id)
        best, bd = None, DUEL["drop_range"]
        for d in obs.get("drops") or []:
            try:
                px, py = d["pos"][0], d["pos"][1]
            except Exception:
                continue
            holder = d.get("holder")
            if holder is not None and holder != -1 and holder != me_id:
                continue
            dist = hyp(x, y, px, py)
            lands = d.get("lands_in") or 0.0
            if dist > bd or lands > dist / max(1.0, self.walk) + 3.0:
                continue
            if self.safe_point(obs, px, py, t + max(lands, 0.0) + 6.0) >= 1:
                continue
            if any(hyp(kx, ky, px, py) < DUEL["drop_clear_m"] for kx, ky in known):
                continue
            best, bd = (px, py), dist
        return best

    # ------------------------------------------------------------------ decision
    def _act(self, obs: Dict[str, Any], t0: float) -> Dict[str, Any]:
        if self.ffa:
            return self.drop_mortar(obs, base.Bot._act(self, obs, t0))
        me = obs["self"]
        t = obs["t"]
        x, y, z = me["pos"]
        vx, vy = me["vel"][0], me["vel"][1]
        hp, mhp = me["hp"], max(1.0, me["max_hp"])
        hpf = hp / mhp
        stats = me.get("stats") or {}
        eye_h = stats.get("eye_height", 8.0)
        muz_h = stats.get("muzzle_height", 7.0)
        energy = me.get("energy", 0.0) or 0.0
        W = self.world
        act: Dict[str, Any] = {}
        self.ingest(obs, me, x, y, z, eye_h, t)

        off = obs.get("offer")
        if off and off.get("choices"):
            order = UPGRADES
            if DUEL["upgrade_mode"] == "nanites_first":
                order = ["nanites", "plating", "armor"] + [u for u in UPGRADES if u not in ("nanites", "plating", "armor")]
            elif DUEL["upgrade_mode"] == "damage_first":
                order = ["laser_damage", "gun_damage", "plating", "laser_charge", "gun_rate", "armor", "nanites"] + \
                    [u for u in UPGRADES if u not in ("laser_damage", "gun_damage", "plating", "laser_charge", "gun_rate", "armor", "nanites")]
            ranks = [order.index(c.get("id")) if c.get("id") in order else 99 for c in off["choices"]]
            act["pick"] = ranks.index(min(ranks))

        weapons = me.get("weapons") or [None, None]
        kinds = [w.get("kind") for w in weapons if w]
        my_id = me.get("id")
        enemies = [m for m in obs.get("mechs") or []
                   if m.get("kind") == "mech" and m.get("id") != my_id and m.get("id") not in self.dead]
        npcs = [m for m in obs.get("mechs") or [] if m.get("kind") == "npc"]
        enemies.sort(key=lambda m: hyp(x, y, m["pos"][0], m["pos"][1]))
        if enemies:
            self.last_hostile_t = t

        # who can shoot us right now (line of sight from their eye to our body)
        shooters = []
        for m in enemies[:6]:
            mx, my_, mz = m["pos"]
            dm = math.dist((x, y, z), (mx, my_, mz))
            if dm > 285:
                continue
            if W and W.sight_blocked((mx, my_, mz + eye_h), (x, y, z + 4.5)) and \
                    W.sight_blocked((mx, my_, mz + eye_h), (x, y, z + 8.5)):
                continue
            shooters.append((m, dm))
        n_threat = len([1 for (m, dm) in shooters if dm < 200 or t - self.attackers.get(int(m["id"]), -99) < 3])

        my_mult = 1.0 + 0.04 * min(me.get("cubes", 0) or 0, 10)
        my_speed = math.hypot(vx, vy)
        # ---- target: one mech at a time, sticky, weakest and closest first, attackers first
        target, best = None, 1e9
        for m in enemies[:6]:
            mx, my_, mz = m["pos"]
            dm = math.dist((x, y, z), (mx, my_, mz))
            if dm > 280:
                continue
            if W and W.sight_blocked((x, y, z + muz_h), (mx, my_, mz + 4.0)):
                continue
            mid = int(m["id"])
            frac = (m.get("hp") or 1400.0) / max(1.0, m.get("max_hp") or 1400.0)
            if DUEL["only_hunters"] and not self.is_hunting(m, x, y, dm, frac, t):
                continue  # a house bot we damage joins the hunt: leave the ones not after us alone
            friends = sum(1 for o in enemies if o is not m and hyp(o["pos"][0], o["pos"][1], mx, my_) < 40)
            if DUEL["target_mode"] == "cost":
                # expected HP we lose killing it: its absolute HP over our damage rate at this range, times
                # its damage rate on us (its visible weapons and cubes); friends near it shoot back too
                tv = m.get("vel") or [0.0, 0.0, 0.0]
                our = my_mult * sum(self.weapon_dps(k, dm, math.hypot(tv[0], tv[1])) for k in kinds)
                tk = [k if isinstance(k, str) else (k or {}).get("kind") for k in (m.get("weapons") or ["gun"])]
                tmult = 1.0 + 0.04 * min(m.get("cubes") or 0, 10)
                their = 0.8 * tmult * sum(self.weapon_dps(k, dm, my_speed) for k in tk)
                ttk = (m.get("hp") or 1400.0) / max(our, 1.0)
                cost = ttk * their * (1.0 + 0.7 * friends) + dm * 0.5
                if t - self.attackers.get(mid, -99) < 3.0:
                    cost *= 0.6
                if mid == self.tgt_id and t - self.tgt_t < 2.0:
                    cost *= 0.7
            else:
                cost = dm + 120.0 * frac + 25.0 * friends
                if t - self.attackers.get(mid, -99) < 3.0:
                    cost -= 50.0
                if mid == self.tgt_id and t - self.tgt_t < 2.0:
                    cost -= 40.0
            if cost < best:
                best, target = cost, m
        if DUEL["multi_focus"] and n_threat >= 2:
            # several shooters: kill the one with the least HP first (fastest cut in incoming damage)
            vis = []
            for m in enemies[:6]:
                mx, my_, mz = m["pos"]
                dm = math.dist((x, y, z), (mx, my_, mz))
                if dm > 230 or (W and W.sight_blocked((x, y, z + muz_h), (mx, my_, mz + 4.0))):
                    continue
                if t - self.attackers.get(int(m["id"]), -99) < 5.0 or dm < 120:
                    vis.append(((m.get("hp") or 1400.0) + 2.0 * dm, m))
            if vis:
                target = min(vis, key=lambda q: q[0])[1]
        if target is not None:
            if int(target["id"]) != self.tgt_id:
                self.tgt_id = int(target["id"])
            self.tgt_t = t
        tfrac = None
        if target is not None:
            tfrac = (target.get("hp") or 1400.0) / max(1.0, target.get("max_hp") or 1400.0)

        # ---- losing? (retreat to cover, keep shooting back)
        retreat = False
        if n_threat >= 3 and hpf < DUEL["retreat_hp_3"]:
            retreat = True
        elif n_threat >= 2 and hpf < DUEL["retreat_hp_2"]:
            retreat = True
        elif hpf < DUEL["retreat_hp_1"] and (tfrac is None or hpf < tfrac + 0.1):
            retreat = True
        finishing = target is not None and tfrac is not None and tfrac < DUEL["finish_frac"] and hpf > 0.2 \
            and n_threat <= 2
        if finishing:
            retreat = False
        if retreat and target is not None:
            near150 = sum(1 for m in enemies if hyp(x, y, m["pos"][0], m["pos"][1]) < 150)
            if near150 >= DUEL["last_stand_n"]:
                retreat = False
                weak = [m for m in enemies if hyp(x, y, m["pos"][0], m["pos"][1]) < 150 and not (
                    W and W.sight_blocked((x, y, z + muz_h), (m["pos"][0], m["pos"][1], m["pos"][2] + 4.0)))]
                if weak:
                    target = min(weak, key=lambda m: m.get("hp") or 1400.0)
                    tfrac = (target.get("hp") or 1400.0) / max(1.0, target.get("max_hp") or 1400.0)

        # ---- heal after fights (regen 45 HP/s starts 5 s after the last damage dealt or taken)
        quiet = not enemies and t - self.last_damage_t > 3.0
        if quiet and hpf < DUEL["heal_start"]:
            self.healing = True
        heal_block = [m for m in enemies if not DUEL["heal_ignore_wanderers"]
                      or self.is_hunting(m, x, y, hyp(x, y, m["pos"][0], m["pos"][1]), 1.0, t)]
        if DUEL["heal_ignore_wanderers"] and quiet is False and not heal_block and t - self.last_damage_t > 3.0 \
                and hpf < DUEL["heal_start"]:
            self.healing = True
        if hpf >= DUEL["heal_until"] or (heal_block and hpf >= 0.5):
            self.healing = False

        # ---- zone timing
        zone = obs["zone"]
        zgx, zgy, _ = self.zone_goal(obs, x, y)
        zdist = hyp(x, y, zgx, zgy)
        cx, cy, cr = zone["center"][0], zone["center"][1], zone["radius"]
        out_now = not me.get("in_zone", True) or hyp(cx, cy, x, y) > cr
        edge_t = self.edge_time(zone, x, y, t)
        time_left = max(1.0, min(zone["shrink_end"], edge_t) - t - 8.0)
        need_speed = zdist * 1.3 / time_left
        zone_urgent = out_now or need_speed > 0.6 * self.walk or (zone["shrink_start"] - t < 12 and zdist > 5)

        threats = [(m["pos"][0], m["pos"][1], m["pos"][2], 2.0) for m in enemies[:4]]
        threats += [(p[0], p[1], W.ground_at(p[0], p[1]) if W else z, p[2]) for p in self.pseudo[-4:]]

        goal: Optional[Tuple[float, float]] = None
        boost = False
        hold = False          # fighting in place: strafe only
        mode = "travel"
        if zone_urgent and (out_now or zdist > 8):
            goal, mode = (zgx, zgy), "zone"
            boost = out_now and energy > 20
        elif retreat and threats:
            if W and (self.cover is None or t - self.cover_t > 0.5):
                self.choose_cover(obs, x, y, z, threats, t)
            if self.cover is not None and hyp(x, y, *self.cover) > 2.0:
                goal, mode = self.cover, "retreat"
                boost = hpf < 0.5 and energy > 30 and hyp(x, y, *self.cover) > 10
            else:
                hold, mode = True, "retreat-hold"
        elif target is not None:
            mode = "fight"
            d = hyp(x, y, target["pos"][0], target["pos"][1])
            if "lightning" in kinds and energy > 25:
                pref = DUEL["range_lightning"]
            elif "laser" in kinds:
                pref = DUEL["range_laser"]
            else:
                pref = DUEL["range_gun"]
            if finishing and DUEL["finish_in"]:
                pref = DUEL["finish_m"]  # close right in: gun ~0.97 hit at 0-25 m, lightning in range
            elif finishing and pref > 50:
                pref = 50.0
            band = DUEL["range_band"]
            if d > pref + band:
                goal = (target["pos"][0], target["pos"][1])
                mode = "fight-close"
            elif d < pref - band:
                ax, ay = (x - target["pos"][0]) / max(d, 1e-3), (y - target["pos"][1]) / max(d, 1e-3)
                bx, by = x + 20 * ax, y + 20 * ay
                if W is None or (W.walkable(bx, by) and self.safe_point(obs, bx, by, t) < 1):
                    goal = (bx, by)
                    mode = "fight-back"
                else:
                    hold = True
            else:
                hold = True
            # with more than one enemy around, fight from a nearby spot where the others can't see us
            if DUEL["isolate"] and W is not None and hold:
                others = [m for m in enemies[:5] if m is not target]
                if others:
                    if self.spot is None or t - self.spot_t > DUEL["spot_every_s"]:
                        self.spot, self.spot_t = self.pick_spot(obs, x, y, z, target, others, t, muz_h), t
                    if self.spot is not None and hyp(x, y, *self.spot) > 2.0:
                        goal, hold, mode = self.spot, False, "fight-spot"
            # a close cube or a better weapon is worth the detour while we keep shooting
            gun_only = not any(k in ("laser", "lightning") for k in kinds)
            wmax = DUEL["fight_weapon_gun_m"] if gun_only else DUEL["fight_weapon_armed_m"]
            fa = self.econ_goal(obs, me, x, y, z, t, act, False, wmax=wmax, weapons_only=True)
            if fa is None:
                cr_save = base.PARAMS["cube_range"]
                base.PARAMS["cube_range"] = DUEL["fight_cube_m"] if hpf > 0.5 else DUEL["fight_cube_hurt_m"]
                try:
                    fa = self.econ_goal(obs, me, x, y, z, t, act, False, wmax=0.0)
                finally:
                    base.PARAMS["cube_range"] = cr_save
            if fa is not None:
                goal, hold, mode = fa[0], False, "fight-" + fa[1]
        elif self.healing:
            mode = "heal"
            if threats and W:
                if self.cover is None or t - self.cover_t > 1.0:
                    self.choose_cover(obs, x, y, z, threats, t)
                if self.cover is not None and hyp(x, y, *self.cover) > 2.0:
                    goal = self.cover
        else:
            chase = None
            if self.focus_id is not None and t - self.focus_t < 6.0 and t < self.endgame_t:
                for m in enemies:
                    if int(m["id"]) == self.focus_id:
                        fr = (m.get("hp") or 1400.0) / max(1.0, m.get("max_hp") or 1400.0)
                        if fr + DUEL["chase_margin"] < hpf and hyp(x, y, m["pos"][0], m["pos"][1]) < DUEL["chase_range"]:
                            chase = m
                        break
            if chase is not None:
                goal, mode = (chase["pos"][0], chase["pos"][1]), "chase"
                target = chase
            else:
                econ = None
                # a supply drop is +3 cubes and a full heal, so it is not gated on HP
                dg = self.drop_goal(obs, x, y, t, my_id) if DUEL["drops"] and not zone_urgent else None
                if dg is not None:
                    econ = (dg, "drop")
                elif hpf >= 0.4 and t < self.T["final_center_t"]:
                    econ = self.econ_goal(obs, me, x, y, z, t, act, zone_urgent and zdist > 8)
                if econ is not None:
                    goal, mode = econ
                else:
                    fg = None
                    if hpf >= DUEL["farm_hp"] and t < self.endgame_t and need_speed < 0.4 * self.walk:
                        fg = self.farm_seek(obs, x, y, z)
                    eg = None
                    if fg is None and DUEL["explore"] and hpf >= 0.5 and t < self.endgame_t and not zone_urgent:
                        eg = self.explore_goal(obs, x, y, t, my_id)
                    if fg is not None:
                        goal, mode = fg, "farm-seek"
                    elif eg is not None:
                        goal, mode = eg, "explore"
                    elif zdist > 3:
                        goal, mode = (zgx, zgy), "travel"
                    else:
                        mode = "camp"

        # ---- movement vector
        mv = [0.0, 0.0]
        gdir = None
        if goal is not None:
            mv = self.steer(x, y, goal, t, me)
            n = math.hypot(*mv)
            if n > 0:
                gdir = (mv[0] / n, mv[1] / n)
                mv = list(gdir)
            if hyp(x, y, *goal) < 2.0:
                mv, gdir = [0.0, 0.0], None
        # strafe across the line of fire of the nearest shooter (or the target) while in a fight
        fight_ref = target if target is not None else (shooters[0][0] if shooters else None)
        strafing = False
        if fight_ref is not None and mode not in ("zone",) and target is not None and target.get("kind") == "mech":
            if t >= self.strafe_next:
                self.strafe_sign = -self.strafe_sign
                self.strafe_next = t + self.rng.uniform(DUEL["strafe_min"], DUEL["strafe_max"])
            b = math.atan2(fight_ref["pos"][1] - y, fight_ref["pos"][0] - x)
            px, py = -math.sin(b) * self.strafe_sign, math.cos(b) * self.strafe_sign
            if W is not None and not W.line_clear(x, y, x + 6 * px, y + 6 * py):
                self.strafe_sign = -self.strafe_sign
                px, py = -px, -py
            if gdir is None:
                mv = [px, py]
            else:
                dp = px * gdir[0] + py * gdir[1]
                if dp < 0:
                    px, py = px - dp * gdir[0], py - dp * gdir[1]
                mv = [gdir[0] * 0.7 + px * 0.7, gdir[1] * 0.7 + py * 0.7]
            strafing = True
            # a laser charging at us: boost sideways (hitscan, can't be outrun, but can be out-strafed)
            for m in enemies:
                if m.get("charging") and m.get("aim"):
                    ma = m["aim"][0]
                    dm = hyp(x, y, m["pos"][0], m["pos"][1])
                    if abs(wrap(math.atan2(y - m["pos"][1], x - m["pos"][0]) - ma)) < math.atan2(self.radius, max(1.0, dm)) + 0.15:
                        if energy > 25 and me.get("grounded", True):
                            boost = True
                        break
        dodge = self.mortar_dodge(obs, x, y, z, vx, vy, t)
        if dodge is not None:
            mv = list(dodge)
            boost = energy > 10 and me.get("grounded", True)
            mode = "dodge"
        n = math.hypot(*mv)
        if n > 1e-6:
            mv = [mv[0] / n, mv[1] / n]

        # ---- stuck: only judged while walking to a goal (not while strafing in place or charging)
        jump = False
        charging = any(w and w.get("kind") == "laser" and (w.get("charge") or 0) > 0 for w in weapons)
        if goal is not None and not strafing and not charging and mode != "dodge":
            self.goal_hist.append((x, y))
            del self.goal_hist[:-11]
            if len(self.goal_hist) == 11 and hyp(self.goal_hist[0][0], self.goal_hist[0][1], x, y) < 1.5:
                self.stuck_n += 1
            else:
                self.stuck_n = max(0, self.stuck_n - 1)
        else:
            self.goal_hist.clear()
            self.stuck_n = 0
        if self.stuck_n >= 5 and t > self.unstick_until + 1.0:
            self.unstick_until = t + 1.2
            self.unstick_dir = -self.unstick_dir
            self.stuck_n = 0
            self.planner, self.path, self.plan_t = None, None, -99
        if t < self.climb_until and goal is not None and not charging:
            if me.get("grounded", True):
                jump = True
            boost = energy > 10
        elif t < self.unstick_until and goal is not None:
            if me.get("grounded", True):
                jump = True
            boost = energy > 15
            px, py = -mv[1], mv[0]
            mv = [mv[0] + 0.5 * self.unstick_dir * px, mv[1] + 0.5 * self.unstick_dir * py]
            n = math.hypot(*mv) or 1.0
            mv = [mv[0] / n, mv[1] / n]

        # ---- aim and fire
        fire = [False, False]
        aim = None
        shoot_at = target
        if shoot_at is None and hpf >= DUEL["farm_hp"] and t < self.endgame_t and not enemies:
            shoot_at = self.farm_target(obs, x, y, z, muz_h)
        if shoot_at is None:
            # drones shooting us
            for nn in npcs:
                if t - self.attackers.get(int(nn["id"]), -99) < 3.0:
                    shoot_at = nn
                    break
        if shoot_at is not None:
            aim, fire = self.fire_control(me, shoot_at, weapons, x, y, z, muz_h)
            if DUEL["lethal_laser"] and shoot_at.get("kind") == "mech":
                # let go of a partial laser charge as soon as it already kills the target
                cur = me.get("aim") or self.last_aim
                tb = math.atan2(shoot_at["pos"][1] - y, shoot_at["pos"][0] - x)
                dt_ = max(1.0, hyp(x, y, shoot_at["pos"][0], shoot_at["pos"][1]))
                on = abs(wrap(tb - cur[0])) < math.atan2(self.radius * 0.8, dt_)
                for sl, wpn in enumerate(weapons):
                    if wpn and wpn.get("kind") == "laser" and (wpn.get("charge") or 0) > 0 and on:
                        st = wpn.get("stats") or {}
                        full = st.get("charge", 0.75) or 0.75
                        mn = st.get("min_frac", 0.35)
                        dmg = st.get("damage", 315.0) * (mn + (1 - mn) * min(1.0, wpn["charge"] / full)) * my_mult
                        if (shoot_at.get("hp") or 1e9) <= 0.95 * dmg:
                            fire[sl] = False
            if mode == "heal" and shoot_at.get("kind") != "mech":
                fire = [False, False]  # dealing damage restarts the regen clock
        if aim is None:
            aim = self.scan_aim(obs, x, y, t, mv, threats)
        g0 = weapons[0] if weapons else None
        if g0 and g0.get("kind") == "gun" and not g0.get("reload"):
            ammo = g0.get("ammo", 12)
            if ammo == 0 or (shoot_at is None and ammo < 8):
                act["reload"] = True

        self.last_aim = aim
        n = math.hypot(*mv)
        if n > 0.998:
            mv = [mv[0] * 0.998 / n, mv[1] * 0.998 / n]
        act.update(move=[round(mv[0], 3), round(mv[1], 3)], aim=[round(aim[0], 4), round(aim[1], 4)],
                   fire=fire, boost=bool(boost), jump=bool(jump))
        self.drop_mortar(obs, act)
        self.mode = mode
        mf.draw.label(f"S {mode} hp{hp:.0f} th{n_threat} tg{self.tgt_id}")
        return act


Bot = Duelist  # the name the kit wrapper and our simulator look for

if __name__ == "__main__":
    try:
        mf.run(Duelist)
    finally:
        try:
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(0)
