"""Experimental rooftop-survival candidate; compare with baseline in practice."""
from array import array
import math
from pathlib import Path
import sys

from bot import Arena, Bot, inside, unit
import mechfight as mf


class TerrainArena(Arena):
    def __init__(self, directory):
        super().__init__(directory)
        import json
        world = json.loads((Path(directory) / 'v2/world.json').read_text())
        self.terrain = world['terrain']
        self.heights = array('h')
        self.heights.frombytes((Path(directory) / 'v2/terrain.i16').read_bytes())
        if sys.byteorder != 'little':
            self.heights.byteswap()
        # Spatial bins keep movement and visibility queries within the tick budget.
        self.bins = {}
        for prism in self.prisms:
            x0, y0, x1, y1, _ = prism
            for ix in range(math.floor(x0 / 32), math.floor(x1 / 32) + 1):
                for iy in range(math.floor(y0 / 32), math.floor(y1 / 32) + 1):
                    self.bins.setdefault((ix, iy), []).append(prism)
        self.roofs = []
        for x0, y0, x1, y1, p in self.prisms:
            if p['kind'] != 'building' or x1 - x0 < 15 or y1 - y0 < 15:
                continue
            # Sample genuinely interior roof points, rather than polygon centroids
            # which may be outside an L-shaped building or inside a courtyard.
            for x in range(math.ceil((x0 + 6) / 12) * 12, math.floor(x1 - 6) + 1, 12):
                for y in range(math.ceil((y0 + 6) / 12) * 12, math.floor(y1 - 6) + 1, 12):
                    if not all(inside(x + dx, y + dy, p['ring']) and not any(inside(x + dx, y + dy, h) for h in p['holes'])
                               for dx, dy in ((0, 0), (6, 0), (-6, 0), (0, 6), (0, -6))):
                        continue
                    elevation = p['top'] - self.ground(x, y)
                    if 9 <= elevation <= 42 and not self.solid(x, y, p['top'] + 0.1, p['top'] + 10):
                        self.roofs.append((x, y, p['top'], elevation))

    def ground(self, x, y):
        t = self.terrain
        fx = max(0, min(t['nx'] - 1.000001, (x - t['minX']) / t['step']))
        fy = max(0, min(t['ny'] - 1.000001, (y - t['minY']) / t['step']))
        ix, iy = int(fx), int(fy)
        ax, ay = fx - ix, fy - iy
        k = iy * t['nx'] + ix
        h = self.heights
        return ((h[k] * (1 - ax) + h[k + 1] * ax) * (1 - ay) +
                (h[k + t['nx']] * (1 - ax) + h[k + t['nx'] + 1] * ax) * ay) * t.get('scale', 0.01)

    def solid(self, x, y, low, high):
        for x0, y0, x1, y1, p in self.bins.get((math.floor(x / 32), math.floor(y / 32)), []):
            if x0 <= x <= x1 and y0 <= y <= y1 and p['base'] < high and p['top'] > low:
                if inside(x, y, p['ring']) and not any(inside(x, y, h) for h in p['holes']):
                    return True
        return False

    def clear_shot(self, a, b):
        n = max(1, math.ceil(math.dist(a, b) / 2))
        for i in range(1, n):
            p = [a[k] + (b[k] - a[k]) * i / n for k in range(3)]
            if p[2] < self.ground(p[0], p[1]) or self.solid(p[0], p[1], p[2] - 0.01, p[2] + 0.01):
                return False
        return True

    def clear_move(self, pos, direction, stats):
        # Inspect the next few decisions, not a 12 m ray extending beyond the
        # destination. The longer ray stranded mechs beside loot near walls.
        radius, height = stats['radius'], stats['height']
        for distance in (1.5, 3):
            x, y = pos[0] + direction[0] * distance, pos[1] + direction[1] * distance
            b = self.bounds
            if not (b['minX'] + radius < x < b['maxX'] - radius and b['minY'] + radius < y < b['maxY'] - radius):
                return False
            ground = self.ground(x, y)
            if ground - pos[2] > distance * math.tan(math.radians(stats.get('max_slope_deg', 50))) + stats['step_up']:
                return False
            feet = max(pos[2], ground)
            for dx, dy in ((0, 0), (radius, 0), (-radius, 0), (0, radius), (0, -radius)):
                if self.solid(x + dx, y + dy, feet + stats['step_up'], feet + height):
                    return False
        return True


