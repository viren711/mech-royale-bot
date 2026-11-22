// The play constants along farxw's chain (src/brain.ts, kiter, farm, gang, far5, farx, farxw) and far6's evasive layer,
// one table. The code reads each as `kn.<NAME>`; every brain holds the defaults, and bots/farxwk reads KNOB_<NAME> from
// env, so a sweep moves only the candidate. sim/KNOBS.md is generated from this list (bun tools/knobs.ts).
export type Knob = { v: number | string; group: string; range: string; what: string }

const PICK = "pickups/cubes/upgrades"
const BAND = "fight distance"
const DODGE = "dodge"
const JETS = "jets/flying"
const CROWD = "gang/crowd"
const ZONE = "zone/edge"
const END = "FFA switch timing"
const AIM = "targeting"
const SNIPE = "laser sniper"

export const KNOBS = {
  // ---- pickups, cubes, upgrades
  UPGRADES: { v: "farm", group: PICK, range: "farm u1 u2 u3 u4 u5 u6 u7 u8", what: "cube upgrade pick order, a preset in UPGRADE_PRESETS" },
  LOOT_R_EARLY: { v: 170, group: PICK, range: "100-250", what: "walk to a wanted weapon this far, before LOOT_EARLY_S" },
  LOOT_R_LATE: { v: 60, group: PICK, range: "30-150", what: "walk to a wanted weapon this far, after LOOT_EARLY_S" },
  LOOT_EARLY_S: { v: 100, group: PICK, range: "60-180", what: "match second the long loot reach ends" },
  LOOT_FIRST_BONUS: { v: 40, group: PICK, range: "0-80", what: "meters of credit for the most wanted weapon kind" },
  CUBE_R: { v: 140, group: PICK, range: "80-200", what: "walk to a cube on our level this far in peace" },
  CALM_R: { v: 160, group: PICK, range: "100-220", what: "no cube or farming while a mech was seen this close" },
  CALM_S: { v: 6, group: PICK, range: "3-12", what: "a mech seen this many seconds ago still counts for CALM_R" },
  FIGHT_CUBE_R: { v: 28, group: PICK, range: "10-50", what: "detour mid-fight for a cube this close" },
  FIGHT_CUBE_R_RETREAT: { v: 14, group: PICK, range: "0-30", what: "detour for a cube this close while retreating" },
  FIGHT_LOOT_R: { v: 80, group: PICK, range: "40-120", what: "detour mid-fight for a wanted weapon this close" },
  FIGHT_LOOT_R_RETREAT: { v: 50, group: PICK, range: "0-80", what: "detour for a wanted weapon this close while retreating" },
  PREY_HP_FRAC: { v: 0.6, group: PICK, range: "0.3-0.9", what: "farm drones and crates only above this HP fraction" },
  CUBE_CAP: { v: 10, group: PICK, range: "6-20", what: "stop farming at this many cubes" },
  DRONE_R: { v: 200, group: PICK, range: "100-250", what: "farm a drone this far" },
  CRATE_R: { v: 150, group: PICK, range: "80-200", what: "farm a crate this far" },
  CRATE_BIAS: { v: 30, group: PICK, range: "0-60", what: "meters a crate counts farther than a drone" },
  DRONE_STANDOFF: { v: 60, group: PICK, range: "30-90", what: "stand this far off a drone we shoot" },
  DRONE_STANDOFF_ARC: { v: 30, group: PICK, range: "15-40", what: "stand-off from a drone while holding the arc gun" },
  CRATE_WALK_R: { v: 120, group: PICK, range: "60-150", what: "walk to a crate past this distance, else shoot from where we stand" },
  LASER_GRAB_R: { v: 80, group: PICK, range: "40-140", what: "break off a fight for a laser this close" },
  LASER_DZ: { v: 8, group: PICK, range: "4-12", what: "a laser this many meters above or below counts as on our level" },
  LASER_RACE_S: { v: 5, group: PICK, range: "2-10", what: "an enemy nearer a laser and seen this recently takes it from us" },
  SEARCH_MIN: { v: 80, group: PICK, range: "40-120", what: "laser search points at least this far" },
  SEARCH_SPAN: { v: 80, group: PICK, range: "40-120", what: "laser search points up to SEARCH_MIN plus this" },
  SEARCH_S: { v: 20, group: PICK, range: "10-40", what: "seconds before a new search point" },
  SEARCH_AVOID_R: { v: 150, group: PICK, range: "80-200", what: "search points shun enemies seen within this" },
  // ---- fight distance
  BAND_K: { v: 1.3, group: BAND, range: "1.0-1.6", what: "farxw: every band of 20 m or more held this many times farther" },
  BAND_CAP: { v: 190, group: BAND, range: "150-200", what: "farxw: the scaled band's far edge at most this, its near edge 30 less" },
  BAND_K_FROM: { v: 20, group: BAND, range: "10-60", what: "farxw: bands with a near edge under this (arc bands) are not scaled" },
  LONG_LO: { v: 90, group: BAND, range: "60-130", what: "far5: near edge against a laser or mortar holder or a crowd" },
  LONG_HI: { v: 130, group: BAND, range: "100-180", what: "far5: far edge against a laser or mortar holder or a crowd" },
  CROWD_R: { v: 160, group: CROWD, range: "100-220", what: "far5: visible foes this close count toward the crowd" },
  CROWD_N: { v: 2, group: CROWD, range: "1-4", what: "far5: this many foes in CROWD_R take the long band" },
  ARC_BAND_LO: { v: 8, group: BAND, range: "4-15", what: "near edge with our arc gun out" },
  ARC_BAND_FRAC: { v: 0.7, group: BAND, range: "0.5-0.9", what: "far edge with our arc gun out, a fraction of its range" },
  ARC_GAP: { v: 30, group: BAND, range: "10-50", what: "meters past their arc gun's range we keep" },
  LASER_BAND_LO: { v: 120, group: BAND, range: "80-160", what: "near edge with our laser against no laser" },
  LASER_BAND_HI: { v: 185, group: BAND, range: "150-230", what: "far edge with our laser against no laser or an arc gun" },
  LASER_DUEL_LO: { v: 50, group: BAND, range: "25-90", what: "near edge laser against laser" },
  LASER_DUEL_HI: { v: 140, group: BAND, range: "100-185", what: "far edge laser against laser" },
  GUN_VS_ARC_HI: { v: 150, group: BAND, range: "100-200", what: "far edge with the gun against an arc gun" },
  GUN_VS_LASER_LO: { v: 25, group: BAND, range: "10-60", what: "near edge with the gun against a laser" },
  GUN_VS_LASER_HI: { v: 70, group: BAND, range: "45-120", what: "far edge with the gun against a laser" },
  GUN_VS_MORTAR_LO: { v: 18, group: BAND, range: "8-40", what: "near edge with the gun against a mortar" },
  GUN_VS_MORTAR_HI: { v: 45, group: BAND, range: "25-90", what: "far edge with the gun against a mortar" },
  GUN_BAND_LO: { v: 60, group: BAND, range: "30-90", what: "near edge gun against gun" },
  GUN_BAND_HI: { v: 110, group: BAND, range: "80-160", what: "far edge gun against gun" },
  BAND_W: { v: 1, group: BAND, range: "0.5-3", what: "planner cost per meter outside the band" },
  // ---- dodge: the fight move planner (kiter planMove) and far6's sidesteps
  DODGE_K: { v: 2, group: DODGE, range: "1-4", what: "farxw: weight of predicted bullet damage in the move planner" },
  BULLET_DMG_K: { v: 1.2, group: DODGE, range: "0.8-2", what: "a gun bullet's damage counts this many times in the planner" },
  SHELL_K: { v: 1.2, group: DODGE, range: "0.5-2.5", what: "mortar splash damage counts this many times in the planner" },
  SHELL_HORIZON_S: { v: 2.5, group: DODGE, range: "1-4", what: "dodge shells landing within this many seconds" },
  STRAFE_W: { v: 6, group: DODGE, range: "0-15", what: "cost of moving off the sideways strafe direction" },
  STOP_COST: { v: 10, group: DODGE, range: "0-25", what: "cost of standing still in a fight" },
  SIDE_MIN_S: { v: 0.35, group: DODGE, range: "0.2-1", what: "strafe side held at least this many seconds" },
  SIDE_SPAN_S: { v: 0.75, group: DODGE, range: "0.2-2", what: "strafe side held up to SIDE_MIN_S plus this, at random" },
  LOS_LOST_COST: { v: 35, group: DODGE, range: "10-60", what: "cost of losing sight of the target" },
  WATCHER_COST: { v: 25, group: CROWD, range: "0-50", what: "cost per other enemy that sees where we end up" },
  SPREAD_W: { v: 30, group: CROWD, range: "0-60", what: "cost per radian of watchers spreading past 90 degrees" },
  RETREAT_SEEN_COST: { v: 60, group: DODGE, range: "20-100", what: "retreating: cost per watcher that still sees us" },
  COVER_R: { v: 45, group: DODGE, range: "20-80", what: "retreating: look for cover from the target this far" },
  COVER_W: { v: 3, group: DODGE, range: "0-6", what: "retreating: cost per meter from that cover" },
  BLOCKED_COST: { v: 25, group: DODGE, range: "0-50", what: "cost of a move that runs into a wall" },
  WALL_CLEAR: { v: 3.2, group: DODGE, range: "1-6", what: "ending closer than this to a wall costs WALL_W a meter" },
  WALL_W: { v: 4, group: DODGE, range: "0-10", what: "cost per meter inside WALL_CLEAR" },
  SIDE_DODGE: { v: 1, group: DODGE, range: "0 1", what: "far6: with EVASIVE, sidestep seen shots out of a fight" },
  // ---- jets and flying
  EVASIVE: { v: 0, group: JETS, range: "0 1", what: "farxwk: 1 wraps farxw in far6's evasive layer (roof jets, sidesteps), as far6w" },
  CLIMB_H: { v: 25, group: JETS, range: "8-40", what: "far6: jet onto a roof at most this many meters above our feet" },
  CLIMB_E: { v: 20, group: JETS, range: "5-40", what: "far6: energy margin a climb keeps" },
  CLIMB_PER_M: { v: 1.6, group: JETS, range: "1-2.5", what: "far6: energy a climb needs per meter of rise" },
  CLIMB_AHEAD: { v: 4.5, group: JETS, range: "2-10", what: "far6: look this far along the move for the wall to climb" },
  RUSH_E: { v: 15, group: JETS, range: "0-50", what: "gang: boost toward a laser while energy is above this" },
  ZONE_BOOST_E: { v: 25, group: JETS, range: "0-60", what: "boost outside the circle while energy is above this" },
  BOOST_COST: { v: 4, group: JETS, range: "0-15", what: "planner cost of a boosted move" },
  BOOST_COST_ARC: { v: 6, group: JETS, range: "0-15", what: "extra boost cost while holding the arc gun (it runs on energy)" },
  BOOST_FLOOR: { v: 12, group: JETS, range: "0-40", what: "no boosted moves in a fight below this energy" },
  BOOST_FLOOR_ARC: { v: 30, group: JETS, range: "10-60", what: "no boosted moves below this energy while holding the arc gun" },
  // ---- gang and crowd: when a second attacker turns a fight into a retreat
  THREAT_R: { v: 200, group: CROWD, range: "100-230", what: "an aware enemy this close is a threat in a fight; any foe this close makes an unaware one not free" },
  HIT_MEMORY_S: { v: 2.5, group: CROWD, range: "1-5", what: "an unseen shooter counts as a threat this long after its hit" },
  RETREAT_HP: { v: 0.5, group: CROWD, range: "0.2-0.8", what: "retreat from a fight with other threats below this HP fraction" },
  RETREAT_ODDS: { v: 0.75, group: CROWD, range: "0.5-1.2", what: "retreat when their time to kill us is under this times ours" },
  RETREAT_ODDS_HP: { v: 0.85, group: CROWD, range: "0.5-1", what: "the RETREAT_ODDS rule applies below this HP fraction" },
  RETREAT_LOW_HP: { v: 0.25, group: CROWD, range: "0.1-0.4", what: "retreat below this HP fraction from a foe with more HP" },
  P5_LEAVE: { v: 2.6, group: CROWD, range: "1.5-4", what: "farxp5: leave a fight when this many attackers are expected on us in the next 5 s" },
  P5_OPEN: { v: 1.6, group: CROWD, range: "1-3", what: "farxp5: hold the band P5_OPEN_M farther at this many expected attackers, and leave below the HP floor" },
  P5_OPEN_M: { v: 15, group: CROWD, range: "0-40", what: "farxp5: meters both band edges move out at P5_OPEN" },
  P5_FLOOR: { v: 0.2, group: CROWD, range: "0-0.5", what: "farxp5: at P5_OPEN, leave when HP after the next 5 s of expected damage is under this fraction" },
  P5_HIT_M: { v: 7, group: CROWD, range: "0-20", what: "farxp5: meters the band moves out for P5_HIT_S after a hit, above half HP; 0 never" },
  P5_HIT_LOW_M: { v: 13, group: CROWD, range: "0-30", what: "farxp5: the same below half HP" },
  P5_HIT_S: { v: 3, group: CROWD, range: "1-6", what: "farxp5: seconds the band stays out after a hit" },
  P5_SLOW_S: { v: 1, group: CROWD, range: "0-3", what: "farxp5: seconds between posture choices; 0 chooses every decision, with no hold" },
  P5_HOLD_S: { v: 3, group: CROWD, range: "0-6", what: "farxp5: a posture holds this long unless a hit, a laser charging at us or a third mech inside 150 m wakes the choice" },
  P5_COVER: { v: 0, group: CROWD, range: "0-1", what: "farxp5: 1 leaves toward cover from the target as farx does, 0 only away from the attackers" },
  FOE_MEMORY_S: { v: 0.6, group: CROWD, range: "0.2-2", what: "an enemy seen this many seconds ago is still a foe" },
  // ---- zone and edge
  ZONE_LEAD_S: { v: 25, group: ZONE, range: "10-45", what: "seconds before a shrink that loot, cubes and lasers must be inside the next circle" },
  ZONE_SAFE_M: { v: 10, group: ZONE, range: "0-30", what: "loot, cubes and lasers count as inside the circle this far in from its edge" },
  ZONE_EDGE_M: { v: 6, group: ZONE, range: "0-20", what: "fight moves ending this close to the circle's edge cost ZONE_EDGE_W a meter" },
  ZONE_EDGE_W: { v: 4, group: ZONE, range: "1-10", what: "cost per meter inside ZONE_EDGE_M" },
  HIDE_EXP_W: { v: 60, group: ZONE, range: "20-120", what: "hiding spot: weight of its exposure" },
  HIDE_DIST_W: { v: 0.12, group: ZONE, range: "0.03-0.4", what: "hiding spot: cost per meter of walk" },
  HIDE_ENEMY_R: { v: 130, group: ZONE, range: "60-200", what: "hiding spot: shun enemies seen within this" },
  HIDE_CENTER_FRAC: { v: 0.35, group: ZONE, range: "0-0.7", what: "hiding spot: keep this fraction of the next radius off its center" },
  REHIDE_S: { v: 25, group: ZONE, range: "10-60", what: "pick a new hiding spot at least this often" },
  // ---- FFA switch timing: when every mech becomes a target
  END_ALIVE: { v: 3, group: END, range: "2-6", what: "endgame (fight anything, no retreat, no loot) at this many alive" },
  END_RADIUS: { v: 40, group: END, range: "20-80", what: "endgame once the circle is this small" },
  END_NEXT_R: { v: 25, group: END, range: "10-50", what: "endgame once the next circle is this small and its shrink is END_LEAD_S away" },
  END_LEAD_S: { v: 5, group: END, range: "0-20", what: "seconds before that shrink" },
  // ---- targeting
  LEAD_K: { v: 0.85, group: AIM, range: "0.6-1.1", what: "fraction of the target's velocity we lead by" },
  TARGET_R: { v: 230, group: AIM, range: "150-260", what: "foes this far are targets" },
  ENGAGE_R: { v: 75, group: AIM, range: "40-150", what: "an unaware foe past this is left alone unless it is free or weak prey" },
  FREE_ODDS: { v: 1.4, group: AIM, range: "1-3", what: "an unaware foe is free when we kill it this many times faster, alone, above half HP" },
  WEAK_HP: { v: 300, group: AIM, range: "100-600", what: "an unaware foe under this HP is weak prey" },
  WEAK_R: { v: 150, group: AIM, range: "75-230", what: "weak prey this close is a target" },
  ODDS_THEIRS_W: { v: 0.3, group: AIM, range: "0-1", what: "target score: weight of their time to kill us against ours" },
  TARGET_DIST_M: { v: 100, group: AIM, range: "30-300", what: "target score: meters that cost one second of time to kill" },
  HIT_BONUS: { v: 3, group: AIM, range: "0-6", what: "target score: credit for the foe that hit us in the last 2 s" },
  FOCUS_BONUS: { v: 1.5, group: AIM, range: "0-4", what: "target score: credit for the target we already have" },
  AWARE_SLACK: { v: 3, group: AIM, range: "1-6", what: "a foe aims at us (aware) within this many times its hit cone" },
  AWARE_HIT_S: { v: 3, group: AIM, range: "1-6", what: "a foe that hit us this recently is aware" },
  // ---- farxwgh1, the laser sniper
  OPEN_R: { v: 190, group: SNIPE, range: "120-230", what: "farxwgh1: with a laser, open on an unaware foe this close, others around or not" },
  OPEN_HP: { v: 0.5, group: SNIPE, range: "0.3-0.9", what: "farxwgh1: open only above this HP fraction" },
  RUSH_S: { v: 30, group: SNIPE, range: "0-60", what: "farxwgh1: until this match second without a laser, shoot crates on the way with mechs near" },
  RUSH_CALM_R: { v: 60, group: SNIPE, range: "0-160", what: "farxwgh1: in the rush, no cube or farming only while a mech was seen this close (CALM_R after)" },
  RUSH_CRATE_R: { v: 80, group: SNIPE, range: "30-150", what: "farxwgh1: in the rush, shoot a crate in sight this close while walking elsewhere" },
  LATE_N: { v: 4, group: SNIPE, range: "0-6", what: "farxwgh1: with this many alive or fewer (3 or more), hold LATE_BAND_LO with a laser and break line of sight from a laser charging at us" },
  LATE_BAND_LO: { v: 120, group: SNIPE, range: "60-160", what: "farxwgh1: late, the near edge of every band while we hold a laser" },
  GUN_MAX_R: { v: 120, group: SNIPE, range: "0-230", what: "farxwgh1: with a laser, the gun holds fire on a mech past this (ours hit 45% at 120-160 m, 25% past); 0 never" },
  CLOSE_R: { v: 60, group: SNIPE, range: "0-90", what: "farxwgh1: with a laser, break line of sight from a target inside this; 0 never" },
} satisfies Record<string, Knob>

