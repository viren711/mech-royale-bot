"""Placement-oriented first entry. Standard library only; all decisions are local."""
import json
import math
from pathlib import Path

import mechfight as mf


def unit(x, y):
    d = math.hypot(x, y)
    return (x / d, y / d) if d > 1e-9 else (0.0, 0.0)


def angle_delta(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def inside(x, y, ring):
    result = False
    j = len(ring) - 2
    for i in range(0, len(ring), 2):
        ax, ay, bx, by = ring[i], ring[i + 1], ring[j], ring[j + 1]
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            result = not result
        j = i
    return result


def lead(origin, target, speed):
    """Constant-velocity intercept; projectile velocity is world-relative."""
    r = [target['pos'][i] - origin[i] for i in range(3)]
    v = target.get('vel', [0, 0, 0])
    a = sum(q * q for q in v) - speed * speed
    b = 2 * sum(r[i] * v[i] for i in range(3))
    c = sum(q * q for q in r)
    disc = b * b - 4 * a * c
    roots = []
    if abs(a) > 1e-9 and disc >= 0:
        roots = [(-b - math.sqrt(disc)) / (2 * a), (-b + math.sqrt(disc)) / (2 * a)]
    elif abs(b) > 1e-9:
        roots = [-c / b]
    t = min((q for q in roots if q >= 0), default=0)
    return [target['pos'][i] + v[i] * min(t, 2) for i in range(3)]


class Arena:
    def __init__(self, directory):
        world = json.loads((Path(directory) / 'v2/world.json').read_text())
        self.bounds = world['bounds']
        self.prisms = []
        for p in world['prisms']:
            ring = p['ring']
            self.prisms.append((min(ring[::2]), min(ring[1::2]), max(ring[::2]), max(ring[1::2]), p))

    def solid(self, x, y, low, high):
        for x0, y0, x1, y1, p in self.prisms:
            if x0 <= x <= x1 and y0 <= y <= y1 and p['base'] < high and p['top'] > low:
                if inside(x, y, p['ring']) and not any(inside(x, y, h) for h in p['holes']):
                    return True
        return False

    def clear_move(self, pos, direction, stats):
        radius, height = stats['radius'], stats['height']
        for d in (3, 7, 12):
            x, y = pos[0] + direction[0] * d, pos[1] + direction[1] * d
            b = self.bounds
            if not (b['minX'] + radius < x < b['maxX'] - radius and b['minY'] + radius < y < b['maxY'] - radius):
                return False
            for dx, dy in ((0, 0), (radius, 0), (-radius, 0), (0, radius), (0, -radius)):
                if self.solid(x + dx, y + dy, pos[2] + stats['step_up'], pos[2] + height):
                    return False
        return True

    def clear_shot(self, a, b):
        # Conservative sampled prism check, including tracked enemies behind cover.
        n = max(1, math.ceil(math.dist(a, b) / 3))
        for i in range(1, n):
            p = [a[k] + (b[k] - a[k]) * i / n for k in range(3)]
            if self.solid(p[0], p[1], p[2] - 0.01, p[2] + 0.01):
                return False
        return True


class Bot:
    name = 'Oval-Sentinel-v1'

    def __init__(self, hello):
        self.config = hello['config']
        self.arena = Arena(hello['map']['dir'])
        self.side = 1 if hello['slot'] % 2 else -1
        self.previous = None
        self.stuck = 0
        self.boosting = False

    def act(self, obs):
        me, zone = obs['self'], obs['zone']
        pos, stats = me['pos'], me['stats']
        x, y, z = pos
        hp_ratio = me['hp'] / max(1, me['max_hp'])
        enemies = sorted((m for m in obs['mechs'] if m['kind'] == 'mech'), key=lambda m: math.dist(pos, m['pos']))
        nearest = math.dist(pos, enemies[0]['pos']) if enemies else 1e9
        healing = hp_ratio < 0.55
        action = {'tick': obs['tick'], 'fire': [False, False]}
        if obs['offer']:
            ranks = {'nanites': 100, 'servos': 95, 'armor': 90, 'plating': 85, 'jets': 80, 'reactor': 75, 'gun_damage': 70, 'gun_rate': 65, 'gun_mag': 60, 'capacitor': 55}
            action['pick'] = max(range(len(obs['offer']['choices'])), key=lambda i: ranks.get(obs['offer']['choices'][i]['id'], 20))

        # Move early enough to reach the next circle, while allowing nearby loot.
        center = zone['next_center']
        dist_next = math.dist(pos[:2], center)
        travel = max(0, dist_next - zone['next_radius'] + 18) / stats['walk_speed']
        urgent = not me['in_zone'] or obs['t'] + travel + 12 > zone['shrink_start']
        goal = center if urgent else zone['center']
        loot = [(math.dist(pos, c['pos']), c) for c in obs['cubes']]
        if me['weapons'][1] is None:
            loot += [(math.dist(pos, p['pos']), p) for p in obs['pickups'] if p['kind'] == 'lightning']
        if not urgent and nearest > 65 and loot:
            distance, item = min(loot, key=lambda pair: pair[0])
            if distance < 65 and abs(item['pos'][2] - z) < 4:
                goal = item['pos'][:2]
        for p in obs['pickups']:
            if p['kind'] == 'lightning' and me['weapons'][1] is None and math.dist(pos[:2], p['pos'][:2]) <= self.config['loot']['pickup_radius'] and abs(p['pos'][2] - z) <= 4:
                action['take'] = p['id']
                break

        gx, gy = unit(goal[0] - x, goal[1] - y)
        if enemies and me['in_zone']:
            ex, ey = unit(enemies[0]['pos'][0] - x, enemies[0]['pos'][1] - y)
            retreat = 2.6 if healing or len(enemies) >= 3 else max(-0.3, min(1.8, (85 - nearest) / 35))
            gx, gy = unit(gx * (1.6 if urgent else 0.4) - ex * retreat - ey * self.side,
                          gy * (1.6 if urgent else 0.4) - ey * retreat + ex * self.side)
        base_angle = math.atan2(gy, gx)
        candidates = []
        for offset in (0, 0.4, -0.4, 0.8, -0.8, 1.3, -1.3, 1.9, -1.9, math.pi):
            direction = (math.cos(base_angle + offset), math.sin(base_angle + offset))
            if self.arena.clear_move(pos, direction, stats):
                future = (x + direction[0] * 12, y + direction[1] * 12)
                outside = max(0, math.dist(future, zone['center']) - max(0, zone['radius'] - 8))
                candidates.append((math.cos(offset) - outside * 0.15, direction))
        action['move'] = list(max(candidates, key=lambda c: c[0])[1]) if candidates else [gx, gy]
        if self.previous is not None and math.dist(pos, self.previous) < 0.15:
            self.stuck += 1
        else:
            self.stuck = 0
        self.previous = list(pos)
        action['jump'] = bool(me['grounded'] and (not candidates or self.stuck > 8) and me['energy'] > 30)
        need_boost = urgent or nearest < 60 or not candidates
        if self.boosting:
            self.boosting = need_boost and me['energy'] > 20
        else:
            self.boosting = need_boost and me['energy'] > 65
        action['boost'] = self.boosting
        action['aim'] = [me['aim'][0] + 0.25, 0.0]

        origin = [x, y, z + stats['muzzle_height']]
        targets = list(enemies)
        if not enemies and not healing:
            targets += [dict(c, kind='crate', vel=[0, 0, 0]) for c in obs['crates'] if math.dist(pos, c['pos']) < 65]
        gun = me['weapons'][0]
        for target in targets:
            height = 4.5 * (1 + 0.05 * target.get('cubes', 0)) if target['kind'] == 'mech' else 1.0
            center_target = dict(target, pos=[*target['pos'][:2], target['pos'][2] + height])
            speed = gun['stats']['speed'] if gun and gun['kind'] == 'gun' else 252
            point = lead(origin, center_target, speed)
            dx, dy, dz = [point[i] - origin[i] for i in range(3)]
            yaw, pitch = math.atan2(dy, dx), math.atan2(dz, math.hypot(dx, dy))
            action['aim'] = [yaw, pitch]
            distance = math.dist(origin, point)
            if not self.arena.clear_shot(origin, point):
                continue
            aligned = abs(angle_delta(yaw, me['aim'][0])) < max(0.025, math.atan2(2.5, distance)) and abs(pitch - me['aim'][1]) < max(0.025, math.atan2(3, distance))
            fight = not healing or distance < 45 or target.get('hp', 1400) < 150
            if gun and gun['kind'] == 'gun':
                action['fire'][0] = bool(aligned and fight and distance < gun['stats']['range'] and gun.get('ammo', 0) > 0)
            second = me['weapons'][1]
            if second and second['kind'] == 'lightning':
                action['fire'][1] = bool(fight and distance < second['stats']['range'] and me['energy'] > 20 and abs(angle_delta(yaw, me['aim'][0])) < math.radians(second['stats']['cone_deg']) * 0.8)
            break
        if gun and gun['kind'] == 'gun':
            action['reload'] = bool(gun.get('ammo', 0) == 0 or (not targets and gun.get('ammo', 0) < gun['stats']['mag'] * 0.7))
        return action


if __name__ == '__main__':
    mf.run(Bot)