class Survivor(Bot):
    name = 'Oval-Sentinel-rooftop-v2'

    def __init__(self, hello):
        super().__init__(hello)
        self.arena = TerrainArena(hello['map']['dir'])
        self.roof = None
        self.select_after = -1
        self.climb_until = -1
        self.last_hurt = -100
        self.last_damage = -100

    def select_roof(self, obs):
        me, zone = obs['self'], obs['zone']
        pos = me['pos']
        radius = max(0, zone['next_radius'] - 18)
        options = []
        for roof in self.arena.roofs:
            to_ring_center = math.dist(roof[:2], zone['next_center'])
            if to_ring_center > radius:
                continue
            distance = math.dist(pos[:2], roof[:2])
            if distance > 230:
                continue
            # Prefer nearby high ground in the next circle. Hysteresis avoids
            # oscillating between almost-equivalent roof points each decision.
            score = roof[3] * 2 - distance * 0.38 - to_ring_center * 0.1
            if self.roof and math.dist(roof[:3], self.roof[:3]) < 1:
                score += 30
            for enemy in obs['mechs']:
                d = math.dist(roof[:3], enemy['pos'])
                if d < 65 and enemy['pos'][2] >= roof[2] - 10:
                    score -= (65 - d) * 1.5
            options.append((score, roof))
        self.roof = max(options, key=lambda pair: pair[0])[1] if options else None
        self.select_after = obs['t'] + 4

    def act(self, obs):
        action = super().act(obs)
        me, zone, now = obs['self'], obs['zone'], obs['t']
        pos, stats = me['pos'], me['stats']
        for event in obs['events']:
            if event['type'] == 'damaged':
                self.last_hurt = now
            elif event['type'] == 'hit':
                self.last_damage = now
        if now >= self.select_after:
            self.select_roof(obs)
        enemies = [m for m in obs['mechs'] if m['kind'] == 'mech']
        nearest = min((math.dist(pos, e['pos']) for e in enemies), default=1e9)
        healing = me['hp'] < me['max_hp'] * 0.8
        # Damage dealt also resets regeneration. Stop shooting while recovering
        # unless a close attacker makes disengagement implausible.
        if healing and nearest > 65:
            action['fire'] = [False, False]

        if zone['next_radius'] <= 35:
            # The late circle makes staying on a remote roof fatal. Prioritize
            # its exact center, including when enemies would pull v1 sideways.
            center = zone['next_center']
            direction = unit(center[0] - pos[0], center[1] - pos[1])
            if math.dist(pos[:2], center) > max(2, zone['next_radius'] * 0.4):
                self.navigate(action, pos, direction, me, zone, now)
            elif nearest > 35:
                action.update(move=[0, 0], boost=False, jump=False)
            return action

        roof = self.roof
        if roof is None:
            return action
        distance = math.dist(pos[:2], roof[:2])
        vertical = roof[2] - pos[2]
        direction = unit(roof[0] - pos[0], roof[1] - pos[1])
        if abs(vertical) < 1.5 and distance < 6:
            # Standing well inside the roof breaks most ground-level sightlines.
            action.update(move=[0, 0], jump=False, boost=False)
            if healing or now - self.last_hurt > 3:
                action['fire'] = [False, False]
            return action
        if distance < 55 and vertical > 1.5:
            estimated_energy = max(0, vertical) * stats['jet_drain'] / max(1, stats['max_rise_speed']) + 16
            if me['grounded'] and me['energy'] >= min(me['max_energy'] * 0.9, estimated_energy):
                self.climb_until = now + min(8, vertical / max(1, stats['max_rise_speed']) + 3)
                action['jump'] = True
            if now < self.climb_until and me['energy'] > 5:
                action['boost'] = True
                action['move'] = list(direction)
                action['fire'] = [False, False] if healing else action['fire']
                return action
        self.navigate(action, pos, direction, me, zone, now)
        return action

    def navigate(self, action, pos, direction, me, zone, now):
        yaw = math.atan2(direction[1], direction[0])
        options = []
        for offset in (0, 0.4, -0.4, 0.8, -0.8, 1.3, -1.3, 1.8, -1.8, 2.5, -2.5, math.pi):
            d = (math.cos(yaw + offset), math.sin(yaw + offset))
            if self.arena.clear_move(pos, d, me['stats']):
                future = [pos[0] + d[0] * 12, pos[1] + d[1] * 12]
                penalty = max(0, math.dist(future, zone['center']) - max(0, zone['radius'] - 5))
                options.append((math.cos(offset) - penalty, d))
        action['move'] = list(max(options, key=lambda p: p[0])[1]) if options else list(direction)
        if self.stuck > 8 or not options:
            action['jump'] = bool(me['grounded'] and me['energy'] > 50)
            if action['jump']:
                self.climb_until = now + 5
        action['boost'] = bool(me['energy'] > 10 and (now < self.climb_until or (not me['in_zone'] and me['grounded'])))


if __name__ == '__main__':
    mf.run(Survivor)
