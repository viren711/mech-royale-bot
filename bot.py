"""Independent Mech Royale controller built for close-range kill tempo and hard-cover resets."""

import math
import os
import random

import mechfight as mf
import nav


TAU = 2.0 * math.pi
UPGRADE_ORDER = (
    "plating",
    "armor",
    "nanites",
    "gun_damage",
    "gun_rate",
    "laser_damage",
    "laser_charge",
    "lightning_efficiency",
    "lightning_chain",
    "capacitor",
    "servos",
    "reactor",
    "gyros",
    "gun_mag",
    "gun_velocity",
    "jets",
    "sensors",
)


def clamp(value, low, high):
    return max(low, min(high, value))


def angle_error(a, b):
    return (a - b + math.pi) % TAU - math.pi


def direction(x, y):
    length = math.hypot(x, y)
    if length < 1e-9:
        return 0.0, 0.0
    return x / length, y / length


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Bot:
    name = "Kapui-CoverTempo-1"

    def __init__(self, hello):
        self.config = hello.get("config") or {}
        self.rng = random.Random(
            (int(hello.get("seed", 0)) ^ int(hello.get("slot", 0)) * 7919) & 0xFFFFFFFF
        )
        self.map = nav.Map(
            hello["map"]["dir"],
            (self.config.get("mech") or {}).get("max_slope_deg", 50.0),
        )
        self.focus_id = None
        self.orbit = 1.0 if self.rng.random() < 0.5 else -1.0
        self.step_choice = (0.0, 0.0)
        self.step_until = -1.0
        self.healing = False
        self.last_hurt = -100.0
        self.last_dealt = -100.0
        self.last_progress = -100.0
        self.progress_pos = None
        self.recover_until = -1.0
        self.recover_dir = (1.0, 0.0)
        self.loot_memory = {}
        self.crate_memory = {}
        self.heard = None
        self.sound_seen = 0.0
        self.goal_key = None
        self.initial_yaw = 0.0
        self.last_mode = ""

    def point_at(self, target, lead=False):
        me = self.me
        gun = self.weapons[0] if self.weapons else None
        pos = target["pos"]
        target_height = (
            3.5
            if target.get("kind") == "npc"
            else 9.0 * (1.0 + 0.05 * target.get("cubes", 0))
        )
        aim_z = pos[2] + (
            2.0 if target.get("kind") == "crate" else target_height * 0.58
        )
        x, y = pos[0], pos[1]
        if lead and gun:
            speed = max(1.0, (gun.get("stats") or {}).get("speed", 252.0))
            velocity = target.get("vel") or (0.0, 0.0, 0.0)
            flight = distance(pos, me["pos"]) / speed
            for _ in range(3):
                x = pos[0] + velocity[0] * flight
                y = pos[1] + velocity[1] * flight
                aim_z = pos[2] + target_height * 0.58 + velocity[2] * flight * 0.35
                flight = math.hypot(x - me["pos"][0], y - me["pos"][1]) / speed
        muzzle_z = me["pos"][2] + (me.get("stats") or {}).get("muzzle_height", 7.0)
        dx, dy = x - me["pos"][0], y - me["pos"][1]
        yaw = math.atan2(dy, dx)
        pitch = math.atan2(aim_z - muzzle_z, max(0.1, math.hypot(dx, dy)))
        limits = me.get("stats") or {}
        pitch = clamp(
            pitch, limits.get("min_pitch", -0.7), limits.get("max_pitch", 1.3)
        )
        return yaw, pitch, (x, y, aim_z)

    def aim_gate(self, target, yaw, pitch, tolerance=0.7):
        me = self.me
        d = max(2.0, distance(target["pos"], me["pos"]))
        radius = (
            1.8
            if target.get("kind") == "npc"
            else 2.5 * (1.0 + 0.05 * target.get("cubes", 0))
        )
        height = (
            3.5
            if target.get("kind") == "npc"
            else 9.0 * (1.0 + 0.05 * target.get("cubes", 0))
        )
        yaw_ok = (
            abs(angle_error(me["aim"][0], yaw))
            <= math.atan2(radius * tolerance, d) + 0.006
        )
        pitch_ok = abs(me["aim"][1] - pitch) <= math.atan2(height * 0.34, d) + 0.01
        return yaw_ok and pitch_ok

    def shot_line(self, endpoint):
        if self.map is None:
            return True
        stats = self.me.get("stats") or {}
        start = (
            self.me["pos"][0],
            self.me["pos"][1],
            self.me["pos"][2] + stats.get("muzzle_height", 7.0),
        )
        return self.map.los(start, endpoint, step=2.0)

    def visible_shot_line(self, enemy, point):
        if self.map is None:
            return True
        pos = enemy["pos"]
        eye = pos[2] + 8.0 * (1.0 + 0.05 * enemy.get("cubes", 0))
        return self.map.los((pos[0], pos[1], eye), point, step=3.0)

    def standable(self, x, y):
        if self.map is None:
            return True
        ground = self.map.ground(x, y)
        for dx, dy in ((0.0, 0.0), (2.8, 0.0), (-2.8, 0.0), (0.0, 2.8), (0.0, -2.8)):
            if self.map.solid(x + dx, y + dy, ground + 1.0) or self.map.solid(
                x + dx, y + dy, ground + 7.5
            ):
                return False
        return True

    def select_target(self, enemies):
        if not enemies:
            self.focus_id = None
            return None
        scored = []
        for enemy in enemies:
            d = distance(enemy["pos"], self.me["pos"])
            hp_fraction = enemy.get("hp", enemy.get("max_hp", 1400.0)) / max(
                1.0, enemy.get("max_hp", 1400.0)
            )
            score = 0.25 * d + 42.0 * hp_fraction
            held = enemy.get("weapons") or []
            if "laser" in held or "lightning" in held:
                score -= 7.0
            if hp_fraction < 0.25:
                score -= 16.0
            if enemy["id"] == self.focus_id:
                score -= 25.0
            scored.append((score, enemy))
        scored.sort(key=lambda item: item[0])
        self.focus_id = scored[0][1]["id"]
        return scored[0][1]

    def weapon_plan(self, target):
        gun = self.weapons[0] if self.weapons else None
        secondary = self.weapons[1] if len(self.weapons) > 1 else None
        fire = [False, False]
        gun_stats = (gun.get("stats") or {}) if gun else {}
        gun_yaw, gun_pitch, gun_endpoint = self.point_at(target, lead=True)
        direct_yaw, direct_pitch, direct_endpoint = self.point_at(target, lead=False)
        aim = [gun_yaw, gun_pitch]
        d = distance(target["pos"], self.me["pos"])
        if (
            gun
            and gun.get("ammo", 0) > 0
            and gun.get("reload", 0) <= 0
            and d <= gun_stats.get("range", 230.0)
        ):
            fire[0] = self.aim_gate(target, gun_yaw, gun_pitch) and self.shot_line(
                gun_endpoint
            )
        if not secondary:
            return aim, fire
        kind = secondary.get("kind")
        stats = secondary.get("stats") or {}
        if kind == "lightning":
            aim = [direct_yaw, direct_pitch]
            cone = math.radians(stats.get("cone_deg", 30.0)) * 0.38
            ready = (
                secondary.get("cooldown", 0) <= 0
                and self.me["energy"] >= stats.get("energy", 3.0) + 3.0
            )
            fire[1] = (
                ready
                and d < stats.get("range", 45.0) - 1.0
                and abs(angle_error(self.me["aim"][0], direct_yaw)) < cone
            )
            fire[1] = fire[1] and self.shot_line(direct_endpoint)
        elif kind == "laser":
            charge = secondary.get("charge") or 0.0
            full_charge = stats.get("charge", 0.75)
            charged = charge >= full_charge - 0.025
            if charge >= full_charge * 0.55 or charged:
                aim = [direct_yaw, direct_pitch]
            ready = (
                secondary.get("cooldown", 0) <= 0
                and d < stats.get("range", 280.0) - 3.0
            )
            release = (
                charged
                and self.aim_gate(target, direct_yaw, direct_pitch, 0.82)
                and self.shot_line(direct_endpoint)
            )
            fire[1] = ready and not release
        return aim, fire

    def farm_plan(self):
        candidates = []
        for enemy in self.obs.get("mechs") or []:
            if (
                enemy.get("kind") == "npc"
                and distance(enemy["pos"], self.me["pos"]) < 72.0
            ):
                candidates.append(
                    (distance(enemy["pos"], self.me["pos"]) + 22.0, enemy)
                )
        for crate in self.obs.get("crates") or []:
            d = distance(crate["pos"], self.me["pos"])
            if d < 85.0:
                candidates.append((d + 35.0, dict(crate, kind="crate")))
        if not candidates:
            return None, [[self.initial_yaw + self.obs["t"] * 2.7, 0.0], [False, False]]
        candidates.sort(key=lambda item: item[0])
        target = candidates[0][1]
        yaw, pitch, endpoint = self.point_at(target, lead=target.get("kind") == "npc")
        fire = self.aim_gate(target, yaw, pitch) and self.shot_line(endpoint)
        return target, [[yaw, pitch], [fire, False]]

    def fight_step(self, target, enemies):
        d = distance(target["pos"], self.me["pos"])
        secondary = self.weapons[1] if len(self.weapons) > 1 else None
        kind = secondary.get("kind") if secondary else "gun"
        desired = 75.0 if kind == "laser" else (21.0 if kind == "lightning" else 17.0)
        if target.get("hp", 1400.0) < 320.0:
            desired = min(desired, 18.0)
        if self.healing:
            desired = 105.0
        t = self.obs["t"]
        if t >= self.step_until:
            ux, uy = direction(
                target["pos"][0] - self.me["pos"][0],
                target["pos"][1] - self.me["pos"][1],
            )
            tx, ty = -uy * self.orbit, ux * self.orbit
            options = [
                (ux, uy),
                (-ux, -uy),
                (tx, ty),
                (-tx, -ty),
                direction(ux + tx, uy + ty),
                direction(ux - tx, uy - ty),
                direction(-ux + tx, -uy + ty),
                direction(-ux - tx, -uy - ty),
                (0.0, 0.0),
            ]
            speed = (self.me.get("stats") or {}).get("walk_speed", 11.7)
            horizon = 0.55 if not self.healing else 0.85
            reach = speed * horizon
            threats = sorted(
                (e for e in enemies if e["id"] != target["id"]),
                key=lambda e: distance(e["pos"], self.me["pos"]),
            )[:4]
            best_score = -1e9
            best = (tx, ty)
            point_z = self.me["pos"][2] + 4.5
            for vx, vy in options:
                x = self.me["pos"][0] + vx * reach
                y = self.me["pos"][1] + vy * reach
                if (vx or vy) and not self.standable(x, y):
                    continue
                nd = math.hypot(target["pos"][0] - x, target["pos"][1] - y)
                score = -abs(nd - desired) * (1.0 if not self.healing else 0.08)
                if self.healing:
                    score += nd * 0.22
                score += 1.8 * (vx * self.step_choice[0] + vy * self.step_choice[1])
                point = (x, y, point_z)
                target_visible = self.visible_shot_line(target, point)
                if not target_visible:
                    score -= 9.0 if not self.healing else -18.0
                for other in threats:
                    if self.visible_shot_line(other, point):
                        score -= 42.0 if self.healing else 10.0
                    else:
                        score += 14.0 if self.healing else 2.5
                zone = self.obs["zone"]
                margin = zone["next_radius"] - math.hypot(
                    x - zone["next_center"][0], y - zone["next_center"][1]
                )
                if margin < 3.0:
                    score -= 80.0
                if score > best_score:
                    best_score, best = score, (vx, vy)
            self.step_choice = best
            self.step_until = t + (0.35 if not self.healing else 0.5)
            if best_score < -70.0:
                self.orbit *= -1.0
        return list(self.step_choice)

    def remember_loot(self):
        visible_ids = set()
        for pickup in self.obs.get("pickups") or []:
            if pickup.get("kind") not in ("laser", "lightning"):
                continue
            visible_ids.add(pickup["id"])
            self.loot_memory[pickup["id"]] = pickup
        visible_crates = set()
        for crate in self.obs.get("crates") or []:
            visible_crates.add(crate["id"])
            self.crate_memory[crate["id"]] = crate
        for key in list(self.loot_memory):
            pos = self.loot_memory[key]["pos"]
            if distance(pos, self.me["pos"]) < 7.0 and key not in visible_ids:
                del self.loot_memory[key]
        for key, crate in list(self.crate_memory.items()):
            if (
                key not in visible_crates
                and distance(crate["pos"], self.me["pos"]) < 35.0
            ):
                del self.crate_memory[key]

    def floor_loot(self, item):
        if self.map is None:
            return True
        return item["pos"][2] < self.map.ground(item["pos"][0], item["pos"][1]) + 4.0

    def wants_weapon(self, kind):
        if kind not in ("laser", "lightning"):
            return False
        held = {weapon.get("kind") for weapon in self.weapons if weapon}
        if kind in held:
            return False
        if len(self.weapons) < 2 or self.weapons[1] is None:
            return True
        return self.weapons[1].get("kind") == "lightning" and kind == "laser"

    def economy_goal(self):
        me_pos = self.me["pos"]
        drops = []
        for drop in self.obs.get("drops") or []:
            d = distance(drop["pos"], me_pos)
            if (
                drop.get("lands_in", 1.0) <= 0
                and d < 95.0
                and (d < 45.0 or self.me["hp"] < self.me["max_hp"] * 0.9)
            ):
                drops.append((d - 70.0, ("drop", drop["id"]), drop["pos"], 1.0))
        if drops:
            return min(drops, key=lambda item: item[0])[1:]
        held = {w.get("kind") for w in self.weapons if w}
        choices = []
        for pickup in self.loot_memory.values():
            kind = pickup["kind"]
            if not self.wants_weapon(kind) or not self.floor_loot(pickup):
                continue
            d = distance(pickup["pos"], me_pos)
            if d > (190.0 if self.obs["t"] < 45.0 else 105.0):
                continue
            priority = -32.0 if kind == "laser" and "laser" not in held else -15.0
            if kind == "lightning" and "laser" in held:
                priority = 35.0
            choices.append((d + priority, ("weapon", pickup["id"]), pickup["pos"], 2.3))
        for cube in self.obs.get("cubes") or []:
            d = distance(cube["pos"], me_pos)
            if d < 65.0:
                choices.append((d + 18.0, ("cube", cube["id"]), cube["pos"], 1.5))
        for crate in self.crate_memory.values():
            d = distance(crate["pos"], me_pos)
            if d < 65.0 and self.floor_loot(crate):
                choices.append((d + 45.0, ("crate", crate["id"]), crate["pos"], 24.0))
        if choices:
            return min(choices, key=lambda item: item[0])[1:]
        if (
            self.heard
            and self.obs["t"] < self.heard[3]
            and self.me["hp"] > self.me["max_hp"] * 0.72
        ):
            return ("sound", 0), (self.heard[0], self.heard[1], self.me["pos"][2]), 12.0
        zone = self.obs["zone"]
        center = zone["next_center"]
        phase = int(self.obs["t"] // 18.0)
        yaw = (phase * 2.399963 + self.rng.random() * 0.02) % TAU
        radius = min(55.0, zone["next_radius"] * 0.3)
        return (
            ("patrol", phase),
            (
                center[0] + math.cos(yaw) * radius,
                center[1] + math.sin(yaw) * radius,
                me_pos[2],
            ),
            8.0,
        )

    def steer_goal(self, key, goal, arrival):
        dx, dy = goal[0] - self.me["pos"][0], goal[1] - self.me["pos"][1]
        d = math.hypot(dx, dy)
        if d <= arrival:
            return [0.0, 0.0], d
        direct = direction(dx, dy)
        probe = min(8.0, d)
        if d <= 30.0 and self.standable(
            self.me["pos"][0] + direct[0] * probe, self.me["pos"][1] + direct[1] * probe
        ):
            return list(direct), d
        rounded_key = (key, round(goal[0] / 10.0), round(goal[1] / 10.0))
        if self.map is not None:
            if rounded_key != self.goal_key:
                self.goal_key = rounded_key
                self.map.start_flow(goal[0], goal[1])
            self.map.step_flow(6000)
            flow = self.map.flow_dir(self.me["pos"][0], self.me["pos"][1])
            if flow:
                return list(flow), d
        ux, uy = direct
        for sign in (self.orbit, -self.orbit):
            side = (-uy * sign, ux * sign)
            if self.standable(
                self.me["pos"][0] + side[0] * 7.0, self.me["pos"][1] + side[1] * 7.0
            ):
                return list(
                    direction(direct[0] * 0.25 + side[0], direct[1] * 0.25 + side[1])
                ), d
        return list(direct), d

    def zone_override(self):
        zone = self.obs["zone"]
        pos = self.me["pos"]
        current_margin = zone["radius"] - math.hypot(
            pos[0] - zone["center"][0], pos[1] - zone["center"][1]
        )
        next_margin = zone["next_radius"] - math.hypot(
            pos[0] - zone["next_center"][0], pos[1] - zone["next_center"][1]
        )
        if (
            not self.me.get("in_zone", True)
            or current_margin < 18.0
            or next_margin < 18.0
        ):
            goal = (zone["next_center"][0], zone["next_center"][1], pos[2])
            key = ("zone", round(goal[0]), round(goal[1]))
            move, d = self.steer_goal(key, goal, 8.0)
            energy_floor = 8.0 if not self.me.get("in_zone", True) else 25.0
            return move, self.me["energy"] > energy_floor and d > 12.0
        return None

    def combat_loot_goal(self, target):
        held = {w.get("kind") for w in self.weapons if w}
        if "laser" in held:
            return None
        choices = []
        for pickup in self.obs.get("pickups") or []:
            if pickup.get("kind") not in ("laser", "lightning"):
                continue
            if not self.wants_weapon(pickup["kind"]) or not self.floor_loot(pickup):
                continue
            d = distance(pickup["pos"], self.me["pos"])
            enemy_d = distance(target["pos"], self.me["pos"])
            if d > 105.0 or (enemy_d < 24.0 and d > 12.0):
                continue
            priority = 0.0 if pickup["kind"] == "laser" else 22.0
            choices.append((d + priority, pickup))
        if not choices:
            return None
        pickup = min(choices, key=lambda item: item[0])[1]
        return ("combat-loot", pickup["id"]), pickup["pos"], 2.3

    def take_reflex(self):
        if len(self.weapons) < 2:
            return None
        secondary = self.weapons[1]
        if (
            secondary
            and secondary.get("kind") == "laser"
            and (secondary.get("charge") or 0) > 0
        ):
            return None
        candidates = []
        for pickup in self.obs.get("pickups") or []:
            kind = pickup.get("kind")
            if (
                not self.wants_weapon(kind)
                or distance(pickup["pos"], self.me["pos"]) > 3.8
                or abs(pickup["pos"][2] - self.me["pos"][2]) > 3.8
            ):
                continue
            rank = 1 if secondary is not None else 0
            enemies_near = any(
                distance(e["pos"], self.me["pos"]) < 48.0 for e in self.enemies
            )
            if rank == 1 and enemies_near:
                continue
            candidates.append((rank, pickup))
        if not candidates:
            return None
        pickup = min(candidates, key=lambda item: item[0])[1]
        action = {"take": pickup["id"]}
        if secondary is not None:
            action["drop"] = 1
        return action

    def dodge_reflex(self, move):
        x, y, z = self.me["pos"]
        dodge_x = dodge_y = 0.0
        for projectile in self.obs.get("projectiles") or []:
            if projectile.get("kind") == "mortar":
                continue
            px, py, pz = projectile["pos"]
            vx, vy, vz = projectile["vel"]
            speed2 = vx * vx + vy * vy + vz * vz
            if speed2 < 1.0:
                continue
            rx, ry, rz = px - x, py - y, pz - (z + 4.5)
            closest = clamp(-(rx * vx + ry * vy + rz * vz) / speed2, 0.0, 0.65)
            miss_x, miss_y = rx + vx * closest, ry + vy * closest
            miss_z = rz + vz * closest
            if closest > 0 and math.hypot(miss_x, miss_y) < 4.5 and abs(miss_z) < 5.0:
                sx, sy = direction(-vy, vx)
                if sx * miss_x + sy * miss_y > 0:
                    sx, sy = -sx, -sy
                dodge_x += sx * 1.5
                dodge_y += sy * 1.5
        for enemy in self.enemies:
            if not enemy.get("charging") or "laser" not in (enemy.get("weapons") or []):
                continue
            yaw = (enemy.get("aim") or [0.0])[0]
            ax, ay = math.cos(yaw), math.sin(yaw)
            rx, ry = x - enemy["pos"][0], y - enemy["pos"][1]
            along = rx * ax + ry * ay
            across = rx * ay - ry * ax
            if 0 < along < 285.0 and abs(across) < 5.0:
                sign = 1.0 if across >= 0 else -1.0
                dodge_x += ay * sign * 2.0
                dodge_y -= ax * sign * 2.0
        if not dodge_x and not dodge_y:
            return move, False
        dx, dy = direction(move[0] + dodge_x, move[1] + dodge_y)
        return [dx, dy], self.me["energy"] > 15.0

    def act(self, obs):
        self.obs = obs
        self.me = obs["self"]
        self.weapons = self.me.get("weapons") or []
        self.enemies = [m for m in obs.get("mechs") or [] if m.get("kind") == "mech"]
        if not self.progress_pos:
            self.progress_pos = tuple(self.me["pos"][:2])
            self.initial_yaw = self.me["aim"][0]
        for event in obs.get("events") or []:
            if event.get("type") == "damaged":
                self.last_hurt = obs["t"]
            elif event.get("type") == "hit":
                self.last_dealt = obs["t"]
                target_id = event.get("target")
                if target_id in self.crate_memory:
                    crate = self.crate_memory[target_id]
                    crate["hp"] = crate.get("hp", 300.0) - event.get("amount", 0.0)
                    if crate["hp"] <= 0:
                        del self.crate_memory[target_id]
            elif event.get("type") == "kill":
                self.healing = False
                self.step_until = -1.0
        self.remember_loot()
        target = self.select_target(self.enemies)
        hp_fraction = self.me["hp"] / max(1.0, self.me["max_hp"])
        close_enemies = sum(
            distance(e["pos"], self.me["pos"]) < 85.0 for e in self.enemies
        )
        nearly_dead = target and target.get("hp", 1400.0) < min(
            280.0, target.get("max_hp", 1400.0) * 0.22
        )
        if (
            hp_fraction < 0.34
            or (hp_fraction < 0.62 and close_enemies >= 2 and not nearly_dead)
            or (hp_fraction < 0.48 and target and not nearly_dead)
        ):
            self.healing = True
            self.step_until = -1.0
        elif self.healing and hp_fraction >= 0.9 and obs["t"] - self.last_hurt >= 4.8:
            self.healing = False
            self.step_until = -1.0
        for sound in obs.get("sounds") or []:
            if sound.get("kind") not in ("gun", "laser", "lightning", "mortar"):
                continue
            estimated = {"near": 38.0, "mid": 105.0, "far": 220.0}.get(
                sound.get("dist"), 150.0
            )
            bearing = sound.get("bearing", 0.0)
            self.heard = (
                self.me["pos"][0] + math.cos(bearing) * estimated,
                self.me["pos"][1] + math.sin(bearing) * estimated,
                0.0,
                obs["t"] + 8.0,
            )
        action = {}
        offer = obs.get("offer")
        if offer:
            choices = [choice["id"] for choice in offer.get("choices") or []]
            action["pick"] = min(
                range(len(choices)),
                key=lambda i: (
                    UPGRADE_ORDER.index(choices[i])
                    if choices[i] in UPGRADE_ORDER
                    else 100
                ),
            )
        taken = self.take_reflex()
        if taken:
            action.update(taken)
        move = [0.0, 0.0]
        boost = False
        aim = [self.initial_yaw + obs["t"] * 2.7, 0.0]
        fire = [False, False]
        mode = "patrol"
        farm_target = None
        zone_move = self.zone_override()
        if target:
            aim, fire = self.weapon_plan(target)
            move = self.fight_step(target, self.enemies)
            boost = self.healing and self.me["energy"] > 18.0
            mode = "heal" if self.healing else "fight"
            loot_goal = self.combat_loot_goal(target)
            if loot_goal and not self.healing and not zone_move:
                key, goal, arrival = loot_goal
                move, goal_distance = self.steer_goal(key, goal, arrival)
                boost = goal_distance > 28.0 and self.me["energy"] > 30.0
                mode = "combat-loot"
        else:
            farm_target, farm = self.farm_plan()
            aim, fire = farm
            key, goal, arrival = self.economy_goal()
            goal_distance = distance(goal, self.me["pos"])
            if not zone_move:
                move, goal_distance = self.steer_goal(key, goal, arrival)
            boost = goal_distance > 38.0 and self.me["energy"] > 38.0 and not fire[0]
            mode = "farm" if fire[0] else "loot"
            if self.healing:
                fire = [False, False]
                mode = "recover"
        if zone_move:
            move, boost = zone_move
            mode = "zone"
        if obs["t"] < 1.6 and not self.enemies and self.me["energy"] > 70.0:
            aim = [self.initial_yaw + obs["t"] * 3.8, 0.15]
            if not self.me.get("grounded"):
                boost = True
            mode = "scan"
        move, dodging = self.dodge_reflex(move)
        boost = boost or dodging
        current_pos = tuple(self.me["pos"][:2])
        if math.hypot(move[0], move[1]) > 0.4:
            if (
                math.dist(current_pos, self.progress_pos) < 0.22
                and obs["t"] - self.last_progress > 1.1
            ):
                yaw = math.atan2(move[1], move[0]) + self.orbit * 1.25
                self.recover_dir = (math.cos(yaw), math.sin(yaw))
                self.recover_until = obs["t"] + 1.0
                self.orbit *= -1.0
                self.last_progress = obs["t"]
            elif math.dist(current_pos, self.progress_pos) >= 0.22:
                self.last_progress = obs["t"]
                self.progress_pos = current_pos
        jump = False
        if obs["t"] < self.recover_until:
            move = list(self.recover_dir)
            jump = self.me.get("grounded", False)
            boost = self.me["energy"] > 20.0
        boost = boost and self.me.get("grounded", False)
        gun = self.weapons[0] if self.weapons else None
        if gun and not target and gun.get("reload", 0) <= 0:
            mag = (gun.get("stats") or {}).get("mag", 12)
            if gun.get("ammo", mag) <= max(3, int(mag * 0.65)) and not fire[0]:
                action["reload"] = True
        action.update(move=move, boost=boost, jump=jump, aim=aim, fire=fire)
        if mode != self.last_mode:
            self.last_mode = mode
        return action


if __name__ == "__main__":
    mf.run(Bot)
