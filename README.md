# Mech Royale — Oval Sentinel

Python entry for the 2026 Builders Buildathon Mech Royale track. The root
Dockerfile runs `combat.py`; there are no third-party runtime dependencies.

## Verified submission

The selected entry scores **5.85** in official practice (48 matches).

- Receipt: `BB-7097A598`
- Scored commit: `2054a5bb27fdd36c8b8f63eebddbcf145737694e`
- Repository: https://github.com/JishnuMadav/mech-royale
- Track: https://www.joinbuilders.org/buildathon/tracks/builders

The development target is **strictly greater than 6.31**. It has not yet been
reached. The site retains the best scored entry while experimental branches
are evaluated. Private free-for-all games are diagnostics, not practice scores.

## Selected recovery strategy v26 (5.85)

This branch starts from the selected 5.81 runtime, not the 5.48 squad/zone
experiment. It starts cover recovery strictly below 25% health and finishes
recovery at 60%, retains occupied shelter when enemies cannot see the bot,
and does not start laser charges outside the zone. An already charged laser
is aimed and released so charging does not keep halving escape speed.

Zone departure uses obstacle-route distance with the selected runtime's walk
speed and eight-second margin. Urgent escape takes priority over supply capture.
The failed experiment's 85% cover trigger and broad sightline movement penalty
are absent. The selected 90 m laser preference and weapon upgrades are retained.

Validation on 2026-11-22:

- All 13 tests pass: `python -m unittest -v test_bot.py test_recovery.py`.
- VM restricted Docker: official stream 300/300, maximum 15.2 ms; private replay
  interval 300/300, maximum 24.8 ms. Both are below the 50 ms response budget.
- The same replay on the local host had one late response (maximum 72.0 ms),
  despite passing the checker's allowed tolerance. The VM result above is a
  separate verification, not a reason to omit that local result.
- Direct comparisons cover 2,792 recorded observations. On the zone-loss trace,
  laser-hold commands outside the zone fell from 58 to zero; zone urgency began
  earlier on 190 observations. This is a decision comparison, not a match simulation.
- One fresh private FFA game: place 1, two kills, five final cubes, no zone damage.
  The baseline's separate random game ended in third place. One unpaired game
  per bot does not establish an improvement in official practice score.

The audit covered all 13 locally saved private traces and the 19 recorded official
results. Official per-match replays are not available in these records, so the
causes of the 5.48 result remain hypotheses. Official practice scored this revision
**5.85** on 2026-11-22, improving the selected score by 0.04. The target remains unmet.

## Strategy

- Acquire a second weapon early, favoring lasers, and collect nearby power cubes.
- Aim the gun with projectile lead, release laser beams at full charge, and use
  ballistic trajectories for mortar shots.
- Maintain weapon-appropriate distance and face incoming fire to protect rear armor.
- Seek reachable cover when wounded; collect uncontested supply drops for repair.
- Plan ground routes around buildings and leave a travel-time margin for the zone.
- Manage ammunition and energy, and use jets to escape corners when progress stalls.

The laser release logic tolerates the observation's two-decimal charge rounding:
a reported charge of `0.56` can represent the full upgraded duration `0.563`.
Without this tolerance, the beam can remain held until its automatic timeout.
The selected version also releases a partial beam when its conservative damage
estimate exceeds the target's HP, allowing for maximum armor and an HP margin.

`bot.py` provides geometry helpers; `survivor.py` provides indexed terrain;
`navigation.py` provides bounded ground routing and cover search. Their earlier
standalone strategies remain available for comparison. `combat.py` is the
submission entrypoint.

## Validation

Run from this directory with Python 3.12+ and Docker:

```sh
python3 setup_kit.py
python3 -m unittest -v test_bot.py
docker build --platform linux/amd64 -t mech-royale:local .
python3 mechfight-kit/check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --memory-swap 512m --pids-limit 128 --cap-drop ALL --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/mechfight-kit/arena:/arena:ro" mech-royale:local
```

The selected runtime passed two VM checks under these container restrictions:
**600/600 observations**, no missed deadlines, maximum response **24.8 ms**
against a 50 ms budget. The local-host replay timing caveat is recorded above. Regression checks cover geometry, aiming,
laser charge release, navigation, and decision handling. The checker validates
protocol and timing; it does not simulate matches or establish playing strength.

## Scored experiments

| Variant | Score | Receipt |
| --- | ---: | --- |
| Baseline | 1.29 | BB-C2349777 |
| Rooftop movement | 0.44 | BB-D8559723 |
| Combat | 3.67 | BB-9D2EC473 |
| Sustain | 3.67 | BB-AA2FFC04 |
| Skirmish and loot | 5.10 | BB-B3606475 |
| Supply capture and escape | 5.46 | BB-D98A5863 |
| Laser charge rounding fix | 5.73 | BB-DF9C6D15 |
| More aggressive growth | 5.67 | BB-AA121873 |
| Faster evasion | 5.17 | BB-5D04F286 |
| Laser retreat from lightning | 5.71 | BB-444A6149 |
| Armor and magazine priorities | 5.71 | BB-6683FFC3 |
| Wider laser spacing | 5.65 | BB-093E79FF |
| Terrain-aware loot | 5.67 | BB-0E14E4C3 |
| Early lethal laser releases | 5.81 | BB-19EDB71A |
| Beam warning dodge | 5.65 | BB-A61CC6BF |
| Projectile physics | 5.31 | BB-3CF94DAD |
| Weaker-target focus | 5.21 | BB-7F41D080 |
| Repair upgrades | 5.65 | BB-5D14A8D0 |
| Earlier squad cover and zone travel | 5.48 | BB-76ECA895 |
| Critical-health recovery and zone escape | **5.85** | **BB-7097A598** |

Results above were observed on 2026-11-21 and 2026-11-22. Each experimental commit is retained
on its `codex/` branch; the selected scored commit is immutable.
Exact commits and receipts are recorded in [results.json](results.json).

## Submission and attribution

Submit the public repository URL with an explicit 40-character commit on the
track page. Keep the Dockerfile at the root, the submitted tree below 20 MB,
and the repository public until results are published. Practice allows four
submissions per rolling hour.

`mechfight.py` is the organizer-provided Python protocol wrapper. `setup_kit.py`
downloads the pinned official kit into an ignored directory for local checks;
the scorer supplies the map at runtime. The implementation uses the documented
observations and public starter kit, with no external runtime libraries.

Project code is released under the MIT License.

