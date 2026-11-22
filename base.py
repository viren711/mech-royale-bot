"""Survival-first mech bot v2 (mechfight/1).

Priorities every decision (0.1 s):
 1. stay out of the zone: rotate early toward the edge of the *next* circle, timed on the remaining
    path length; from the last two phases on hold the final centre and keep HP full (HP race);
 2. dodge what can be dodged (mortar shells by predicted impact point, gun fire at long range by
    lateral jinks) and keep the torso on the most dangerous threat (charging lasers first);
 3. engagement gate: fight only when our predicted time-to-kill beats theirs (Lanchester/TTK
    check over every enemy with line of sight to us); otherwise break LOS to cover and regen;
 4. fire discipline: shoot only when the predicted hit probability (spread + target motion +
    current torso error) is high enough; bullets lead the target with the intercept solution;
 5. loot weapons / cubes when quiet, survival upgrades first;
 6. never crash: any error falls back to a safe action (keep moving to the zone, keep aim).

Every number below is either read from `hello.config` or derived from it; genuinely free
parameters live in PARAMS with what they trade off (to be tuned on practice runs).
"""
from __future__ import annotations

import math
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import mechfight as mf

try:
    import world as worldmod
except Exception:  # pragma: no cover - world module is shipped next to the bot
    worldmod = None

TAU = 2 * math.pi
SQRT2 = math.sqrt(2.0)

# Free parameters (everything else comes from hello.config). Each comment says what it trades off.
PARAMS = {
    # Fire discipline: minimum predicted hit probability per gun bullet. Lower = more DPS at long
    # range, but wasted ammo (reload 2.4 s) and a gun sound heard at 320 m for little damage.
    "gun_min_hit_p": 0.12,
    # Laser release threshold: a miss costs a full charge + cooldown (2.4 s), so it is stricter.
    "laser_min_hit_p": 0.60,
    # Assumed random acceleration (m/s^2) of a target during the bullet flight, for hit prediction.
    # 0 = trust constant-velocity lead fully; ground accel max is 58.5 (a hard jinker).
    "target_accel_sigma": 6.0,
    # Engagement gate: engage when ttk_us < k * ttk_them. >1 = take even fights (practice: kills
    # are the only points), <1 = only clearly favourable fights (final FFA: survival is the score).
    # v3: squad practice = each house-bot death before ours is +1 place, and house bots only die to
    # us or the zone, so take even-to-unfavourable fights (k > 1). FFA mode uses ffa_engage_k.
    "engage_k": 1.6,
    "ffa_engage_k": 0.7,
    # Below this HP fraction we disengage to regen (45 HP/s after 5 s) unless the target is nearly dead.
    "retreat_hp": 0.35,
    # A target at or below this HP fraction is a "finishing" kill: always taken if we out-race it.
    "finish_frac": 0.3,
    # Chase a recently damaged target (memory gives its true position for 5 s) when our HP is above this.
    "chase_min_hp": 0.5,
    "chase_range": 120.0,
    # In the last two zone phases (HP race, 260 dps final zone ignores armor) k is multiplied by this.
    "endgame_k_mult": 0.5,
    # Enemy aim quality relative to our own hit model (1 = they lead as well as we do). Unknown
    # for house bots; higher = more cautious gate.
    "enemy_aim_mult": 0.8,
    # Remaining-path / straight-line ratio assumed before a path is planned (city blocks ~1.3).
    "detour": 1.3,
    # Extra seconds of slack when timing the rotation into the next circle (cover, fights).
    "zone_slack_s": 10.0,
    # Margin (m) added to the mortar splash radius + our radius when deciding to dodge a shell.
    "mortar_margin": 1.5,
    # Cover search radius (m). Larger finds cover more often but means longer exposed runs
    # (11.7 m/s walk: 48 m ~ 4 s, about one gun magazine of incoming fire).
    "cover_radius": 48.0,
    # Farm drones / crates for cubes when nothing hostile is near and HP is above this fraction
    # (replay winner farmed 16 cubes). Higher = safer, fewer cubes; firing is heard at 320 m.
    "farm_min_hp": 0.6,
    "farm_range": 60.0,
    # v3: actively walk to drones / crates seen within this distance while quiet (before endgame).
    "farm_seek_range": 120.0,
    # v4 card A, defeat in detail (Lanchester n^2: we beat one hunter, lose to two). Optional mech
    # fights only when <= detail_max_hunters known hunters are within detail_range and the target's
    # HP <= detail_hp_ratio x ours; any second hunter seen/heard within detail_abort_range aborts.
    "detail_range": 120.0,
    # v5.2 card 2: evidence events (third-party HP drop > 3 drone bullets, or a death we did not cause
    # before the first shrink) needed to switch to FFA rules. The hello has no mode field.
    "ffa_ev_needed": 1,
    # evidence before ffa_min_t s is ignored (cuts squad false switches; FFA replays: 75% still detected by 20 s)
    "ffa_min_t": 8.0,
    # v5 loot: a pickup more than loot_roof_dz above the terrain under it is on a roof; before
    # loot_early_t (first hunters arrive) weapon pickups are sought up to loot_early_range.
    "loot_roof_dz": 2.0,
    "loot_early_t": 45.0,
    "loot_early_range": 200.0,
    "detail_max_hunters": 1,
    "detail_hp_ratio": 1.2,
    "detail_abort_range": 100.0,
    # After each kill: break LOS, move >= recover_move_m silently, regen to >= recover_hp first.
    "recover_hp": 0.95,
    "recover_move_m": 20.0,
    # v4 card B, endgame: no optional fights from no_fight_t; walk to the final centre from
    # final_center_t; survive mode when alive <= survive_alive after survive_t; lightning on a
    # cluster of >= cluster_n hunters within lightning range after cluster_t.
    "no_fight_t": 340.0,
    "final_center_t": 350.0,
    "survive_alive": 3,
    "survive_t": 300.0,
    "cluster_t": 375.0,
    "cluster_n": 3,
    # v4 card D: silent walk fraction of max speed (< 5 m/s makes no step sound).
    "silent_move": 0.40,
    # v4 card C: in the last inner_edge_phases phases camp at inner_edge_frac of the next radius from
    # its centre, on the side facing the hunters, so they approach through the zone edge.
    "inner_edge_frac": 0.6,
    "inner_edge_phases": 3,
    # Probe P1: never fire at mechs (score = zone/NPC deaths + jackpot only). False in real play.
    "pacifist": False,
    # ---- p-econ (architecture review I1/I3/I4)
    # The absolute times above (no_fight_t .. cluster_t) are tuned on the stream zone timeline
    # (415 s total, first hold 60 s); at hello they are rescaled to the timeline the config gives.
    "ref_timeline_s": 415.0,
    "ref_first_hold_s": 60.0,
    # Arm-up window as a multiple of the first hold (only one, weakest, hunter is out): head for the
    # nearest remembered laser / lightning (mortar costs mortar_cost x its distance).
    "arm_hold_mult": 1.5,
    "arm_range": 350.0,
    "arm_late_range": 150.0,
    "mortar_cost": 2.5,
    # extra metres charged for a roof pickup (jet climb, exposure); climbs above max_climb_frac of
    # what a full tank lifts us (100 energy / 15 per s x 8.9 m/s ~ 59 m) are skipped
    "roof_cost_m": 25.0,
    "max_climb_frac": 0.7,
    # remembered cubes are walked to within this range (v5.1: 60 m and only while visible)
    "cube_range": 150.0,
    # after a mech kill, loot its drop (all its cubes + 2, its weapons) for this long if nobody has LOS
    "corpse_s": 20.0,
    "econ_min_hp": 0.5,
    # while fighting, walk to a better weapon within this range (keeps firing on the way)
    "fight_arm_range": 70.0,
    # econ trips under fire only when ttk_them >= econ_ttk_mult x the trip time
    "econ_ttk_mult": 4.0,
    # a camp spot is kept while the zone goal is within this distance (the camp cover radius)
    "camp_stay_m": 24.0,
    "cube_dz": 6.0,
    # give up on a loot goal that got no closer by 2 m in this many seconds (blocked climb, bad path)
    "econ_giveup_s": 8.0,
    # I3: keep a chosen movement mode at least this long unless a hard trigger fires
    "mode_commit_s": 1.5,
    "dmg_spike_frac": 0.15,
}
# v2: lightning first. Measured on the public replay: the winner went gun+lightning (3,000 dmg on
# 33 lightning hits at 16-43 m); lightning also beats laser in the triangle (short cancels charge).
WEAPON_RANK = {"lightning": 3, "laser": 2, "mortar": 1, "gun": 0}
# plating first: +15% max HP raises every TTK comparison and is the only lever on the endgame HP race
# (zone damage ignores armor); nanites shorten the 5 s regen delay; armor only cuts weapon damage.
UPGRADE_PRIORITY = ["plating", "nanites", "armor", "reactor", "sensors", "servos", "laser_damage",
                    "gun_damage", "gun_rate", "laser_charge", "capacitor", "gyros", "jets",
                    "lightning_range", "lightning_efficiency", "lightning_chain", "gun_mag",
                    "gun_velocity", "mortar_splash", "mortar_reload", "mortar_velocity", "laser_pierce"]
SOUND_DIST = {"near": 40.0, "mid": 110.0, "far": 230.0}
HOSTILE_SOUNDS = {"step", "boost", "jet", "gun", "laser_charge", "laser", "lightning", "mortar", "reload"}


def wrap(a: float) -> float:
    return (a + math.pi) % TAU - math.pi


def ncdf(v: float) -> float:
    return 0.5 * (1.0 + math.erf(v / SQRT2))


def p_within(mu: float, sigma: float, half: float) -> float:
    """P(|mu + N(0, sigma)| < half): a Gaussian miss offset landing inside a half-width."""
    if sigma < 1e-6:
        return 1.0 if abs(mu) < half else 0.0
    return max(0.0, ncdf((half - mu) / sigma) - ncdf((-half - mu) / sigma))


def hyp(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)


def find_map_dir(hello: Dict[str, Any]) -> Optional[str]:
    d = (hello.get("map") or {}).get("dir") or "/arena"
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (d, os.path.join(os.getcwd(), d), os.path.join(here, d), "/arena",
                 os.path.join(here, "..", "arena"), os.path.join(here, "arena")):
        try:
            if os.path.isfile(os.path.join(cand, "v2", "world.json")):
                return cand
        except Exception:
            pass
    return None


