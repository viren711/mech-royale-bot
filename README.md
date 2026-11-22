# Team Inventors — Mech Royale bot

Entry for the Builders Buildathon "Mech Royale" track (protocol `mechfight/1`, scorer `builders-3`).
Python 3.13, standard library only. Started from the kit's Python starter.

| File | What it is |
| --- | --- |
| `Dockerfile` | The image the scorer builds. Base image pinned by digest; nothing else is downloaded. |
| `bot.py` | The bot: targeting, firing, fight / retreat / loot / zone decisions. |
| `world.py` | Map model from `/arena`: walk and sight grids, line checks, time-sliced A*. |
| `mechfight.py` | The kit's wrapper, unchanged (stdin/stdout loop, newest-observation rule). |
| `tools/` | Dev-only helpers (not in the image): `mapcheck.py`, `sim.py`. |

## How it plays (submitted version)

Legs and torso are decided separately each observation. Behaviour switches are constants at the top of
`bot.py`; the defaults are the combination that scored best.

- **Zone:** heads for the next circle early enough to be inside before each shrink; boosts if outside.
- **Navigation:** buildings, the stadium, low bridges and steep terrain are rasterised to a 2 m grid;
  paths are A* on a 4 m grid, run in small slices so no decision is slow. Jumps/jets when stuck.
- **Fighting:** never retreats. Holds about 110 m from the target, strafing with random flips; leads
  the gun, charges and releases the laser on target, arcs lightning, lobs the mortar. Shoots the enemy
  it can finish soonest.
- **Loot:** fetches a better second weapon (laser > lightning > mortar) within 110 m even mid-fight,
  grabs nearby cubes, takes supply drops without waiting under them or circling in a contested ring.
  Upgrades: laser damage and charge first when holding a laser, then HP and armor.

## Checks run (2026-11-21, kit `mechfight-kit.tar.gz`)

Run from the kit folder, with this repository at `../mech-royale`.

| Command | Result |
| --- | --- |
| `python3 check/check.py -- python3 -u python/example_bot.py` (unmodified starter) | PASS, 300/300 in time, max 0.8 ms |
| starter image under the match limits (command below with `starter-bot`) | PASS, 300/300, max 2.8 ms |
| `python3 check/check.py -- python3 -u ../mech-royale/bot.py` | PASS, 300/300, p50 0.3 / p99 2.8 / max 3.0 ms |
| `docker build --platform linux/amd64 -t inventors-bot ../mech-royale` | builds in seconds, amd64 |
| `python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 --pids-limit 128 -v "$PWD/arena:/arena:ro" inventors-bot` (3 runs) | PASS ×3, 300/300 in time, ready in ~0.45 s, p50 0.6–0.7 / p99 3.6–4.9 / max 4.4–6.9 ms |
| `tools/sim.py` in a `--cpus 1 --memory 512m --read-only --user 65534` container, 5 full sandbox matches | 0 exceptions, per decision p50 0.05 / p99 ≤ 3.0 / max 4.8 ms |

Budget is 50 ms per decision, so the worst measured answer uses about 14% of it.

## Practice results (48 matches each, scorer builders-3, starter baseline 1.15)

Each row changes one thing from the row it builds on. One run wobbles by a few tenths, so only
differences of about 0.3 or more mean much.

| Version | Score |
| --- | --- |
| First version | 4.35 |
| + focus weakest target, cubes mid-fight, supply drops | 4.48 |
| Never hides (diagnostic) | 0.13 |
| Never retreats | 4.67 |
| + fight at 35 m / 110 m / 150 m / 80 m | 4.67 / **4.90** / 4.50 / 4.65 |
| + pursue lost enemies | 4.71 |
| + fetch a better weapon mid-fight (110 m) | **5.15** |
| + fetch from 200 m / farm when hurt / cube-greedy | 4.94 / not run / 5.13 |
| + faster dodge rhythm / + current-velocity aim | 4.81 / 5.15 (both) |
| + collect kill drops / corner fighting | 5.06 / 5.13 |
| + smart supply drops | **5.23** |
| + zone escape (with and without aim change) | 4.88 |
| + seek enemies by sound | 4.86 |
| + laser upgrades first | **5.25** (entry: `ad1d5a6`) |
| + rest out of sight between fights / + also break off losing fights | 5.06 / 4.71 |
| Diagnostics: stop at 90 s / 180 s / hide for the first 120 s | 3.06 / 5.02 / 4.50 |
| + ideas from Team Kanyaraasi's public bot (written independently): all five / engage gate + finish fast / engage gate only | 4.88 / 5.19 / 5.13 |
| + dodge charging lasers / + also shoot laser carriers first | 5.21 / 4.79 |

What the diagnostics say: the score is close to the number of kills (house bots only die to us).
About 3 kills come by 90 s and 5 by 180 s, then almost none. Starting two minutes late still gives
about 4.5 kills, so the wall follows the kill count, not the clock: the squad sends more hunters as it
is thinned out, and this bot does not survive that. Healing, hiding, cover, retreating, only fighting
hunters that are already engaging, and dodging charging lasers (which did about 3/4 of the damage in
the kit's recorded match) did not measurably help.

## Limitations

- **Placement is unmeasured.** The kit has no match runner. `tools/sim.py` is a home-made sandbox
  with invented physics and opponents; it only catches crashes, navigation dead-ends and slow
  decisions. Real placement needs an official practice submission.
- Everything is 2D: it does not climb roofs on purpose and skips rooftop loot.
- Line of sight ignores trees and low walls; canopy is not modelled.
- Sounds and beams are not used; unseen attackers are only noticed through damage bearings.
- Practice is against a house squad; the qualifying round and final are free-for-alls against other
  teams' bots, which this tuning has never seen.

## License

MIT, see `LICENSE`.
