"""Combat candidate: early loot, weapon-specific aiming, strafing and recovery."""
import math

from bot import angle_delta, lead, unit
from survivor import TerrainArena
from navigation import Navigator
import mechfight as mf


class Combat:
    name = 'Oval-Sentinel-recovery-v26'

    def __init__(self, hello):
        self.config = hello['config']
        self.arena = TerrainArena(hello['map']['dir'])
        self.side = 1 if hello['slot'] % 2 else -1
        self.previous = None
        self.stuck = 0
        self.jet_until = -1
        self.boosting = False
        self.target_id = None
        self.arc_resting = False
        self.navigator = Navigator(self.arena)
        self.cover_goal = None
        self.cover_after = -1
        self.healing = False
        self.pickup_memory = {}
        self.cube_memory = {}
        self.last_threat = (-100, 0)
        self.progress_pos = None
        self.progress_at = 0
        self.zone_urgent = False

    def update_recovery(self, hp):
        # Enter only below 25%; finish a recovery rather than oscillating at 25%.
        if hp >= .60:
            self.healing = False
            self.cover_goal = None
        elif hp < .25:
            self.healing = True

    def aim_at(self, me, target, kind, weapon):
        scale = 1 + 0.05 * target.get('cubes', 0)
        height = 4.5 * scale if target.get('kind') == 'mech' else 1.75 if target.get('kind') == 'npc' else 1.0
        stats = weapon['stats']
        origin = [*me['pos'][:2], me['pos'][2] + me['stats']['muzzle_height']]
        center = [*target['pos'][:2], target['pos'][2] + height]
        if kind == 'gun':
            point = lead(origin, dict(target, pos=center), stats['speed'])
        elif kind == 'mortar':
            origin[2] = me['pos'][2] + me['stats']['height'] + 0.5
            point = list(center)
            pitch = None
            for _ in range(3):
                distance = math.dist(origin[:2], point[:2])
                dz = point[2] - origin[2]
                v, g = stats['speed'], stats['gravity']
                disc = v**4 - g * (g * distance**2 + 2 * dz * v*v)
                if disc < 0 or distance < 12:
                    return None
                pitch = math.atan2(v*v - math.sqrt(disc), g * distance)
                flight = distance / max(1, v * math.cos(pitch))
                point = [center[i] + target.get('vel', [0, 0, 0])[i] * flight for i in range(3)]
            if not me['stats']['min_pitch'] <= pitch <= me['stats']['max_pitch']:
                return None
            return [math.atan2(point[1] - origin[1], point[0] - origin[0]), pitch], origin, point
        else:
            point = center
        dx, dy, dz = [point[i] - origin[i] for i in range(3)]
        return [math.atan2(dy, dx), math.atan2(dz, math.hypot(dx, dy))], origin, point

    def is_hostile(self, m, pos, now):
        # Fight only mechs that are after us: hit us recently, aim at us, charging a laser, close, or closing in fast.
        if now - getattr(self, 'attackers', {}).get(m['id'], -99) < 10:
            return True
        dx, dy = pos[0] - m['pos'][0], pos[1] - m['pos'][1]
        d = math.hypot(dx, dy)
        if d < 50 or m.get('charging'):
            return True
        diff = (m['aim'][0] - math.atan2(dy, dx) + math.pi) % (2 * math.pi) - math.pi
        if d < 230 and abs(diff) < .28:
            return True
        return d < 170 and (m['vel'][0] * dx + m['vel'][1] * dy) / max(d, 1) > 4

    def laser_should_release(self, me, target, weapon):
        stats = weapon['stats']
        charge = weapon.get('charge', 0)
        if charge + .01 >= stats['charge']:
            return True
        if charge < stats['min_charge']:
            return False
        damage = stats['damage'] * (1 + .04 * min(10, me['cubes']))
        damage *= stats['min_frac'] + (1 - stats['min_frac']) * charge / stats['charge']
        if target.get('kind') == 'mech':
            # Enemy upgrades are hidden. Assume all three armor stacks and
            # leave a margin for rounded HP and observations between ticks.
            damage *= .76
            if 'mortar' in target.get('weapons', []):
                damage *= 1 + stats['cookoff']
        return damage >= target.get('hp', math.inf) + 15

    def aligned(self, me, aim, distance, radius=2.0):
        # The server slews the torso before simulating shots. Permit a trigger
        # when it can align during the next simulation tick, not only when the
        # previous observation already happened to be aligned.
        yaw_error = max(0, abs(angle_delta(aim[0], me['aim'][0])) - me['stats']['turn_rate'] * 0.05)
        pitch_error = max(0, abs(aim[1] - me['aim'][1]) - me['stats']['pitch_rate'] * 0.05)
        return yaw_error <= max(0.018, math.atan2(radius, max(1, distance))) and pitch_error <= max(0.02, math.atan2(3, max(1, distance)))

    def act(self, obs):
        me, zone, now = obs['self'], obs['zone'], obs['t']
        pos, stats = me['pos'], me['stats']
        x, y, z = pos
        hp = me['hp'] / me['max_hp']
        if not hasattr(self, 'attackers'):
            self.attackers = {}
        for event in obs['events']:
            if event['type'] == 'damaged' and event.get('by') is not None:
                self.attackers[event['by']] = now
            if event['type'] == 'damaged' and event.get('bearing') is not None:
                self.last_threat = (now, event['bearing'])
        weapons = me['weapons']
        action = {'tick': obs['tick'], 'fire': [False, False], 'boost': False, 'jump': False}
        by_kind = {w['kind']: (i, w) for i, w in enumerate(weapons) if w}
        for key, memory in (('pickups', self.pickup_memory), ('cubes', self.cube_memory)):
            seen = {item['id'] for item in obs[key]}
            for item in obs[key]:
                memory[item['id']] = (now, item)
            for item_id, (last_seen, item) in list(memory.items()):
                if now - last_seen > 12 or (item_id not in seen and math.dist(pos, item['pos']) < 5):
                    del memory[item_id]
        known_pickups = [item for _, item in self.pickup_memory.values()]
        known_cubes = [item for _, item in self.cube_memory.values()]
        if self.arc_resting:
            self.arc_resting = me['energy'] < min(65, me['max_energy'] * .65)
        elif me['energy'] < 20:
            self.arc_resting = True
        mechs = [m for m in obs['mechs'] if m['kind'] == 'mech']
        nearest = min((math.dist(pos, m['pos']) for m in mechs), default=1e9)
        close_count = sum(math.dist(pos, m['pos']) < 100 for m in mechs)
        self.update_recovery(hp)
        recovering = self.healing and nearest > 55
        if obs['offer']:
            ranks = {'gun_damage': 88, 'gun_rate': 86, 'gun_mag': 98, 'plating': 100, 'armor': 94,
                     'servos': 95, 'nanites': 96 if hp < .55 else 80, 'reactor': 77, 'jets': 70, 'capacitor': 60,
                     'lightning_efficiency': 108, 'lightning_range': 106, 'laser_damage': 115,
                     'laser_charge': 110, 'gun_velocity': 78}
            action['pick'] = max(range(len(obs['offer']['choices'])), key=lambda i: ranks.get(obs['offer']['choices'][i]['id'], 25))

        # Early second-weapon acquisition is worth a short detour. Empty slots
        # accept any weapon; later replacements are based on the actual matchup.
        pickup_candidates = []
        for p in known_pickups:
            if p['kind'] in by_kind or abs(p['pos'][2] - z) > 4:
                continue
            distance = math.dist(pos, p['pos'])
            wanted = any(w is None for w in weapons) and p['kind'] != 'mortar'
            replace = None
            if not wanted and 'mortar' in by_kind and p['kind'] in ('laser', 'lightning'):
                wanted, replace = True, by_kind['mortar'][0]
            if not wanted and p['kind'] == 'laser' and 'lightning' in by_kind and nearest > 45:
                wanted, replace = True, by_kind['lightning'][0]
            if wanted:
                pickup_candidates.append((distance / (1.8 if p['kind'] == 'laser' else 1.1 if p['kind'] == 'lightning' else .8), p))
                if distance <= self.config['loot']['pickup_radius']:
                    action['take'] = p['id']
                    if replace is not None and weapons[replace].get('charge', 0) == 0:
                        action['drop'] = replace

        origin = [x, y, z + stats['muzzle_height']]
        targets = []
        for m in obs['mechs']:
            distance = math.dist(pos, m['pos'])
            if m['kind'] == 'npc' and (nearest < 90 or distance > 65):
                continue
            if m['kind'] == 'mech' and not self.is_hostile(m, pos, now):
                continue
            top = m['pos'][2] + (4.5 * (1 + .05 * m.get('cubes', 0)) if m['kind'] == 'mech' else 1.75)
            if not self.arena.clear_shot(origin, [*m['pos'][:2], top]):
                continue
            value = distance + m.get('hp', 1400) * .045
            if m['kind'] == 'npc':
                value += 45
            if m['id'] == self.target_id:
                value -= 18
            if m.get('hp', 1400) < 300:
                value -= 40
            targets.append((value, m))
        if nearest > 90 and not recovering:
            for crate in obs['crates']:
                distance = math.dist(pos, crate['pos'])
                if distance < 65 and abs(crate['pos'][2] - z) < 6 and self.arena.clear_shot(origin, [*crate['pos'][:2], crate['pos'][2] + 1]):
                    targets.append((distance + 65, dict(crate, kind='crate', vel=[0, 0, 0])))
        target = min(targets, key=lambda pair: pair[0])[1] if targets else None
        self.target_id = target['id'] if target else None

        # Hold favorable territory instead of automatically walking into the
        # coordinated squad. Move to the next circle when its edge will catch us.
        goal = list(pos[:2])
        if not self.healing and nearest > 80 and (len(by_kind) < 2 or (now < 45 and me['cubes'] < 3)):
            # An empty-handed spawn behind cover needs exploration; scanning in
            # place cannot reveal loot on the other side of the building.
            goal = list(zone['next_center'])
        seeking_loot = False
        to_next = self.navigator.zone_distance(pos, zone, now)
        urgent = not me['in_zone'] or (to_next > 0 and now + to_next / stats['walk_speed'] + 8 >= zone['shrink_end'])
        self.zone_urgent = urgent
        if urgent or zone['next_radius'] <= 30:
            goal = list(zone['next_center'])
        # Don't abandon an early duel just because a shrinking phase has begun.
        if not urgent and zone['next_radius'] > 30:
            if pickup_candidates and min(pickup_candidates, key=lambda pair: pair[0])[0] < 80 and nearest > 35:
                goal = min(pickup_candidates, key=lambda pair: pair[0])[1]['pos'][:2]
                seeking_loot = True
            elif known_cubes and nearest > 40 and me['cubes'] < 10:
                cube = min(known_cubes, key=lambda c: math.dist(pos, c['pos']))
                collect_range = 140 if nearest > 80 else 80
                if math.dist(pos, cube['pos']) < collect_range and abs(cube['pos'][2] - z) < 4:
                    goal = cube['pos'][:2]
                    seeking_loot = True
            elif target and target['kind'] != 'mech':
                goal = target['pos'][:2]

        if self.healing and mechs and now >= self.cover_after:
            # Keep useful shelter instead of choosing a different hiding place
            # every two seconds while regeneration needs five quiet seconds.
            sheltered = self.cover_goal is not None and math.dist(pos[:2], self.cover_goal[:2]) < 8
            if sheltered:
                body = [x, y, z + stats['height'] * .75]
                sheltered = all(not self.arena.clear_shot([*e['pos'][:2], e['pos'][2] + 7], body)
                                for e in mechs)
            if not sheltered:
                self.cover_goal = self.navigator.cover(pos, mechs, zone)
            self.cover_after = now + 2
        seeking_cover = self.healing and self.cover_goal is not None and not urgent
        if seeking_cover:
            goal = self.cover_goal[:2]
        supply = None
        if not urgent and (hp < .85 or me['cubes'] < 10):
            options = []
            for drop in obs['drops']:
                distance = math.dist(pos, drop['pos'])
                if distance > (130 if hp < .7 else 85) or drop['holder'] not in (None, me['id']):
                    continue
                if drop['lands_in'] > distance / stats['walk_speed'] + 5:
                    continue
                if math.dist(drop['pos'][:2], zone['next_center']) > zone['next_radius'] - 8:
                    continue
                opposition = min((math.dist(drop['pos'], e['pos']) for e in mechs), default=1e9)
                if opposition < 55 and not (drop['holder'] == me['id'] and drop['capture_s'] - drop['progress'] < 1):
                    continue
                options.append((distance, drop))
            if options:
                supply = min(options, key=lambda pair: pair[0])[1]
                goal = supply['pos'][:2]
                seeking_loot = True
                seeking_cover = False
        travel_goal = goal
        if math.dist(pos[:2], goal) > 15:
            travel_goal = self.navigator.waypoint(pos, goal, now)

        direction = unit(travel_goal[0] - x, travel_goal[1] - y)
        if target and target['kind'] == 'mech' and not urgent and not seeking_loot and not seeking_cover and zone['next_radius'] > 20:
            ex, ey = unit(target['pos'][0] - x, target['pos'][1] - y)
            distance = math.dist(pos, target['pos'])
            preferred = (60 if self.arc_resting else 35) if 'lightning' in by_kind else 90 if 'laser' in by_kind else 60
            if 'lightning' in target.get('weapons', []) and 'laser' in by_kind:
                preferred = 110
            if hp < 0.35 or close_count >= 3:
                preferred += 40
            radial = max(-1.3, min(1.2, (distance - preferred) / 25))
            strafe = self.side * (1 if int(now / 2.2) % 2 == 0 else -1)
            direction = unit(ex * radial - ey * strafe, ey * radial + ex * strafe)
        if math.dist(pos[:2], goal) < 2 and target is None:
            direction = (0, 0)
        if supply and math.dist(pos[:2], supply['pos'][:2]) < supply['radius'] - 3:
            direction = (0, 0)
        self.navigate(action, obs, direction)
        action['aim'] = [me['aim'][0] + .3, 0]
        if now - self.last_threat[0] < 2:
            action['aim'] = [self.last_threat[1], 0]
        elif mechs:
            watch = min(mechs, key=lambda enemy: math.dist(pos, enemy['pos']))
            action['aim'] = [math.atan2(watch['pos'][1] - y, watch['pos'][0] - x), 0]

        if target:
            distance = math.dist(pos, target['pos'])
            chosen = by_kind.get('gun')
            laser = by_kind.get('laser')
            mortar = by_kind.get('mortar')
            escaping_zone = not me['in_zone']
            # Observed charge is rounded to 2 decimals, while upgraded charge
            # duration is rounded to 3 (.56 versus .563). Without tolerance a
            # full beam waits for the automatic two-second hold timeout.
            if laser and (self.laser_should_release(me, target, laser[1]) or
                          (escaping_zone and laser[1].get('charge', 0) > 0)):
                chosen = laser
            elif mortar and mortar[1]['cooldown'] <= .05 and distance > 25:
                chosen = mortar
            elif not chosen:
                chosen = next(iter(by_kind.values()), None)
            if chosen:
                slot, weapon = chosen
                solution = self.aim_at(me, target, weapon['kind'], weapon)
                if solution:
                    aim, muzzle, point = solution
                    action['aim'] = aim
                    aligned = self.aligned(me, aim, distance)
                    # Keep defending while exposed. Stopping in the open cannot
                    # start regeneration because incoming hits reset its timer.
                    can_fight = not (seeking_cover and math.dist(pos[:2], goal) < 8 and target['kind'] != 'mech')
                    if weapon['kind'] == 'gun':
                        action['fire'][slot] = bool(can_fight and aligned and distance < weapon['stats']['range'] and weapon.get('ammo', 0) > 0 and self.arena.clear_shot(muzzle, point))
                    elif weapon['kind'] == 'mortar':
                        action['fire'][slot] = bool(can_fight and aligned)
                    if laser and distance < laser[1]['stats']['range'] and can_fight:
                        charged = self.laser_should_release(me, target, laser[1]) or escaping_zone
                        if not escaping_zone or laser[1].get('charge', 0) > 0:
                            # Outside the zone, discharge along the correct aim
                            # and do not begin another movement-halving charge.
                            action['fire'][laser[0]] = bool(not charged or not (weapon['kind'] == 'laser' and aligned))
                    lightning = by_kind.get('lightning')
                    if lightning:
                        w = lightning[1]
                        yaw = math.atan2(target['pos'][1] - y, target['pos'][0] - x)
                        action['fire'][lightning[0]] = bool(can_fight and not self.arc_resting and distance < w['stats']['range'] and me['energy'] >= w['stats']['energy'] + 8 and abs(angle_delta(yaw, me['aim'][0])) < math.radians(w['stats']['cone_deg']) * .85)
        if 'gun' in by_kind:
            gun = by_kind['gun'][1]
            action['reload'] = bool(gun.get('ammo', 0) == 0 or (target is None and nearest > 100 and gun.get('ammo', 0) <= gun['stats']['mag'] - 3))
        if self.healing and target is None and nearest > 55:
            action['fire'] = [False, False]
        return action

    def navigate(self, action, obs, direction):
        me, zone, now = obs['self'], obs['zone'], obs['t']
        pos, stats = me['pos'], me['stats']
        yaw = math.atan2(direction[1], direction[0])
        kinds = {w['kind'] for w in me['weapons'] if w}
        enemies = sorted((e for e in obs['mechs'] if e['kind'] == 'mech' and e.get('hp', 1400) > 150),
                         key=lambda e: math.dist(pos, e['pos']))[:4]
        separation = 30 if 'lightning' in kinds and not self.arc_resting else 85 if 'laser' in kinds else 55
        if self.healing:
            separation += 25
        candidates = []
        for offset in (0, .35, -.35, .7, -.7, 1.2, -1.2, 1.7, -1.7, 2.3, -2.3, math.pi):
            d = (math.cos(yaw + offset), math.sin(yaw + offset))
            if not self.arena.clear_move(pos, d, stats):
                continue
            future = [pos[0] + d[0] * 10, pos[1] + d[1] * 10]
            score = math.cos(offset) - max(0, math.dist(future, zone['center']) - max(0, zone['radius'] - 5)) * .3
            velocity = me.get('vel', [0, 0, 0])
            score += .15 * sum(d[i] * velocity[i] for i in range(2)) / stats['walk_speed']
            # Circle travel must not walk straight into a fresh enemy's weapon
            # range. This potential allows a sideways approach to the safe area.
            for enemy in enemies:
                distance = math.dist(future, enemy['pos'][:2])
                score -= 8 * max(0, 1 - distance / separation) ** 2
            for projectile in obs['projectiles'][:30]:
                rel = [projectile['pos'][i] - pos[i] for i in range(2)]
                velocity = [projectile['vel'][i] - d[i] * stats['walk_speed'] for i in range(2)]
                speed2 = sum(v*v for v in velocity)
                t = -sum(rel[i]*velocity[i] for i in range(2)) / max(1, speed2)
                if 0 < t < .6:
                    gap = math.hypot(*(rel[i] + velocity[i]*t for i in range(2)))
                    pz = projectile['pos'][2] + projectile['vel'][2]*t
                    if gap < stats['radius'] + 2 and pos[2] <= pz <= pos[2] + stats['height']:
                        score -= (stats['radius'] + 2 - gap) * .35
            candidates.append((score, d))
        action['move'] = list(max(candidates, key=lambda p:p[0])[1]) if candidates else list(direction)
        if direction == (0, 0):
            action['move'] = [0, 0]
        if self.previous is not None and math.dist(pos, self.previous) < .12 and direction != (0, 0):
            self.stuck += 1
        else:
            self.stuck = 0
        self.previous = list(pos)
        if self.progress_pos is None or direction == (0, 0):
            self.progress_pos, self.progress_at = list(pos), now
        elif now - self.progress_at >= 3:
            if math.dist(pos, self.progress_pos) < 4 and me['grounded'] and me['energy'] > 35:
                # Oscillating at a corner is movement but not route progress.
                # Escape vertically before the shrinking zone makes it fatal.
                action['jump'] = True
                self.jet_until = now + 4
                self.navigator.route_after = -1
            self.progress_pos, self.progress_at = list(pos), now
        if (self.stuck > 10 or not candidates) and me['grounded'] and me['energy'] > 60:
            action['jump'] = True
            self.jet_until = now + 4
        nearest = min((math.dist(pos, e['pos']) for e in enemies), default=1e9)
        danger = not me['in_zone'] or me['hp'] < me['max_hp'] * .55 or ('laser' in kinds and nearest < 65)
        if self.boosting:
            self.boosting = danger and me['energy'] > 20
        else:
            self.boosting = danger and me['energy'] > 65
        action['boost'] = bool(self.boosting or (now < self.jet_until and me['energy'] > 10))


if __name__ == '__main__':
    mf.run(Combat)