class Bot:
    name = "survivor-v5"

    def __init__(self, hello: Dict[str, Any]) -> None:
        cfg = hello.get("config") or {}
        self.cfg = cfg
        self.me_id = hello.get("slot")
        w = cfg.get("weapons") or {}
        self.gun_speed = (w.get("gun") or {}).get("speed", 252.0)
        self.mortar_speed = (w.get("mortar") or {}).get("speed", 72.0)
        self.mortar_g = (w.get("mortar") or {}).get("gravity", 22.0)
        self.light_range = (w.get("lightning") or {}).get("range", 45.0)
        self.light_cone = math.radians((w.get("lightning") or {}).get("cone_deg", 30.0))
        self.laser_charge = (w.get("laser") or {}).get("charge", 0.75)
        self.reach = (cfg.get("loot") or {}).get("pickup_radius", 4.0)
        # v5: FFA evidence needs an HP drop larger than 3 drone bullets (unseen drones hit too)
        self.ffa_drop = max(40.0, 3.0 * float((cfg.get("npc") or {}).get("damage", 25)) + 1.0)
        self.near_range = (cfg.get("vision") or {}).get("near_range", 45.0)
        # ---- v2: everything the gate / aim / dodge needs, derived from the live config
        self.wcfg = {k: dict(v) for k, v in w.items() if isinstance(v, dict)}
        g = self.wcfg.setdefault("gun", {})
        self.gun_spread = math.radians(g.get("spread_deg", 0.6))
        self.gun_range = g.get("range", 230.0)
        mech = cfg.get("mech") or {}
        self.radius = mech.get("radius", 2.5)
        self.body_h = mech.get("height", 9.0)
        self.walk = mech.get("walk_speed", 11.7)
        self.accel = mech.get("ground_accel", 58.5)
        self.turn_rate = mech.get("turn_rate", 4.0)
        self.rear_arc = math.radians(mech.get("front_arc_deg", 180.0)) / 2
        thz = cfg.get("match", {}).get("tick_hz", 20) or 20
        dev = cfg.get("match", {}).get("decide_every", 2) or 2
        self.tick_dt = 1.0 / thz            # a shot leaves on the first tick of the action
        self.dec_dt = dev / thz             # one decision = 0.1 s
        self.bullet_r = (cfg.get("projectile") or {}).get("gun_radius", 0.3) if isinstance(cfg.get("projectile"), dict) else 0.3
        # jinking beats a constant-velocity lead only if a full-accel swerve during the bullet flight
        # moves us off the aim point by more than our radius: 0.5*a*t^2 > R  =>  t > sqrt(2R/a)
        self.jink_min_d = self.gun_speed * math.sqrt(2 * (self.radius + self.bullet_r) / max(1.0, self.accel))
        self.jink_min_d = min(self.jink_min_d, 60.0)  # v3: AIMFIT shows reversals help from ~60 m
        zph = (cfg.get("zone") or {}).get("phases") or []
        # absolute start of the second-to-last hold: the HP race begins there
        tt, starts = 0.0, []
        for ph in zph:
            starts.append(tt)
            tt += ph.get("hold_s", 0) + ph.get("shrink_s", 0)
        self.endgame_t = starts[-2] if len(starts) >= 2 else 1e9
        # I4: absolute-time PARAMS rescaled to this config's zone timeline (identical on the stream config)
        sc_t = tt / PARAMS["ref_timeline_s"] if tt > 0 else 1.0
        hold0 = zph[0].get("hold_s", PARAMS["ref_first_hold_s"]) if zph else PARAMS["ref_first_hold_s"]
        sc_h = hold0 / PARAMS["ref_first_hold_s"]
        self.T = {k: PARAMS[k] * sc_t for k in ("no_fight_t", "final_center_t", "survive_t", "cluster_t")}
        self.T["loot_early_t"] = PARAMS["loot_early_t"] * sc_h
        self.arm_t = PARAMS["arm_hold_mult"] * hold0
        # I1: world memory of loot. pickups id -> (kind, (x, y, z), t_seen); crates / cubes id -> (pos, t)
        self.mem_pick: Dict[int, Tuple[Any, Tuple[float, float, float], float]] = {}
        self.mem_crate: Dict[int, Tuple[Tuple[float, float, float], float]] = {}
        self.mem_cube: Dict[int, Tuple[Tuple[float, float, float], float]] = {}
        self.mech_last: Dict[int, Tuple[float, float, float, float]] = {}  # id -> x, y, z, t
        self.corpse: Optional[Tuple[float, float, float, float]] = None
        self.econ_key = None
        self.econ_best = (1e9, 0.0)
        self.econ_black: Dict[Any, float] = {}
        self.sweep_until = -1.0
        self.sweep_last = -99.0
        self.mem_check_i = 0
        vis = cfg.get("vision") or {}
        self.vis_range = vis.get("range", 200.0)
        self.fov_half = math.radians(vis.get("fov_deg", 120.0)) / 2
        self.max_climb = PARAMS["max_climb_frac"] * mech.get("energy", 100.0) / max(1e-3, mech.get("jet_drain", 15.0)) * \
            (mech.get("max_rise_speed", 10.0) - mech.get("gravity", 22.0) * self.tick_dt)
        # I3: committed movement mode
        self.cmode: Optional[str] = None
        self.cmode_t = -99.0
        self.cmode_state = None
        self.prev_los_ids: set = set()
        self.hp_hist: List[Tuple[float, float]] = []
        self.last_dmg_anon_t = -99.0
        k_ie = PARAMS["inner_edge_phases"]
        self.inner_edge_t = starts[-k_ie] if len(starts) >= k_ie else 1e9
        # v4: recovery after a kill (position of the kill; cleared when healed and moved away)
        self.recover_from: Optional[Tuple[float, float]] = None
        self.hunter_c: Optional[Tuple[float, float, float]] = None  # x, y, t of last known hunter centroid
        seed = hello.get("seed")
        self.rng = __import__("random").Random(seed if seed is not None else 20261120)
        self.jink_sign = 1.0
        self.jink_next = 0.0
        self.dodge_until = -1.0
        self.dodge_dir = (0.0, 0.0)
        self.gate_info = ""
        self.world = None
        t0 = time.time()
        try:
            md = find_map_dir(hello)
            if md and worldmod is not None:
                mech = cfg.get("mech") or {}
                self.world = worldmod.World(md, mech.get("step_up", 1.2), mech.get("height", 9.0))
            mf.log(f"world loaded from {md} in {time.time() - t0:.2f}s")
        except Exception:
            mf.log("world load failed:\n" + traceback.format_exc())
            self.world = None
        # memory
        self.last_damage_t = -99.0
        self.last_hostile_t = -99.0
        self.dmg_bearing: Optional[float] = None
        self.dmg_by: Optional[float] = None
        self.attackers: Dict[int, float] = {}
        self.pseudo: List[Tuple[float, float, float, float]] = []  # x, y, weight, t
        self.planner = None
        self.plan_goal: Optional[Tuple[float, float]] = None
        self.plan_t = -99.0
        self.path: Optional[List[Tuple[float, float]]] = None
        self.path_i = 0
        self.cover: Optional[Tuple[float, float]] = None
        self.cover_t = -99.0
        self.cover_score = -1e9
        self.stuck_n = 0
        self.unstick_until = -1.0
        self.unstick_dir = 1.0
        self.prev_pos: Optional[List[float]] = None
        self.last_aim = [0.0, 0.0]
        self.scan_i = 0
        self.scan_t = 0.0
        self.taken_fail: Dict[int, float] = {}
        self.mode = "start"
        self.slow_ticks = 0
        self.tick_t0 = 0.0
        self.cover_budget_s = 0.005
        # v3: focus fire. The mech we damaged last and when; we finish it instead of letting it regen.
        self.focus_id: Optional[int] = None
        self.focus_t = -99.0
        # v3 FFA detector: practice house bots never damage each other, a free-for-all does. Evidence =
        # a visible mech losing >= 40 HP in one decision that we did not hit and no drone is near
        # (zone <= 26/decision, drone shot 25), or a death we
        # did not cause before the zone bites.
        self.ffa = False
        self.ffa_ev = 0
        self.enemy_hp: Dict[int, Tuple[float, float]] = {}
        self.prev_alive: Optional[int] = None
        self.our_hits: Dict[int, float] = {}
        self.our_kill_t = -99.0
        self.path_partial = False
        self.climb_until = -1.0  # wall-time cap for the cover search inside one decision

    # ------------------------------------------------------------------ main entry
    def act(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        t_start = time.perf_counter()
        self.tick_t0 = t_start
        try:
            a = self._act(obs, t_start)
        except Exception:
            mf.log("act error:\n" + traceback.format_exc())
            a = self._safe(obs)
        dt = (time.perf_counter() - t_start) * 1000
        if dt > 20:
            self.slow_ticks += 1
        return a

    def _safe(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            me = obs["self"]
            x, y = me["pos"][0], me["pos"][1]
            z = obs["zone"]
            gx, gy = z["next_center"]
            d = hyp(x, y, gx, gy)
            mv = [(gx - x) / d, (gy - y) / d] if d > 1 else [0.0, 0.0]
            return {"move": mv, "aim": list(self.last_aim), "boost": not me.get("in_zone", True)}
        except Exception:
            return {"aim": list(self.last_aim)}

    # ------------------------------------------------------------------ helpers
    def zone_radius_at(self, zone: Dict[str, Any], t_now: float, t_future: float) -> Tuple[float, float, float]:
        cx, cy = zone["center"]
        r = zone["radius"]
        nx, ny = zone["next_center"]
        nr = zone["next_radius"]
        s0, s1 = zone["shrink_start"], zone["shrink_end"]
        if t_future <= s0 or s1 <= t_now:
            return cx, cy, r
        start = max(t_now, s0)
        f = min(1.0, (t_future - start) / max(1e-3, s1 - start))
        return cx + (nx - cx) * f, cy + (ny - cy) * f, r + (nr - r) * f

    def zone_goal(self, obs: Dict[str, Any], x: float, y: float) -> Tuple[float, float, float]:
        """Point in the next circle closest to us (inset), and the inset radius."""
        z = obs["zone"]
        ncx, ncy = z["next_center"]
        nr = z["next_radius"]
        inset = max(0.0, nr - min(30.0, 0.35 * nr + 3.0))
        if obs.get("t", 0) >= min(self.endgame_t, self.T["final_center_t"]):
            inset = 0.0  # HP race: the circle centre stays inside longest during the last shrinks
        d = hyp(ncx, ncy, x, y)
        if d <= inset:
            return x, y, inset
        f = inset / d
        return ncx + (x - ncx) * f, ncy + (y - ncy) * f, inset

    def safe_point(self, obs: Dict[str, Any], px: float, py: float, t: float) -> float:
        """Penalty for standing at p in the near future (zone)."""
        z = obs["zone"]
        pen = 0.0
        cx, cy, r = self.zone_radius_at(z, t, t + 12.0)
        dd = hyp(cx, cy, px, py)
        if dd > r - 4:
            pen += 25.0 + (dd - r) * 0.5
        ncx, ncy = z["next_center"]
        if hyp(ncx, ncy, px, py) > z["next_radius"] - 5 and z["shrink_start"] - t < 25:
            pen += 8.0
        return pen

    # ------------------------------------------------------------------ the decision
    def _act(self, obs: Dict[str, Any], t0: float) -> Dict[str, Any]:
        me = obs["self"]
        t = obs["t"]
        x, y, z = me["pos"]
        vx, vy = me["vel"][0], me["vel"][1]
        hp, mhp = me["hp"], max(1.0, me["max_hp"])
        stats = me.get("stats") or {}
        eye_h = stats.get("eye_height", 8.0)
        muz_h = stats.get("muzzle_height", 7.0)
        act: Dict[str, Any] = {}
        W = self.world

        # ---- events
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
                    if e.get("by") is not None:
                        self.attackers[int(e["by"])] = t
                        self.dmg_by = e["by"]
                        if e["by"] < 100 and e.get("bearing") is not None:
                            b = e["bearing"]
                            self.pseudo.append((x + 80 * math.cos(b), y + 80 * math.sin(b), 1.5, t))
            elif et == "hit":
                tg = e.get("target")
                if isinstance(tg, int) and tg < 100:
                    self.focus_id, self.focus_t = tg, t
            elif et == "kill":
                if isinstance(e.get("target"), int):
                    self.attackers.pop(int(e["target"]), None)
                if e.get("target") == self.focus_id:
                    self.focus_id = None
                if isinstance(e.get("target"), int) and e["target"] < 100:  # mechs only, not drones
                    self.recover_from = (x, y)
                    ml = self.mech_last.get(int(e["target"]))
                    if ml is not None and t - ml[3] < 3.0:
                        self.corpse = (ml[0], ml[1], ml[2], t)
                if isinstance(e.get("target"), int):
                    self.mem_crate.pop(int(e["target"]), None)
            elif et == "take_failed":
                self.taken_fail[int(e.get("id", -1))] = t
                if e.get("reason") == "gone":
                    self.mem_pick.pop(int(e.get("id", -1)), None)
            elif et == "took":
                self.mem_pick.pop(int(e.get("id", -1)), None)
        self.update_memory(obs, me, x, y, z, eye_h, t)
        for s in obs.get("sounds") or []:
            if s.get("kind") in HOSTILE_SOUNDS and s.get("age", 0) < 1.0:
                dd = SOUND_DIST.get(s.get("dist"), 110.0)
                b = s["bearing"]
                self.pseudo.append((x + dd * math.cos(b), y + dd * math.sin(b), 0.6, t))
                if dd < 120:
                    self.last_hostile_t = max(self.last_hostile_t, t - 3.0)
        self.pseudo = [p for p in self.pseudo if t - p[3] < 6.0][-12:]
        self.detect_ffa(obs, t)
        # v4 card A: how many distinct hunters do we know of nearby (seen, or heard < 1 s ago)
        vis_m = [m for m in obs.get("mechs") or [] if m.get("kind") == "mech" and m.get("id") != me.get("id")]
        near_seen = [m for m in vis_m if hyp(x, y, m["pos"][0], m["pos"][1]) < PARAMS["detail_range"]]
        abort_seen = [m for m in vis_m if hyp(x, y, m["pos"][0], m["pos"][1]) < PARAMS["detail_abort_range"]]
        heard: List[float] = []
        for s in obs.get("sounds") or []:
            if s.get("kind") in HOSTILE_SOUNDS and s.get("age", 0) < 1.0 and \
                    SOUND_DIST.get(s.get("dist"), 110.0) < PARAMS["detail_abort_range"] and "bearing" in s:
                b = s["bearing"]
                # a sound on the bearing of a visible mech is that mech, not a second one
                if not any(abs(wrap(math.atan2(m["pos"][1] - y, m["pos"][0] - x) - b)) < 0.35 for m in vis_m):
                    if not any(abs(wrap(b - hb)) < 0.35 for hb in heard):
                        heard.append(b)
        n_hunters = max(len(near_seen), len(abort_seen) + len(heard))
        if vis_m:
            self.hunter_c = (sum(m["pos"][0] for m in vis_m) / len(vis_m),
                             sum(m["pos"][1] for m in vis_m) / len(vis_m), t)
        elif self.pseudo:
            pw = sum(p[2] for p in self.pseudo)
            self.hunter_c = (sum(p[0] * p[2] for p in self.pseudo) / pw, sum(p[1] * p[2] for p in self.pseudo) / pw, t)
        if self.recover_from is not None and hp >= PARAMS["recover_hp"] * mhp and \
                hyp(x, y, *self.recover_from) >= PARAMS["recover_move_m"]:
            self.recover_from = None
        recovering = self.recover_from is not None
        alive_n = obs.get("alive")
        survive = (t >= self.T["no_fight_t"]) or (isinstance(alive_n, int) and alive_n <= PARAMS["survive_alive"]
                                                    and t >= self.T["survive_t"])
        no_optional = survive or recovering or n_hunters > PARAMS["detail_max_hunters"]

        # ---- offer
        off = obs.get("offer")
        if off and off.get("choices"):
            ids = [c.get("id") for c in off["choices"]]
            best, bi = 999, 0
            for i, cid in enumerate(ids):
                r = UPGRADE_PRIORITY.index(cid) if cid in UPGRADE_PRIORITY else 50
                if r < best:
                    best, bi = r, i
            act["pick"] = bi

        # ---- threats
        enemies = [m for m in obs.get("mechs") or [] if m.get("kind") == "mech" and m.get("id") != me.get("id")]
        npcs = [m for m in obs.get("mechs") or [] if m.get("kind") == "npc"]
        for m in enemies:
            dm = hyp(x, y, m["pos"][0], m["pos"][1])
            if dm < 230:
                self.last_hostile_t = t
        enemies.sort(key=lambda m: hyp(x, y, m["pos"][0], m["pos"][1]))
        threats: List[Tuple[float, float, float, float]] = []  # x, y, z, weight
        for m in enemies[:4]:
            threats.append((m["pos"][0], m["pos"][1], m["pos"][2], 2.0))
        for n in npcs[:3]:
            if hyp(x, y, n["pos"][0], n["pos"][1]) < 90:
                threats.append((n["pos"][0], n["pos"][1], n["pos"][2], 0.7))
        for (px, py, wgt, _) in self.pseudo[-4:]:
            gz = W.ground_at(px, py) if W else z
            threats.append((px, py, gz, wgt))

        engaged = (t - self.last_damage_t) < 4.0
        recent_hostile = (t - self.last_hostile_t) < 12.0

        # ---- v2 engagement gate: who can shoot us, and which target we out-race
        weapons_now = me.get("weapons") or [None, None]
        my_kinds = [wp.get("kind") for wp in weapons_now if wp]
        my_mult = 1.0 + 0.04 * min(me.get("cubes", 0) or 0, 10)
        my_speed = math.hypot(vx, vy)
        shooters = []  # (mech, dist) with line of sight to our body: they can hurt us now
        for m in enemies[:6]:
            mx, my_, mz = m["pos"]
            dm = math.dist((x, y, z), (mx, my_, mz))
            if dm > 285:
                continue
            if W and W.sight_blocked((mx, my_, mz + eye_h), (x, y, z + 4.5)) and \
                    W.sight_blocked((mx, my_, mz + eye_h), (x, y, z + 8.5)):
                continue
            shooters.append((m, dm))
        their_dps = 0.0
        for (m, dm) in shooters:
            mult = 1.0 + 0.04 * min(m.get("cubes", 0) or 0, 10)
            kinds = m.get("weapons") or ["gun"]
            their_dps += mult * PARAMS["enemy_aim_mult"] * sum(
                self.weapon_dps(k if isinstance(k, str) else (k or {}).get("kind"), dm, my_speed) for k in kinds)
        ttk_them = hp / their_dps if their_dps > 1e-6 else 1e9
        k_gate = PARAMS["ffa_engage_k" if self.ffa else "engage_k"] * (PARAMS["endgame_k_mult"] if t >= self.endgame_t else 1.0)

        # ---- target selection (things in our line of sight)
        target = None
        tscore = -1e9
        fight_ok = False
        t_finish = False
        for m in enemies[:5] + npcs[:3]:
            mx, my_, mz = m["pos"]
            dm = math.dist((x, y, z), (mx, my_, mz))
            if dm > 285:
                continue
            if W and W.sight_blocked((x, y, z + muz_h), (mx, my_, mz + 4.0)):
                continue
            is_mech = m.get("kind") == "mech"
            attacker = (t - self.attackers.get(int(m["id"]), -99)) < 5.0
            tv = m.get("vel") or [0, 0, 0]
            our = my_mult * sum(self.weapon_dps(k, dm, math.hypot(tv[0], tv[1])) for k in my_kinds)
            m_hp = m.get("hp", 350.0 if not is_mech else 1400.0)
            m_frac = m_hp / max(1.0, m.get("max_hp", 350.0 if not is_mech else 1400.0))
            ttk_us = m_hp / our if our > 1e-6 else 1e9
            ok = ttk_us < k_gate * ttk_them
            # v3: a finishing kill is taken whenever we still out-race the shooters (k = 1);
            # below retreat_hp we only take finishing kills and otherwise go regen
            finishing = is_mech and m_frac <= PARAMS["finish_frac"] and ttk_us < ttk_them
            if hp < PARAMS["retreat_hp"] * mhp and not finishing:
                ok = False
            ok = ok or finishing
            if is_mech and not self.ffa:
                # v4 defeat in detail: optional fights only 1v1 against a not-healthier hunter;
                # finishing kills still need us to be in a 1v1
                if finishing:
                    ok = ok and n_hunters <= PARAMS["detail_max_hunters"] and not (survive and not attacker)
                else:
                    ok = ok and (not no_optional) and m_hp <= PARAMS["detail_hp_ratio"] * hp
                if PARAMS["pacifist"]:
                    ok = False
            focus = is_mech and int(m["id"]) == self.focus_id and (t - self.focus_t) < 8.0
            if not is_mech:
                # drones: when they shoot us, or (v3) to farm cubes while no mech is around
                want = attacker or (not enemies and not recent_hostile and hp >= PARAMS["farm_min_hp"] * mhp
                                    and t < self.endgame_t)
                ok = ok or want
            else:
                want = ok or attacker
                if self.ffa and not (finishing or (attacker and ok)):
                    # FFA: survival is the score. Let others trade; shoot only to finish or defend
                    want, ok = attacker, False
            # v3: isolated hunters first (fewer friends within 40 m = less return fire while we kill it)
            friends = sum(1 for o in enemies if o is not m and hyp(o["pos"][0], o["pos"][1], mx, my_) < 40)
            sc = -ttk_us + (5.0 if attacker else 0.0) + (3.0 if ok else 0.0) + (1.0 if is_mech else -2.0) \
                + (4.0 if focus else 0.0) + (3.0 if finishing else 0.0) - 1.5 * friends
            if want and sc > tscore:
                tscore, target, fight_ok, t_finish = sc, m, ok, finishing
        if not self.ffa and t >= self.T["cluster_t"] and "lightning" in my_kinds:
            clus = [m for m in enemies if hyp(x, y, m["pos"][0], m["pos"][1]) < self.light_range]
            if len(clus) >= PARAMS["cluster_n"]:
                target, fight_ok = clus[0], True  # packed final circle: chain lightning hits several
        self.gate_info = f"ttk_them {min(ttk_them, 999):.0f} k {k_gate:.2f} sh {len(shooters)}"

        # ---- movement goal
        zgx, zgy, zinset = self.zone_goal(obs, x, y)
        zdist = hyp(x, y, zgx, zgy)
        zone = obs["zone"]
        cx, cy, cr = zone["center"][0], zone["center"][1], zone["radius"]
        out_now = not me.get("in_zone", True) or hyp(cx, cy, x, y) > cr
        # v2: time the rotation on the remaining *path* length, not the straight line, and against
        # the moment the shrinking edge reaches our goal (the goal is inset from the next edge)
        plen = zdist * PARAMS["detour"]
        if self.path and self.plan_goal and hyp(self.plan_goal[0], self.plan_goal[1], zgx, zgy) < 8:
            pts = self.path
            rem = hyp(x, y, *pts[min(self.path_i, len(pts) - 1)])
            for q in range(self.path_i, len(pts) - 1):
                rem += hyp(pts[q][0], pts[q][1], pts[q + 1][0], pts[q + 1][1])
            plen = max(zdist, rem)
        # when does the moving edge pass the point where we stand?  our margin vs that deadline:
        edge_t = self.edge_time(zone, x, y, t)
        time_left = max(1.0, min(zone["shrink_end"], edge_t) - t - PARAMS["zone_slack_s"])
        need_speed = plen / time_left
        silent = 0.42 * self.walk  # < 5 m/s: no step sounds
        urgent = out_now or need_speed > 0.75 * silent or (zone["shrink_start"] - t < 15 and zdist > 5)

        speed = PARAMS["silent_move"]  # silent walk
        goal: Optional[Tuple[float, float]] = None
        boost = False
        mode = "idle"

        elapsed = (time.perf_counter() - t0) * 1000
        # v2: a mech fight that passes the gate is taken (hold ground, jink); everything else hides
        fighting = target is not None and fight_ok and target.get("kind") == "mech"
        # v3: chase the focus target after it breaks LOS (the 5 s memory gives its true position),
        # so it can't regen; only when we are healthier than it and nobody else is shooting us
        chase = None
        if not fighting and not self.ffa and self.focus_id is not None and (t - self.focus_t) < 6.0 and not shooters \
                and hp >= PARAMS["chase_min_hp"] * mhp and t < self.endgame_t and not no_optional:
            for m in enemies:
                if int(m["id"]) == self.focus_id:
                    fr = m.get("hp", 1400.0) / max(1.0, m.get("max_hp", 1400.0))
                    if fr < hp / mhp and hyp(x, y, m["pos"][0], m["pos"][1]) < PARAMS["chase_range"]:
                        chase = m
                    break
        hide_needed = (not fighting) and (chase is None) and (engaged or (enemies and hyp(x, y, enemies[0]["pos"][0], enemies[0]["pos"][1]) < 200)
                                          or (hp < mhp * 0.98 and recent_hostile))
        if W and threats and hide_needed and elapsed < 6:
            if t - self.cover_t > 0.5 or self.cover is None:
                self.choose_cover(obs, x, y, z, threats, t)
        # v5: a second weapon (laser/lightning) is the biggest DPS lever; loot whenever no gunner has
        # line of sight and we are not under fire (not only after 12 s of total quiet)
        loot_ok = (not shooters) and (not engaged) and hp >= 0.5 * mhp
        # I1: economy goals come from the loot memory, whatever the mode branch, whenever nobody has
        # line of sight to us and we are not under fire
        econ = None
        # under fire = damage in the last 4 s from a mech that is still alive (a kill ends that fight)
        under_fire = (t - self.last_dmg_anon_t) < 4.0 or any(t - ta < 4.0 for ta in self.attackers.values())
        econ_hp = hp >= PARAMS["econ_min_hp"] * mhp or (self.corpse is not None and hp >= PARAMS["retreat_hp"] * mhp)
        if not fighting and chase is None and not out_now and econ_hp and t < self.T["final_center_t"]:
            econ = self.econ_goal(obs, me, x, y, z, t, act, urgent and zdist > 8)
            # with shooters on us, take the trip only when they need several times longer to kill us
            # than the trip takes (a far gunner landing few hits)
            if econ is not None and (shooters or under_fire):
                trip = hyp(x, y, *econ[0]) / max(1.0, self.walk) + 2.0
                if ttk_them < PARAMS["econ_ttk_mult"] * trip:
                    econ = None
        if out_now or (urgent and zdist > 8):
            goal = (zgx, zgy)
            speed = 1.0
            mode = "zone"
            if out_now:
                boost = me.get("energy", 0) > 20
            if hide_needed and self.cover is not None and self.safe_point(obs, *self.cover, t) < 1 and not out_now:
                goal = self.cover
                mode = "zone-cover"
        elif fighting:
            goal = None  # hold position; lateral jinks below make us hard to lead
            mode = "fight"
            speed = 1.0
            # I1: a better weapon close by is worth walking to while we keep shooting (fire control is
            # independent of movement): gun -> gun+laser is x2.2 sustained DPS
            if not out_now and not urgent:
                fa = self.econ_goal(obs, me, x, y, z, t, act, False, wmax=PARAMS["fight_arm_range"], weapons_only=True)
                if fa is not None:
                    goal, mode = fa[0], "fight-arm"
            # with lightning ready, close to ~0.7 x its range (replay: lightning hits p50 31 m of 45)
            if "lightning" in my_kinds and me.get("energy", 0) > 30:
                tx_, ty_ = target["pos"][0], target["pos"][1]
                dtg = hyp(x, y, tx_, ty_)
                if dtg > 0.7 * self.light_range:
                    f_ = (dtg - 0.6 * self.light_range) / dtg
                    goal = (x + (tx_ - x) * f_, y + (ty_ - y) * f_)
                    mode = "fight-close"
        elif chase is not None:
            goal = (chase["pos"][0], chase["pos"][1])
            mode = "chase"
            speed = 1.0
        elif econ is not None:
            goal, mode = econ
            speed = 1.0 if (enemies or t < self.arm_t or mode == "corpse") else PARAMS["silent_move"]
        elif hide_needed and self.cover is not None:
            goal = self.cover
            mode = "hide"
            speed = 1.0 if (engaged or (enemies and hyp(x, y, enemies[0]["pos"][0], enemies[0]["pos"][1]) < 90)) else PARAMS["silent_move"]
            if engaged and hp < mhp * 0.5 and me.get("energy", 0) > 40 and hyp(x, y, *goal) > 10:
                boost = True
        else:
            # safe: loot if close, otherwise go/stay in a hidden spot in the zone
            lg = None
            fg = None
            if lg is None and not recent_hostile and hp >= PARAMS["farm_min_hp"] * mhp and t < self.endgame_t \
                    and need_speed < 0.5 * silent:
                fg = self.farm_seek(obs, x, y, z)
            if lg is not None:
                goal = lg
                mode = "loot"
                speed = PARAMS["silent_move"]
            elif fg is not None:
                goal = fg
                mode = "farm-seek"
                speed = PARAMS["silent_move"]
            elif (not self.ffa and self.hunter_c is not None and t - self.hunter_c[2] < 30.0
                  and self.inner_edge_t <= t < self.T["final_center_t"] and not urgent
                  and hyp(self.hunter_c[0], self.hunter_c[1], *zone["next_center"]) > zone["next_radius"]):
                # v4 card C: stand inside the next circle on the hunters' side so their approach runs
                # through the zone edge (they eat zone damage, we stay in and regen)
                ncx, ncy = zone["next_center"]
                hb = math.atan2(self.hunter_c[1] - ncy, self.hunter_c[0] - ncx)
                rr = PARAMS["inner_edge_frac"] * zone["next_radius"]
                goal = (ncx + rr * math.cos(hb), ncy + rr * math.sin(hb))
                mode = "inner-edge"
                speed = PARAMS["silent_move"] if need_speed < 0.8 * silent else 1.0
            elif zdist > (PARAMS["camp_stay_m"] if self.cmode == "camp" else 3):
                # I3: spatial hysteresis, a camp spot near the zone goal is kept until it drifts camp_stay_m away
                goal = (zgx, zgy)
                mode = "travel"
                speed = PARAMS["silent_move"] if need_speed < 0.8 * silent else 1.0
            else:
                # camp: hidden from the likely direction of others (zone centre)
                if W and (self.cover is None or t - self.cover_t > 4.0) and elapsed < 6:
                    ncx, ncy = zone["next_center"]
                    b = math.atan2(ncy - y, ncx - x)
                    pseudo = [(x + 120 * math.cos(b + k), y + 120 * math.sin(b + k), z, 0.5) for k in (-0.6, 0.0, 0.6)]
                    self.choose_cover(obs, x, y, z, pseudo + threats, t, radius=24.0)
                if self.cover is not None and self.safe_point(obs, *self.cover, t) < 1:
                    goal = self.cover
                    mode = "camp"
                    speed = PARAMS["silent_move"]

        # ---- I3: mode commitment. A new movement mode replaces the committed one only after
        # mode_commit_s, or at once on a hard trigger (damage spike, a new mech with line of sight,
        # low HP, zone).
        self.hp_hist.append((t, hp))
        self.hp_hist = [h for h in self.hp_hist if t - h[0] <= 1.0]
        spike = (self.hp_hist[0][1] - hp) > PARAMS["dmg_spike_frac"] * mhp
        los_ids = {int(m["id"]) for (m, _) in shooters}
        if target is not None and target.get("kind") == "mech":
            los_ids.add(int(target["id"]))
        new_los = bool(los_ids - self.prev_los_ids)
        self.prev_los_ids = los_ids
        hard = out_now or mode == "zone" or spike or new_los or hp < PARAMS["retreat_hp"] * mhp
        if mode != self.cmode:
            if (not hard and self.cmode is not None and self.cmode_state is not None
                    and t - self.cmode_t < PARAMS["mode_commit_s"]):
                mode, goal, speed, boost = self.cmode_state
            else:
                self.cmode, self.cmode_t = mode, t
        self.cmode_state = (mode, goal, speed, boost)

        mv = [0.0, 0.0]
        gdir = None  # v5: unit direction toward the movement goal (None = holding position)
        if goal is not None:
            mv = self.steer(x, y, goal, t, me)
            mvn = math.hypot(*mv)
            if mvn > 0:
                gdir = (mv[0] / mvn, mv[1] / mvn)
            dgoal = hyp(x, y, goal[0], goal[1])
            if dgoal < 2.0:
                mv = [0.0, 0.0]
            elif mvn > 0:
                sp = speed if dgoal > 4 else min(speed, 0.4)
                mv = [mv[0] / mvn * sp, mv[1] / mvn * sp]

        # ---- v2 dodges: jink against long-range gun fire, step out of predicted mortar splash
        jink = self.jink_vector(t, x, y, shooters)
        if jink is not None and not out_now:
            if gdir is not None:
                # v5: with a goal, drop the jink component that points back against it; otherwise the
                # alternating jink cancels every walk to cover (full jink only while holding position)
                dp = jink[0] * gdir[0] + jink[1] * gdir[1]
                if dp < 0:
                    jink = (jink[0] - dp * gdir[0], jink[1] - dp * gdir[1])
            mv = [mv[0] * 0.6 + jink[0], mv[1] * 0.6 + jink[1]]
            n = math.hypot(*mv) or 1.0
            mv = [mv[0] / n, mv[1] / n]
            mode += "+jink"
        dodge = self.mortar_dodge(obs, x, y, z, vx, vy, t)
        if dodge is not None:
            mv = list(dodge)
            boost = me.get("energy", 0) > 10 and me.get("grounded", True)
            mode = "dodge"

        # ---- stuck detection / unstick
        jump = False
        hs = math.hypot(vx, vy)
        cmd = math.hypot(*mv)
        # v2: also count "no horizontal progress over the last 1 s" while commanded to move (catches
        # bouncing in pits / against eaves, where v1's grounded-speed test never fires). Walking at
        # the silent pace covers >= 4.7 m in 1 s, so < 1.5 m means we are blocked.
        hist = getattr(self, "pos_hist", None)
        if hist is None:
            hist = self.pos_hist = []
        hist.append((x, y, cmd))
        del hist[:-11]
        no_progress = len(hist) == 11 and all(h[2] > 0.3 for h in hist) and             hyp(hist[0][0], hist[0][1], x, y) < 1.5
        if (cmd > 0.3 and me.get("grounded", True) and hs < 1.2) or no_progress:
            self.stuck_n += 1
        else:
            self.stuck_n = max(0, self.stuck_n - 1)
        if self.stuck_n >= 8 and t > self.unstick_until + 1.0:
            self.unstick_until = t + 1.2
            self.unstick_dir = -self.unstick_dir
            self.stuck_n = 0
            self.planner = None
            self.path = None
            self.plan_t = -99
        if t < self.climb_until and cmd > 0:
            if me.get("grounded", True):
                jump = True
            boost = me.get("energy", 0) > 10
        elif t < self.unstick_until and cmd > 0:
            if me.get("grounded", True):
                jump = True
            boost = me.get("energy", 0) > 15
            # sidestep a little while climbing
            px, py = -mv[1], mv[0]
            mv = [mv[0] + 0.5 * self.unstick_dir * px, mv[1] + 0.5 * self.unstick_dir * py]
            n = math.hypot(*mv) or 1.0
            mv = [mv[0] / n, mv[1] / n]

        # ---- aim and fire
        fire = [False, False]
        weapons = me.get("weapons") or [None, None]
        aim = None
        if target is None and not recent_hostile and hp >= PARAMS["farm_min_hp"] * mhp and t < self.endgame_t:
            target = self.farm_target(obs, x, y, z, muz_h)
            if target is not None:
                mode += "+farm"  # I3: the label is the movement mode; fire targets are a suffix
        if target is None and chase is not None:
            aim, _ = self.fire_control(me, chase, weapons, x, y, z, muz_h)  # pre-aim, no blind fire
        elif target is not None:
            aim, fire = self.fire_control(me, target, weapons, x, y, z, muz_h)
            if PARAMS["pacifist"] and target.get("kind") == "mech":
                fire = [False, False]
            if False:
                # v5: retreating to cover: keep aiming, but returning fire restarts our own regen
                # clock; only a laser already charging may finish its shot
                fire = [bool(f and wp and wp.get("kind") == "laser" and (wp.get("charge") or 0) > 0)
                        for f, wp in zip(fire, list(weapons) + [None, None])]
            if mode.split("+")[0] in ("travel", "loot", "camp", "idle", "arm", "cubes", "corpse"):
                mode += "+shoot"
        if aim is None:
            # I1: a 360 deg torso sweep at spawn (and while unarmed with nothing remembered) fills the
            # loot memory: the far vision cone is only 120 deg
            w1 = weapons[1] if len(weapons) > 1 else None
            if t < self.arm_t and (w1 is None or w1.get("kind") == "mortar") and mode.split("+")[0] != "arm" \
                    and t - self.sweep_last > 10.0 and not shooters and not engaged:
                self.sweep_last, self.sweep_until = t, t + 2.0
            if t < self.sweep_until and not shooters and not engaged:
                aim = [wrap((me.get("aim") or self.last_aim)[0] + 1.2), 0.0]
            else:
                aim = self.scan_aim(obs, x, y, t, mv, threats)
        else:
            # laser charging slows us; fine. keep aim
            pass
        # reload when nothing to shoot
        g0 = weapons[0] if weapons else None
        if g0 and g0.get("kind") == "gun" and target is None and g0.get("ammo", 12) < 6 and not g0.get("reload") \
                and (not recent_hostile or engaged or g0.get("ammo", 12) == 0):
            act["reload"] = True

        self.last_aim = aim
        mn = math.hypot(*mv)
        if mn > 0.998:
            mv = [mv[0] * 0.998 / mn, mv[1] * 0.998 / mn]
        act.update(move=[round(mv[0], 3), round(mv[1], 3)], aim=[round(aim[0], 4), round(aim[1], 4)],
                   fire=fire, boost=bool(boost), jump=bool(jump))
        self.mode = mode
        mf.draw.label(f"{'F' if self.ffa else 'S'} {mode} hp{hp:.0f} e{len(enemies)} {self.gate_info}")
        return act

    # ------------------------------------------------------------------ v2 models
    def gun_hit_p(self, d: float, miss_h: float, miss_v: float, tt: float, spread: Optional[float] = None,
                  rad: Optional[float] = None, height: Optional[float] = None) -> float:
        """Probability one projectile hits a mech body: Gaussian spread (sigma = spread_deg) plus the
        displacement of a randomly accelerating target over the flight time, vs the body cross
        section (radius + bullet radius wide, half the body height tall)."""
        sp = self.gun_spread if spread is None else spread
        sig = math.hypot(d * math.tan(sp), 0.5 * PARAMS["target_accel_sigma"] * tt * tt)
        rad = self.radius if rad is None else rad
        height = self.body_h if height is None else height
        return p_within(miss_h, sig, rad + self.bullet_r) * p_within(miss_v, sig, height / 2)

    def weapon_dps(self, kind: Optional[str], d: float, tgt_speed: float) -> float:
        """Expected sustained damage per second of one weapon at range d (config stats, perfect aim
        apart from spread and target motion). Used by the engagement gate both ways."""
        if not kind:
            return 0.0
        w = self.wcfg.get(kind) or {}
        if kind == "gun":
            if d > w.get("range", 230.0):
                return 0.0
            mag, cd, rl = w.get("mag", 12), w.get("cooldown", 0.24), w.get("reload", 2.4)
            tt = d / w.get("speed", 252.0) + self.tick_dt
            return w.get("damage", 45) * mag / (mag * cd + rl) * self.gun_hit_p(d, 0.0, 0.0, tt)
        if kind == "laser":
            if d > w.get("range", 280.0):
                return 0.0
            # hitscan: only the reaction delay lets the target move; one shot per charge+cooldown
            p = self.gun_hit_p(d, 0.0, 0.0, self.dec_dt + self.tick_dt, spread=0.0)
            return w.get("damage", 315) / (w.get("charge", 0.75) + w.get("cooldown", 1.65)) * p
        if kind == "lightning":
            # auto-targets in the cone; 3 energy per 0.25 s shot vs 18/s regen -> ~100/12 s bursts
            return w.get("damage", 60) / w.get("cooldown", 0.25) if d <= w.get("range", 45.0) else 0.0
        if kind == "mortar":
            if d > 230 or d < 15:
                return 0.0
            # a 72 m/s shell flies d/50 s or more: a moving target usually only takes the splash edge
            tt = d / max(1.0, w.get("speed", 72.0) * 0.7)
            p = 1.0 if tgt_speed * tt < w.get("splash_radius", 7.0) else 0.4
            return (w.get("splash", 160) * p) / w.get("cooldown", 2.6)
        return 0.0

    def edge_time(self, zone: Dict[str, Any], x: float, y: float, t: float) -> float:
        """Time at which the shrinking zone edge passes the point (x, y); 1e9 if it never does
        during this shrink (point inside the next circle)."""
        ncx, ncy = zone["next_center"]
        if hyp(ncx, ncy, x, y) <= zone["next_radius"]:
            return 1e9
        s0, s1 = zone["shrink_start"], zone["shrink_end"]
        if s1 <= t:
            return t
        tau = max(t, s0)
        while tau <= s1:
            cx, cy, r = self.zone_radius_at(zone, t, tau)
            if hyp(cx, cy, x, y) > r:
                return tau
            tau += 1.0
        return s1

    def jink_vector(self, t: float, x: float, y: float, shooters) -> Optional[Tuple[float, float]]:
        """Lateral swerve against the nearest gun shooter that is far enough for a swerve to beat a
        constant-velocity lead (d > jink_min_d). Direction flips at random intervals of about one
        bullet flight time, so the shooter's lead (our velocity at fire time) is stale on arrival."""
        best = None
        for (m, dm) in shooters:
            kinds = m.get("weapons") or ["gun"]
            if "gun" not in kinds or dm < self.jink_min_d or dm > self.gun_range:
                continue
            if best is None or dm < best[1]:
                best = (m, dm)
        if best is None:
            return None
        m, dm = best
        flight = dm / self.gun_speed
        if t >= self.jink_next:
            # v3 (AIMFIT): house bots lead ~95% of our velocity, so reverse at random 0.4-0.8 s
            # intervals (37-55% fewer hits at 90-120 m in the 1-D model)
            self.jink_sign = -self.jink_sign
            self.jink_next = t + self.rng.uniform(0.4, 0.8)
        b = math.atan2(m["pos"][1] - y, m["pos"][0] - x)
        px, py = -math.sin(b) * self.jink_sign, math.cos(b) * self.jink_sign
        W = self.world
        if W is not None and not W.line_clear(x, y, x + 6 * px, y + 6 * py):
            self.jink_sign = -self.jink_sign
            px, py = -px, -py
        return (px, py)

    def mortar_dodge(self, obs, x, y, z, vx, vy, t) -> Optional[Tuple[float, float]]:
        """Predict each visible shell's impact (ballistic, gravity from config) and, if our coasting
        position at impact lies inside splash radius + our radius + margin, run directly away from
        the impact point (or sideways to the shell track if it would land on us)."""
        if t < self.dodge_until:
            return self.dodge_dir
        mw = self.wcfg.get("mortar") or {}
        g = mw.get("gravity", self.mortar_g)
        danger_r = mw.get("splash_radius", 7.0) + self.radius + PARAMS["mortar_margin"]
        best = None
        for p in obs.get("projectiles") or []:
            if p.get("kind") != "mortar":
                continue
            px, py, pz = p["pos"]
            pvx, pvy, pvz = p["vel"]
            gz = z
            disc = pvz * pvz + 2 * g * (pz - gz)
            if disc < 0:
                continue
            ti = (pvz + math.sqrt(disc)) / g
            if ti <= 0 or ti > 6:
                continue
            ix, iy = px + pvx * ti, py + pvy * ti
            dd = hyp(ix, iy, x + vx * ti, y + vy * ti)
            if dd < danger_r and (best is None or ti < best[0]):
                best = (ti, ix, iy, pvx, pvy)
        if best is None:
            return None
        ti, ix, iy, pvx, pvy = best
        dx, dy = x - ix, y - iy
        n = math.hypot(dx, dy)
        if n < 1.0:
            n = math.hypot(pvx, pvy) or 1.0
            dx, dy = -pvy / n, pvx / n
            n = 1.0
        base = math.atan2(dy, dx)
        W = self.world
        for off in (0.0, 0.6, -0.6, 1.2, -1.2, 1.8, -1.8):
            a = base + off
            if W is None or W.line_clear(x, y, x + 8 * math.cos(a), y + 8 * math.sin(a)):
                self.dodge_dir = (math.cos(a), math.sin(a))
                self.dodge_until = t + min(ti, 1.5)
                return self.dodge_dir
        return None

    def farm_target(self, obs, x, y, z, muz_h):
        """Nearest drone or crate within farm range in line of sight (cubes -> HP pool, upgrades).
        Drones: 350 HP, 25 dmg/s back; crates: 300 HP, 1 cube + 50% weapon, no return fire."""
        W = self.world
        best, bd = None, PARAMS["farm_range"]
        for c in (obs.get("crates") or []):
            d = hyp(x, y, c["pos"][0], c["pos"][1])
            if d < bd and abs(c["pos"][2] - z) < 6:
                if W and W.sight_blocked((x, y, z + muz_h), (c["pos"][0], c["pos"][1], c["pos"][2] + 1.2)):
                    continue
                best, bd = dict(c, kind="crate", vel=[0, 0, 0], id=c.get("id", -1)), d
        for m in obs.get("mechs") or []:
            if m.get("kind") != "npc":
                continue
            d = hyp(x, y, m["pos"][0], m["pos"][1])
            if d < bd:
                if W and W.sight_blocked((x, y, z + muz_h), (m["pos"][0], m["pos"][1], m["pos"][2] + 1.75)):
                    continue
                best, bd = m, d
        return best

    def detect_ffa(self, obs, t: float) -> None:
        if self.ffa:
            return
        me_id = (obs.get("self") or {}).get("id", self.me_id)
        for e in obs.get("events") or []:
            if e.get("type") == "hit" and isinstance(e.get("target"), int):
                self.our_hits[e["target"]] = t
            elif e.get("type") == "kill":
                self.our_kill_t = t
        mechs = [m for m in obs.get("mechs") or [] if m.get("kind") == "mech" and m.get("id") != me_id]
        npcs = [m for m in obs.get("mechs") or [] if m.get("kind") == "npc"]
        for m in mechs:
            mid = int(m["id"])
            hpm = m.get("hp")
            if hpm is None:
                continue
            prev = self.enemy_hp.get(mid)
            self.enemy_hp[mid] = (hpm, t)
            if prev is None or t - prev[1] > 0.25 or t - self.our_hits.get(mid, -99.0) < 0.5:
                continue
            if prev[0] - hpm >= self.ffa_drop and not any(hyp(n["pos"][0], n["pos"][1], m["pos"][0], m["pos"][1]) < 100 for n in npcs):
                self.ffa_ev += 1 if t > PARAMS["ffa_min_t"] else 0
                mf.log(f"ffa evidence: mech {mid} lost {prev[0] - hpm:.0f} HP at t={t:.1f} (not us)")
        alive = obs.get("alive")
        if isinstance(alive, int):
            zone = obs.get("zone") or {}
            if self.prev_alive is not None and alive < self.prev_alive and t - self.our_kill_t > 0.5 and                     t < (zone.get("shrink_start", 60.0) if zone.get("radius", 0) >= 500 else 0.0):
                self.ffa_ev += 1 if t > PARAMS["ffa_min_t"] else 0
                mf.log(f"ffa evidence: a mech died at t={t:.1f} (not our kill, no zone yet)")
            self.prev_alive = alive
        if self.ffa_ev >= PARAMS["ffa_ev_needed"]:
            self.ffa = True
            mf.log(f"FFA mode detected at t={t:.1f}")

    def farm_seek(self, obs, x, y, z) -> Optional[Tuple[float, float]]:
        """v3: walk toward the nearest seen drone (2 cubes) or crate (1 cube) to farm it: stop at
        ~30 m from a drone (inside our accurate gun range, its 25-dmg shots are weak) or ~10 m from
        a crate. Cubes = +4% HP and damage each, and upgrade offers."""
        best, bd = None, PARAMS["farm_seek_range"]
        t = obs["t"]
        for m in obs.get("mechs") or []:
            if m.get("kind") == "npc":
                px, py, pz = m["pos"]
                d = hyp(x, y, px, py)
                if d < bd and abs(pz - z) < 5 and self.safe_point(obs, px, py, t) < 1:
                    best, bd = (px, py, 28.0), d
        for c in obs.get("crates") or []:
            px, py, pz = c["pos"]
            d = hyp(x, y, px, py)
            if d < bd and abs(pz - z) < 4 and self.safe_point(obs, px, py, t) < 1:
                best, bd = (px, py, 10.0), d
        if best is None:
            return None
        px, py, stand = best
        if bd <= stand:
            return None
        f = (bd - stand) / bd
        return (x + (px - x) * f, y + (py - y) * f)

    # ------------------------------------------------------------------ I1 world memory + economy
    def update_memory(self, obs, me, x, y, z, eye_h, t) -> None:
        """Pickups, crates and cubes are listed only while visible: remember them until we see the
        spot empty (or a took / take_failed:gone event). Mechs: last seen position (corpse looting)."""
        for p in obs.get("pickups") or []:
            try:
                self.mem_pick[int(p["id"])] = (p.get("kind"), tuple(p["pos"]), t)
            except Exception:
                pass
        for c in obs.get("crates") or []:
            try:
                self.mem_crate[int(c["id"])] = (tuple(c["pos"]), t)
            except Exception:
                pass
        for c in obs.get("cubes") or []:
            try:
                self.mem_cube[int(c["id"])] = (tuple(c["pos"]), t)
            except Exception:
                pass
        for m in obs.get("mechs") or []:
            if m.get("kind") == "mech" and m.get("id") != me.get("id"):
                self.mech_last[int(m["id"])] = (m["pos"][0], m["pos"][1], m["pos"][2], t)
        # expiry: a remembered item inside our current view with a clear sight line that is not listed
        W = self.world
        yaw = (me.get("aim") or self.last_aim or [0.0])[0]
        cand = []
        for store, item_h in ((self.mem_pick, 0.5), (self.mem_crate, 1.2), (self.mem_cube, 0.5)):
            for k, v in store.items():
                pos, ts = (v[1], v[2]) if store is self.mem_pick else (v[0], v[1])
                if ts >= t:
                    continue
                d = hyp(x, y, pos[0], pos[1])
                if d <= 0.85 * self.near_range or (
                        d <= 0.9 * self.vis_range and abs(wrap(math.atan2(pos[1] - y, pos[0] - x) - yaw)) < self.fov_half - 0.1):
                    cand.append((d, store, k, pos, item_h))
        cand.sort(key=lambda c: c[0])
        for d, store, k, pos, item_h in cand[:8]:  # cap the sight checks per decision
            if d > 6.0 and W is not None and W.sight_blocked((x, y, z + eye_h), (pos[0], pos[1], pos[2] + item_h)):
                continue
            store.pop(k, None)
        if self.corpse is not None and (t - self.corpse[3] > PARAMS["corpse_s"] or hyp(x, y, self.corpse[0], self.corpse[1]) < 5.0):
            self.corpse = None

    def known_mechs(self, t: float, me_id) -> List[Tuple[float, float]]:
        return [(v[0], v[1]) for k, v in self.mech_last.items() if t - v[3] < 10.0 and k != me_id]

    def econ_goal(self, obs, me, x, y, z, t, act, urgent: bool, wmax: Optional[float] = None,
                  weapons_only: bool = False) -> Optional[Tuple[Tuple[float, float], str]]:
        """I1: the best remembered economy goal (second weapon, cubes, the last kill's drop), or None.
        Also issues `take` when a better weapon is within reach."""
        W = self.world
        weapons = me.get("weapons") or [None, None]
        held = [w.get("kind") for w in weapons if w]
        slot1 = weapons[1] if len(weapons) > 1 else None
        s1k = slot1.get("kind") if slot1 else None
        want_w = slot1 is None or s1k == "mortar"
        known = self.known_mechs(t, me.get("id")) + [(p[0], p[1]) for p in self.pseudo if t - p[3] < 3.0]
        energy = me.get("energy", 0.0) or 0.0
        best, bc, label = None, 1e9, None
        wrange = PARAMS["arm_range"] if t < self.arm_t else PARAMS["arm_late_range"]
        if wmax is not None:
            wrange = wmax
        for pid, (kind, pos, ts) in list(self.mem_pick.items()):
            if kind in held or kind == "gun" or kind is None:
                continue
            if WEAPON_RANK.get(kind, 0) <= WEAPON_RANK.get(s1k, -1):
                continue
            if t - self.taken_fail.get(pid, -99) < 3.0 or self.econ_black.get(("p", pid), -99) > t:
                continue
            px, py, pz = pos
            d = hyp(x, y, px, py)
            if d < self.reach - 0.3 and abs(pz - z) < 4:
                if slot1 is not None and slot1.get("kind") == "laser" and slot1.get("charge"):
                    continue
                act["take"] = pid
                if slot1 is not None:
                    act["drop"] = 1
                return None
            if not want_w or d > wrange:
                continue
            roof = W is not None and pz - W.ground_at(px, py) > PARAMS["loot_roof_dz"]
            if roof and pz - z > min(self.max_climb, self.max_climb * max(energy, 30.0) / 100.0 + 8.0):
                continue
            if any(hyp(kx, ky, px, py) < 0.8 * d for kx, ky in known):
                continue  # contested: a known mech is nearer to it than we are
            if self.safe_point(obs, px, py, t) >= 1:
                continue
            c = d * (1.0 if kind in ("lightning", "laser") else PARAMS["mortar_cost"]) + (PARAMS["roof_cost_m"] if roof else 0.0)
            if c < bc:
                best, bc, label = (px, py), c, ("p", pid)
        # cubes (kill drops, crates, drones): remembered set within cube_range in the safe zone
        crange = PARAMS["cube_range"]
        for cid, (pos, ts) in ([] if weapons_only else self.mem_cube.items()):
            px, py, pz = pos
            if abs(pz - z) > PARAMS["cube_dz"] or self.econ_black.get(("q", cid), -99) > t:
                continue
            d = hyp(x, y, px, py)
            if d > crange or self.safe_point(obs, px, py, t) >= 1:
                continue
            if any(hyp(kx, ky, px, py) < 0.8 * d for kx, ky in known):
                continue
            c = d * (0.7 if want_w else 1.0)
            if c < bc:
                best, bc, label = (px, py), c, ("q", cid)
        if best is None and self.corpse is not None and not weapons_only:
            px, py, pz, _ = self.corpse
            if self.safe_point(obs, px, py, t) < 1 and self.econ_black.get(("k", self.corpse[3]), -99) <= t:
                best, label = (px, py), ("k", self.corpse[3])
        if best is None:
            self.econ_key = None
            return None
        if urgent and hyp(x, y, *best) > 30.0:
            return None
        # give up on goals that stop getting closer (blocked climb, unreachable courtyard)
        d = hyp(x, y, *best)
        if label != self.econ_key:
            self.econ_key, self.econ_best = label, (d, t)
        elif d < self.econ_best[0] - 2.0:
            self.econ_best = (d, t)
        elif t - self.econ_best[1] > PARAMS["econ_giveup_s"]:
            self.econ_black[label] = t + 40.0
            self.econ_key = None
            return None
        return best, ("arm" if label[0] == "p" else "corpse" if label[0] == "k" else "cubes")

    # ------------------------------------------------------------------ loot
    def loot_goal(self, obs, me, x, y, z, act) -> Optional[Tuple[float, float]]:
        weapons = me.get("weapons") or [None, None]
        held = [w.get("kind") for w in weapons if w]
        slot1 = weapons[1] if len(weapons) > 1 else None
        best = None
        bd = 1e9
        W = self.world
        lim = PARAMS["loot_early_range"] if obs["t"] < self.T["loot_early_t"] else 90.0
        for p in obs.get("pickups") or []:
            kind = p.get("kind")
            pid = int(p.get("id", -1))
            if kind in held or kind == "gun":
                continue
            if obs["t"] - self.taken_fail.get(pid, -99) < 3.0:
                continue
            better = slot1 is None or WEAPON_RANK.get(kind, 0) > WEAPON_RANK.get(slot1.get("kind"), 0)
            if not better:
                continue
            px, py, pz = p["pos"]
            d = hyp(x, y, px, py)
            # v5: roof or not from the map (pickup height above the terrain there), not from our z,
            # so pickups on sloped open ground are kept
            if W is not None:
                if pz - W.ground_at(px, py) > PARAMS["loot_roof_dz"]:
                    continue
            elif abs(pz - z) > 6 and d < 10:
                continue
            if d < self.reach - 0.3 and abs(pz - z) < 4:
                act["take"] = p["id"]
                if slot1 is not None:
                    if slot1.get("kind") == "laser" and slot1.get("charge"):
                        act.pop("take", None)
                    else:
                        act["drop"] = 1
                return None
            # v5: lightning/laser are worth a longer walk than a mortar; search wider early in the match
            de = d * (1.0 if kind in ("lightning", "laser") else 2.0)
            if d < lim and de < bd and (W is not None or abs(pz - z) < 5) and self.safe_point(obs, px, py, obs["t"]) < 1:
                bd, best = de, (px, py)
        for c in obs.get("cubes") or []:
            cxp, cyp, czp = c["pos"]
            d = hyp(x, y, cxp, cyp)
            if d < 60 and d < bd and abs(czp - z) < 4 and self.safe_point(obs, cxp, cyp, obs["t"]) < 1:
                bd, best = d, (cxp, cyp)
        return best

    # ------------------------------------------------------------------ cover
    def choose_cover(self, obs, x, y, z, threats, t, radius: Optional[float] = None) -> None:
        W = self.world
        best = None
        bs = -1e9
        radius = PARAMS["cover_radius"] if radius is None else radius
        cands = [(x, y)]
        rot = 0.2 if int(t * 2) % 2 else 0.0
        # v2: 4 rings x 16 bearings, ordered direction-major so a wall-clock cut still samples every
        # distance; candidates first on the side away from the nearest threat (cover is behind walls)
        if threats:
            th0 = min(threats, key=lambda th: hyp(x, y, th[0], th[1]))
            away = math.atan2(y - th0[1], x - th0[0])
        else:
            away = 0.0
        offs = sorted((k * TAU / 16 for k in range(16)), key=lambda a: abs(wrap(a)))
        for a0 in offs:
            a = away + a0 + rot
            for f in (0.25, 0.5, 0.75, 1.0):
                cands.append((x + radius * f * math.cos(a), y + radius * f * math.sin(a)))
        ths = sorted(threats, key=lambda th: hyp(x, y, th[0], th[1]) / th[3])[:3]
        deadline = self.tick_t0 + self.cover_budget_s
        for (px, py) in cands:
            if time.perf_counter() > deadline:
                break
            if not W.walkable(px, py):
                continue
            dme = hyp(x, y, px, py)
            gz = W.floor[W.idx(px, py)]
            if dme > 3 and not W.line_clear(x, y, px, py):
                # not straight-walkable: keep it only on our own level (A* routes around the block;
                # a roof would need a jet climb), and charge the assumed detour
                if abs(gz - z) > W.rise:
                    continue
                dme *= PARAMS["detour"]
            sc = -dme / 12.0 - self.safe_point(obs, px, py, t)
            can = W.canopy_at(px, py)
            for (tx, ty, tz, wgt) in ths:
                dt = hyp(tx, ty, px, py)
                eye = (tx, ty, tz + 8.0)
                hidden = W.sight_blocked(eye, (px, py, gz + 9.0)) and W.sight_blocked(eye, (px, py, gz + 4.5))
                if hidden:
                    sc += 6.0 * wgt
                elif dt > self.near_range and can >= 4.0:
                    sc += 4.0 * wgt
                elif dt > 200:
                    sc += 2.0 * wgt
                sc += min(dt, 220.0) / 40.0 * wgt
            if (px, py) == (x, y):
                sc += 0.5
            if sc > bs:
                bs, best = sc, (px, py)
        # hysteresis: keep old cover unless clearly better
        if self.cover is not None and best is not None and t - self.cover_t < 3.0:
            ox, oy = self.cover
            if hyp(ox, oy, best[0], best[1]) > 3 and bs < self.cover_score + 1.5:
                self.cover_t = t
                return
        self.cover, self.cover_score, self.cover_t = best, bs, t

    # ------------------------------------------------------------------ steering
    def steer(self, x: float, y: float, goal: Tuple[float, float], t: float, me) -> List[float]:
        W = self.world
        gx, gy = goal
        d = hyp(x, y, gx, gy)
        if d < 0.5:
            return [0.0, 0.0]
        direct = [(gx - x) / d, (gy - y) / d]
        if W is None:
            return direct
        if d < 60 and W.line_clear(x, y, gx, gy):
            self.path = None
            return direct
        # (re)plan
        if self.plan_goal is None or hyp(self.plan_goal[0], self.plan_goal[1], gx, gy) > 6 or \
                (self.path is None and self.planner is None) or t - self.plan_t > 4.0:
            self.planner = worldmod.AStar(W, (x, y), (gx, gy))
            self.plan_goal = (gx, gy)
            self.plan_t = t
        if self.planner is not None:
            if self.planner.step(600, self.tick_t0 + 0.007):
                if self.planner.path:
                    self.path = self.planner.path
                    self.path_i = 0
                    self.path_partial = not self.planner.reached
                self.planner = None
        if self.path and self.path_partial and self.path_i >= len(self.path) - 3 and d > 3:
            # the walkable graph doesn't connect us to the goal (roof, courtyard): jet over toward it.
            # v2: jet time from the height to climb (steady jet rise ~8.9 m/s per SPEC 1.3) + 1 s hop,
            # capped by a full tank (100 energy / 15 per s); v1 used a fixed 2.5 s and only beyond 15 m
            rise = max(0.0, W.floor[W.idx(gx, gy)] - (me.get("pos") or [0, 0, 0])[2])
            self.climb_until = t + min(6.5, rise / 8.9 + 1.0)
            self.path = None
            self.plan_t = t - 2.0  # replan soon after the climb
            return direct
        if self.path:
            pts = self.path
            while self.path_i < len(pts) - 1 and hyp(x, y, *pts[self.path_i]) < 3.0:
                self.path_i += 1
            # skip ahead along visible waypoints
            tgt = pts[self.path_i]
            for k in (min(len(pts) - 1, self.path_i + 12), min(len(pts) - 1, self.path_i + 5)):
                if k > self.path_i and W.line_clear(x, y, *pts[k]):
                    tgt = pts[k]
                    self.path_i = max(self.path_i, k - 2)
                    break
            dd = hyp(x, y, *tgt)
            if dd > 0.3:
                return [(tgt[0] - x) / dd, (tgt[1] - y) / dd]
        # local avoidance while planning
        base = math.atan2(direct[1], direct[0])
        for off in (0.0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5):
            a = base + off
            if W.line_clear(x, y, x + 8 * math.cos(a), y + 8 * math.sin(a)):
                return [math.cos(a), math.sin(a)]
        return direct

    # ------------------------------------------------------------------ aiming
    def scan_aim(self, obs, x, y, t, mv, threats) -> List[float]:
        # v2: a charging laser aimed at us is the most dangerous thing (315 hitscan; a hitscan beam
        # cannot be outrun): keep it inside the front arc so it can't land the x1.5 rear hit
        best = None
        for m in obs.get("mechs") or []:
            if m.get("kind") != "mech" or not m.get("charging"):
                continue
            mx, my_ = m["pos"][0], m["pos"][1]
            dm = hyp(x, y, mx, my_)
            ma = (m.get("aim") or [0, 0])[0]
            if abs(wrap(math.atan2(y - my_, x - mx) - ma)) < math.atan2(self.radius, max(1.0, dm)) + 0.15:
                if best is None or dm < best[0]:
                    best = (dm, math.atan2(my_ - y, mx - x))
        if best is not None:
            return [best[1], 0.0]
        # face the most recent damage / sound / nearest threat; else sweep around
        if t - self.last_damage_t < 3.0 and self.dmg_bearing is not None:
            return [self.dmg_bearing, 0.0]
        if threats:
            th = min(threats, key=lambda th: hyp(x, y, th[0], th[1]) / th[3])
            return [math.atan2(th[1] - y, th[0] - x), 0.0]
        zc = obs["zone"]["next_center"]
        if hyp(x, y, zc[0], zc[1]) > 5:
            base = math.atan2(zc[1] - y, zc[0] - x)
        elif math.hypot(*mv) > 0.1:
            base = math.atan2(mv[1], mv[0])
        else:
            base = self.last_aim[0]
        if t - self.scan_t > 0.8:
            self.scan_t = t
            self.scan_i = (self.scan_i + 1) % 6
        offs = (0.0, 1.9, -1.9, 0.0, math.pi, 0.9)
        return [wrap(base + offs[self.scan_i]), 0.0]

    def lead(self, sx, sy, sz, tp, tv, speed) -> Tuple[float, float, float, float]:
        """First-order intercept: solve |D + V t| = s t + 3 (the shot spawns 3 m out along the aim)
        for the smallest t > 0, aim at D + V t. Falls back to the no-lead point if no solution."""
        dx, dy, dz = tp[0] - sx, tp[1] - sy, tp[2] - sz
        vx, vy, vz = tv
        off = 3.0
        a = vx * vx + vy * vy + vz * vz - speed * speed
        b = 2 * (dx * vx + dy * vy + dz * vz) - 2 * off * speed
        c = dx * dx + dy * dy + dz * dz - off * off
        tt = None
        if abs(a) < 1e-9:
            if abs(b) > 1e-9:
                tt = -c / b
        else:
            disc = b * b - 4 * a * c
            if disc >= 0:
                r = math.sqrt(disc)
                cands = [q for q in ((-b - r) / (2 * a), (-b + r) / (2 * a)) if q > 0]
                tt = min(cands) if cands else None
        if tt is None or tt <= 0:
            tt = max(0.0, (math.sqrt(dx * dx + dy * dy + dz * dz) - off) / speed)
        return tp[0] + vx * tt, tp[1] + vy * tt, tp[2] + vz * tt, tt

    def fire_control(self, me, m, weapons, x, y, z, muz_h):
        sx, sy, sz = x, y, z + muz_h
        tp = m["pos"]
        tv = m.get("vel") or [0, 0, 0]
        is_npc = m.get("kind") in ("npc", "crate")
        # body centre / size: drone r 1.8 h 3.5, crate r 1.4 h 2.4 (config), mech r 2.5 h 9
        dims = {"npc": (1.8, 3.5), "crate": (1.4, 2.4)}.get(m.get("kind"), (self.radius, self.body_h))
        cz = dims[1] / 2
        tpos = (tp[0], tp[1], tp[2] + cz)
        d = hyp(x, y, tp[0], tp[1])
        cur = me.get("aim") or self.last_aim
        kinds = [w.get("kind") if w else None for w in weapons]
        fire = [False, False]

        def aim_to(px, py, pz):
            return [math.atan2(py - sy, px - sx), math.atan2(pz - sz, max(0.1, hyp(sx, sy, px, py)))]

        def err(a):
            dy = abs(wrap(a[0] - cur[0]))
            dp = abs(a[1] - cur[1])
            return math.hypot(dy, dp)

        # pick the aim from the best ready weapon
        aim = None
        primary = None
        for slot in (1, 0):
            w = weapons[slot] if slot < len(weapons) else None
            if not w:
                continue
            k = w.get("kind")
            if k == "lightning" and d <= self.light_range - 2 and me.get("energy", 0) > 8:
                primary = slot
                aim = aim_to(*tpos)
                break
            if k == "laser" and d <= 270 and (w.get("cooldown", 0) <= 0.05 or w.get("charge", 0) > 0):
                primary = slot
                aim = aim_to(*tpos)
                break
            if k == "mortar" and 30 < d < 220 and w.get("cooldown", 0) <= 0.05:
                sol = self.mortar_aim(sx, sy, sz, tpos, tv)
                if sol is not None and (not kinds[0] == "gun" or d > 120):
                    primary = slot
                    aim = sol
                    break
        gun_aim = None
        gun_tt = 0.0
        # v2: the shot leaves on the first tick of this action: advance both ends by one tick
        dt0 = self.tick_dt
        mv_ = me.get("vel") or [0, 0, 0]
        fsx, fsy, fsz = sx + mv_[0] * dt0, sy + mv_[1] * dt0, sz
        if kinds[0] == "gun" and math.dist((sx, sy, sz), tpos) < self.gun_range:
            ftp = (tpos[0] + tv[0] * dt0, tpos[1] + tv[1] * dt0, tpos[2] + tv[2] * dt0)
            lx, ly, lz, gun_tt = self.lead(fsx, fsy, fsz, ftp, tv, self.gun_speed)
            gun_aim = [math.atan2(ly - fsy, lx - fsx), math.atan2(lz - fsz, max(0.1, hyp(fsx, fsy, lx, ly)))]
        if primary is not None and weapons[primary].get("kind") == "laser":
            # hitscan: aim where the target will be when the beam is released (next tick)
            aim = aim_to(tpos[0] + tv[0] * dt0, tpos[1] + tv[1] * dt0, tpos[2])
        if aim is None:
            aim = gun_aim
            primary = 0 if gun_aim else None
        if aim is None:
            return None, fire
        trad, thgt = dims

        def phit(a, tt, spread=None):
            # predicted hit probability if the shot leaves along the *current* torso aim
            return self.gun_hit_p(d, abs(wrap(a[0] - cur[0])) * d, abs(a[1] - cur[1]) * d, tt, spread, trad, thgt)
        e = err(aim)
        if primary is not None:
            w = weapons[primary]
            k = w.get("kind")
            if k == "laser":
                ch = w.get("charge", 0) or 0
                if ch < self.laser_charge:
                    fire[primary] = e < 0.35  # build charge while roughly on target
                else:
                    # release (fire) when on target; keep holding otherwise
                    fire[primary] = phit(aim, self.dec_dt, 0.0) < PARAMS["laser_min_hit_p"]
            elif k == "lightning":
                fire[primary] = abs(wrap(aim[0] - cur[0])) < self.light_cone / 2 - 0.05
            elif k == "mortar":
                fire[primary] = e < 0.04
            else:
                fire[primary] = phit(aim, gun_tt) >= PARAMS["gun_min_hit_p"]
        if gun_aim is not None and primary != 0:
            g = weapons[0]
            if g and (g.get("ammo", 1) > 0) and phit(gun_aim, gun_tt) >= PARAMS["gun_min_hit_p"]:
                fire[0] = True
        return aim, fire

    def mortar_aim(self, sx, sy, sz, tpos, tv) -> Optional[List[float]]:
        v, g = self.mortar_speed, self.mortar_g
        px, py, pz = tpos
        tt = 1.0
        for _ in range(3):
            qx, qy = px + tv[0] * tt, py + tv[1] * tt
            d = hyp(sx, sy, qx, qy)
            dz = pz - 1.0 - (sz + 2.5)
            disc = v ** 4 - g * (g * d * d + 2 * dz * v * v)
            if disc < 0:
                return None
            th = math.atan2(v * v - math.sqrt(disc), g * d)
            if th > 1.25:
                return None
            tt = d / max(1.0, v * math.cos(th))
        return [math.atan2(qy - sy, qx - sx), th]


if __name__ == "__main__":
    try:
        mf.run(Bot)
    finally:
        try:
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(0)  # exit at once after `end` (don't wait on the stdin reader thread)