export type Knobs = { [K in keyof typeof KNOBS]: (typeof KNOBS)[K]["v"] }
export const KNOB_DEFAULTS = Object.fromEntries(Object.entries(KNOBS).map(([k, s]) => [k, s.v])) as Knobs

// Cube upgrade orders: farm's (farxw's) and the 8 screened as bots/farxwu1-8. Ids missing from an order rank 1, and
// an upgrade for a weapon kind we do not hold ranks 1 too (farm pickKit).
export const UPGRADE_PRESETS: Record<string, Record<string, number>> = {
  // per pick, against several attackers (protocol.md §7, hello.config.upgrades): plating x1.15 HP beats armor
  // (-8% damage, x1.087 then x1.095); the drum magazine lifts sustained gun damage about 30% (20 rounds, reload x0.8),
  // the lens +18% laser damage; gun damage +15% and fire rate x1.15 count only between reloads
  farm: {
    plating: 10, gun_mag: 9, laser_damage: 9, armor: 8, gun_damage: 8, lightning_efficiency: 8, gun_rate: 7, nanites: 7,
    laser_charge: 7, lightning_range: 6, servos: 6, gyros: 5, gun_velocity: 5, capacitor: 4, reactor: 4, jets: 3,
    sensors: 3, lightning_chain: 3, laser_pierce: 2, mortar_reload: 1, mortar_velocity: 1, mortar_splash: 1,
  },
  // offense first
  u1: { gun_rate: 12, gun_damage: 11, laser_damage: 11, laser_charge: 10, lightning_efficiency: 9, plating: 8, armor: 8, nanites: 7, gun_mag: 6, gun_velocity: 5, servos: 4, sensors: 3, gyros: 3, reactor: 2, capacitor: 2, jets: 2 },
  // mobility first
  u2: { servos: 12, jets: 11, reactor: 10, capacitor: 9, plating: 8, armor: 8, nanites: 7, gun_rate: 6, laser_damage: 6, laser_charge: 6, gun_damage: 5, gyros: 4, sensors: 4 },
  // armor before plating
  u3: { armor: 12, plating: 11, nanites: 10, laser_damage: 7, laser_charge: 7, gun_rate: 6, gun_damage: 6, servos: 5, lightning_efficiency: 5, sensors: 4, gyros: 4, gun_mag: 4 },
  // nanites first
  u4: { nanites: 12, plating: 11, armor: 10, laser_damage: 7, laser_charge: 7, gun_rate: 6, gun_damage: 6, servos: 5, sensors: 4, gyros: 4, gun_mag: 4 },
  // sensors first
  u5: { sensors: 12, plating: 10, armor: 9, nanites: 8, laser_damage: 7, laser_charge: 7, gun_rate: 6, gun_damage: 6, servos: 5, gyros: 4, gun_mag: 4 },
  // energy first
  u6: { reactor: 12, capacitor: 11, jets: 10, plating: 9, armor: 9, nanites: 8, laser_damage: 7, laser_charge: 7, gun_rate: 6, gun_damage: 6, servos: 5 },
  // laser first
  u7: { laser_charge: 12, laser_damage: 11, laser_pierce: 9, plating: 10, armor: 9, nanites: 8, gun_rate: 6, gun_damage: 6, servos: 5, sensors: 4, gyros: 4 },
  // gyros first
  u8: { gyros: 12, plating: 10, armor: 9, nanites: 8, laser_damage: 7, laser_charge: 7, gun_rate: 6, gun_damage: 6, servos: 5, sensors: 4 },
}

/** the defaults with each KNOB_<NAME> in env applied; a name, number or preset that does not exist throws */
export function knobsFromEnv(env: Record<string, string | undefined> = process.env): Knobs {
  const k: Record<string, number | string> = { ...KNOB_DEFAULTS }
  for (const [key, raw] of Object.entries(env)) {
    if (!key.startsWith("KNOB_") || raw === undefined) continue
    const name = key.slice(5)
    if (!(name in KNOBS)) throw new Error(`${key}: no such knob (src/knobs.ts)`)
    if (name === "UPGRADES") {
      if (!(raw in UPGRADE_PRESETS)) throw new Error(`${key}=${raw}: no such preset, one of ${Object.keys(UPGRADE_PRESETS).join(" ")}`)
      k[name] = raw
      continue
    }
    const v = Number(raw)
    if (raw.trim() === "" || !Number.isFinite(v)) throw new Error(`${key}=${raw}: not a number`)
    k[name] = v
  }
  return k as Knobs
}
