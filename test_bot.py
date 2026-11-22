"""Regression checks for interception and every official recorded observation."""
import gzip
import json
import math
from pathlib import Path
import unittest

from bot import Bot, inside, lead
from survivor import Survivor, TerrainArena
from combat import Combat
from navigation import Navigator


ROOT = Path(__file__).resolve().parent


class BotTests(unittest.TestCase):
    def test_can_approach_loot_before_wall(self):
        class Map:
            bounds = {'minX': -60, 'maxX': 60, 'minY': -60, 'maxY': 60}
            def ground(self, x, y):
                return 0
            def solid(self, x, y, low, high):
                return x >= 10
        stats = {'radius': 2.5, 'height': 9, 'step_up': 1.2}
        self.assertTrue(TerrainArena.clear_move(Map(), [0, 0, 0], (1, 0), stats))
        self.assertFalse(TerrainArena.clear_move(Map(), [6, 0, 0], (1, 0), stats))

    def test_route_around_obstacle(self):
        class Map:
            bounds = {'minX': -60, 'maxX': 60, 'minY': -60, 'maxY': 60}
            def ground(self, x, y):
                return 0
            def solid(self, x, y, low, high):
                return -10 <= x <= 10 and -20 <= y <= 20
        nav = Navigator(Map())
        path = nav.path([-40, 0, 0], [40, 0])
        self.assertTrue(path)
        self.assertEqual(path[-1][:2], (40, 0))
        self.assertGreater(max(abs(p[1]) for p in path), 20)
        for a, b in zip(path, path[1:]):
            for fraction in (.25, .5, .75):
                x, y = (a[i] + fraction * (b[i] - a[i]) for i in range(2))
                self.assertFalse(Map().solid(x, y, 0, 9))

    def test_intercept(self):
        target = {'pos': [100, 0, 0], 'vel': [0, 10, 0]}
        point = lead([0, 0, 0], target, 100)
        travel_time = math.dist([0, 0, 0], point) / 100
        self.assertAlmostEqual(point[1], 10 * travel_time)

    def test_polygon(self):
        ring = [0, 0, 10, 0, 10, 10, 0, 10]
        self.assertTrue(inside(5, 5, ring))
        self.assertFalse(inside(15, 5, ring))

    def test_recording_without_wrapper_fallback(self):
        with gzip.open(ROOT / 'mechfight-kit/check/stream.jsonl.gz', 'rt') as stream:
            messages = [json.loads(line) for line in stream if line.strip()]
        hello = next(m for m in messages if m['type'] == 'hello')
        hello['map']['dir'] = str(ROOT / 'mechfight-kit/arena')
        bot = Bot(hello)
        count = 0
        for obs in messages:
            if obs['type'] != 'obs':
                continue
            action = bot.act(obs)
            json.dumps(action, allow_nan=False)
            self.assertEqual(action['tick'], obs['tick'])
            self.assertLessEqual(math.hypot(*action['move']), 1.000001)
            self.assertEqual(len(action['fire']), 2)
            count += 1
        self.assertGreaterEqual(count, 300)

    def test_survivor_recording_and_final_circle(self):
        with gzip.open(ROOT / 'mechfight-kit/check/stream.jsonl.gz', 'rt') as stream:
            messages = [json.loads(line) for line in stream if line.strip()]
        hello = next(m for m in messages if m['type'] == 'hello')
        hello['map']['dir'] = str(ROOT / 'mechfight-kit/arena')
        bot = Survivor(hello)
        self.assertGreater(len(bot.arena.roofs), 0)
        observations = [m for m in messages if m['type'] == 'obs']
        for obs in observations:
            action = bot.act(obs)
            json.dumps(action, allow_nan=False)
            self.assertLessEqual(math.hypot(*action['move']), 1.000001)
        # At the final center, without a nearby attacker, do not walk back out.
        obs = json.loads(json.dumps(observations[-1]))
        obs['t'] = 414.0
        obs['zone']['next_radius'] = 0
        obs['zone']['next_center'] = obs['self']['pos'][:2]
        obs['mechs'] = []
        action = bot.act(obs)
        self.assertEqual(action['move'], [0, 0])
        self.assertFalse(action['boost'])

    def test_combat_weapon_aim_and_replay(self):
        with gzip.open(ROOT / 'mechfight-kit/check/stream.jsonl.gz', 'rt') as stream:
            messages = [json.loads(line) for line in stream if line.strip()]
        hello = next(m for m in messages if m['type'] == 'hello')
        hello['map']['dir'] = str(ROOT / 'mechfight-kit/arena')
        bot = Combat(hello)
        observations = [m for m in messages if m['type'] == 'obs']
        for obs in observations:
            action = bot.act(obs)
            json.dumps(action, allow_nan=False)
            self.assertEqual(action['tick'], obs['tick'])
            self.assertLessEqual(math.hypot(*action['move']), 1.000001)
        me = observations[0]['self']
        target = {'id': 99, 'kind': 'mech', 'pos': [me['pos'][0] + 80, me['pos'][1], me['pos'][2]], 'vel': [0, 10, 0]}
        gun = {'stats': hello['config']['weapons']['gun']}
        laser = {'stats': hello['config']['weapons']['laser']}
        mortar = {'stats': hello['config']['weapons']['mortar']}
        gun_aim = bot.aim_at(me, target, 'gun', gun)[0]
        laser_aim = bot.aim_at(me, target, 'laser', laser)[0]
        self.assertGreater(gun_aim[0], 0)
        self.assertAlmostEqual(laser_aim[0], 0)
        solution = bot.aim_at(me, target, 'mortar', mortar)
        self.assertIsNotNone(solution)
        self.assertGreater(solution[0][1], gun_aim[1])

        # Lightning must wait through a useful recharge period, rather than
        # repeatedly spending each newly regenerated shot and resetting regen.
        obs = json.loads(json.dumps(observations[0]))
        obs['self']['weapons'][1] = {'kind': 'lightning', 'cooldown': 0, 'stats': hello['config']['weapons']['lightning']}
        pos = obs['self']['pos']
        enemy = {'id': 99, 'kind': 'mech', 'pos': [pos[0] + 15, pos[1], pos[2]], 'vel': [0, 0, 0], 'hp': 1400, 'cubes': 0}
        obs['mechs'] = [enemy]
        obs['self']['aim'] = [0, 0]
        obs['self']['hp'] = obs['self']['max_hp']
        bot.arena.clear_shot = lambda *args: True
        for energy in (10, 30, 60):
            obs['self']['energy'] = energy
            self.assertFalse(bot.act(obs)['fire'][1])
        obs['self']['energy'] = 80
        self.assertTrue(bot.act(obs)['fire'][1])

        # Capture requires uninterrupted residence in the supply ring. Do not
        # strafe out of an uncontested drop while waiting for its repair.
        obs['self']['hp'] = obs['self']['max_hp'] * .5
        obs['mechs'], obs['pickups'], obs['cubes'], obs['crates'] = [], [], [], []
        obs['zone'].update(center=pos[:2], next_center=pos[:2], radius=250, next_radius=200)
        obs['drops'] = [{'id': 20000, 'pos': [pos[0] + 1, pos[1], pos[2]], 'radius': 8,
                         'lands_in': 0, 'capture_s': 4, 'progress': 1, 'holder': obs['self']['id']}]
        self.assertEqual(bot.act(obs)['move'], [0, 0])

        # A full upgraded beam is reported as .56 seconds against a .563-second
        # limit. Release along the laser snapshot, not the moving gun intercept.
        obs['self']['hp'] = obs['self']['max_hp']
        laser_stats = dict(hello['config']['weapons']['laser'], charge=.563)
        obs['self']['weapons'][1] = {'kind': 'laser', 'cooldown': 0, 'charge': .56, 'stats': laser_stats}
        enemy.update(pos=[pos[0] + 80, pos[1], pos[2]], vel=[0, 10, 0])
        obs['mechs'] = [enemy]
        obs['self']['aim'] = [0, 0]
        action = bot.act(obs)
        self.assertFalse(action['fire'][1])
        self.assertAlmostEqual(action['aim'][0], 0)

        # A conservative lethal partial beam should finish the target now,
        # while the same charge must keep building against a healthy mech.
        obs['self']['weapons'][1]['charge'] = .2
        enemy['hp'] = 80
        action = bot.act(obs)
        self.assertFalse(action['fire'][1])
        self.assertAlmostEqual(action['aim'][0], 0)
        enemy['hp'] = 1400
        self.assertTrue(bot.act(obs)['fire'][1])


if __name__ == '__main__':
    unittest.main()
