# Hackermen mech bot (mechfight/1)

Team Hackermen's entry for Builders Buildathon "Mech Royale". Python standard library only.

| File | Role |
| --- | --- |
| `bot.py` | `Duelist`: the decision layer for practice (house squad) matches |
| `base.py` | the survivor bot (map model use, pathing, cover search, aim and fire control, loot memory, zone timing); also the free-for-all fallback |
| `world.py` | static map model built at `hello` from `/arena` (2 m grid: floor, walls, line of sight, canopy) and incremental A* |
| `mechfight.py` | the kit's wrapper, unchanged |

## How it plays

Practice matches pit us against 15 house bots that never hurt each other, so every point is a
house bot that dies before us. The duelist takes fights and tries to make each one lopsided:

- fight at the range our loadout wins (lightning ~28 m, laser ~125 m, gun ~75 m) and strafe with
  random flips; boost sideways when a laser is charging at us;
- one target at a time: attackers first, then weak and close ones, sticky for 2 s; finish low targets;
- back off to cover only when losing (HP < 35% and behind, < 55% vs two shooters, < 80% vs three),
  then heal to 90% before the next fight;
- laser > lightning > mortar; grab close cubes and better weapons even mid-fight; farm drones and
  crates when healthy; plating, armor and nanites first;
- full-speed movement; zone rotation timed on the remaining distance.

When the bot sees a mech take damage it did not deal (a free-for-all), it switches to the
survival-first base behaviour: hide, heal, and only finish weakened enemies.

## Check it

```sh
docker build -t hackermen-mech .
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m \
  --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" hackermen-mech
```

MIT licensed (see `LICENSE`).
