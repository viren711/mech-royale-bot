"""Regression checks for critical-health recovery and zone escape conflicts."""
import copy
import gzip
import json
from pathlib import Path
import unittest

from combat import Combat
from navigation import Navigator

ROOT = Path(__file__).resolve().parent


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        records = [json.loads(line) for line in gzip.open(ROOT / 'mechfight-kit/check/stream.jsonl.gz', 'rt')]
        cls.hello = next(r for r in records if r['type'] == 'hello')
        cls.hello['map']['dir'] = str(ROOT / 'mechfight-kit/arena')
        cls.observation = next(r for r in records if r['type'] == 'obs')

    def scenario(self):
        bot = Combat(self.hello)
        obs = copy.deepcopy(self.observation)
        pos = obs['self']['pos']
        obs['self'].update(hp=obs['self']['max_hp'], in_zone=True, aim=[0, 0])
        for key in ('mechs', 'pickups', 'cubes', 'crates', 'drops', 'projectiles', 'events'):
            obs[key] = []
        obs['offer'] = None
        obs['zone'].update(center=pos[:2], next_center=pos[:2], radius=250, next_radius=200, shrink_end=obs['t'] + 100)
        bot.arena.clear_move = lambda *args: True
        bot.navigator.waypoint = lambda pos, goal, now: goal
        return bot, obs

    def test_recovery_starts_strictly_below_25_and_finishes_at_60(self):
        bot, _ = self.scenario()
        for hp in (.85, .59, .26, .25):
            bot.update_recovery(hp)
            self.assertFalse(bot.healing)
        bot.update_recovery(.249)
        self.assertTrue(bot.healing)
        bot.update_recovery(.3)
        self.assertTrue(bot.healing)
        bot.update_recovery(.6)
        self.assertFalse(bot.healing)

    def test_does_not_seek_cover_at_half_health_when_outnumbered(self):
        bot, obs = self.scenario()
        pos = obs['self']['pos']
        obs['self']['hp'] *= .5
        obs['mechs'] = [dict(id=i + 20, kind='mech', hp=1400, cubes=0,
                             pos=[pos[0] + 80, pos[1] + i * 10, pos[2]]) for i in range(2)]
        def unexpected_cover(*args):
            self.fail('Cover search must not trigger at half health')
        bot.navigator.cover = unexpected_cover
        bot.act(obs)
        self.assertFalse(bot.healing)

    def test_keeps_safe_shelter_instead_of_relocating(self):
        bot, obs = self.scenario()
        pos = obs['self']['pos']
        obs['self']['hp'] *= .2
        obs['mechs'] = [dict(id=99, kind='mech', hp=1400, cubes=0,
                             pos=[pos[0] + 100, pos[1], pos[2]])]
        bot.cover_goal = list(pos)
        bot.arena.clear_shot = lambda *args: False
        def unexpected_cover(*args):
            self.fail('A safe occupied shelter should be retained')
        bot.navigator.cover = unexpected_cover
        action = bot.act(obs)
        self.assertEqual(bot.cover_goal, pos)
        self.assertEqual(action['move'], [0, 0])
        self.assertEqual(action['fire'], [False, False])

    def test_zone_escape_stops_new_laser_charge_and_releases_existing(self):
        bot, obs = self.scenario()
        pos = obs['self']['pos']
        obs['mechs'] = [dict(id=99, kind='mech', hp=1400, cubes=0,
                             pos=[pos[0] + 80, pos[1], pos[2]], vel=[0, 0, 0])]
        obs['self']['weapons'][1] = dict(kind='laser', cooldown=0, charge=0,
                                       stats=self.hello['config']['weapons']['laser'])
        bot.arena.clear_shot = lambda *args: True
        obs['self']['in_zone'] = False
        self.assertFalse(bot.act(obs)['fire'][1])
        obs['self']['weapons'][1]['charge'] = .2
        action = bot.act(obs)
        self.assertFalse(action['fire'][1])
        self.assertAlmostEqual(action['aim'][0], 0)
        obs['self']['in_zone'] = True
        obs['self']['weapons'][1]['charge'] = 0
        self.assertTrue(bot.act(obs)['fire'][1])

    def test_zone_escape_does_not_stop_to_capture_supply(self):
        bot, obs = self.scenario()
        pos = obs['self']['pos']
        obs['self'].update(in_zone=False, hp=obs['self']['max_hp'] * .2)
        obs['zone'].update(center=[pos[0] + 50, pos[1]], next_center=[pos[0] + 50, pos[1]], radius=40, next_radius=100)
        obs['drops'] = [dict(id=20000, pos=[pos[0] + 1, pos[1], pos[2]], radius=8,
                             lands_in=0, capture_s=4, progress=1, holder=obs['self']['id'])]
        self.assertGreater(bot.act(obs)['move'][0], .8)

    def test_zone_distance_accounts_for_wall_detour(self):
        class Map:
            bounds = dict(minX=-80, maxX=80, minY=-80, maxY=80)
            def ground(self, x, y):
                return 0
            def solid(self, x, y, low, high):
                return -10 <= x <= 10 and -40 <= y <= 40
        nav = Navigator(Map())
        zone = dict(next_center=[50, 0], next_radius=20)
        self.assertGreater(nav.zone_distance([-50, 0, 0], zone, 0), 120)
        self.assertEqual(nav.zone_distance([50, 0, 0], zone, 1), 0)
        nav.path = lambda *args: []
        self.assertGreaterEqual(nav.zone_distance([-50, 0, 0], zone, 3), 92)


if __name__ == '__main__':
    unittest.main()
