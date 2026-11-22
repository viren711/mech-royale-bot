// One brain, many goals. Each lane behavior (drop sniper, dodge, zap, endgame, laser hunter...) is a Goal; bots/arb
// runs one at a time under an arbiter that commits to its pick (no flip-flop) and lets a floor goal take over when we
// are about to lose too much hp. A goal never sees the others: it says what it is worth now, then plays until done.
//
// Utility is in expected places gained against playing the default goals for the goal's horizon (the defaults score
// 0). Self-preservation sits inside every score: a goal subtracts the hp it expects to lose, priced by hpCost().
//   utility = gainPlaces x P(success) - hpCost(expected damage taken)
// A goal that does not apply returns -Infinity.
import type { Action, Observation, SelfObs } from "./mechfight.ts"
import type { Rivals } from "./rivals.ts"
import type { Brain as Duo } from "../bots/duo/brain.ts"

export type Act = Omit<Action, "tick">
export type Status = "run" | "done" | "fail"

/** where the match is: time, circle, field size and which kind of field we are in */
export type Phase = {
  /** match time, s */
  t: number
  /** mechs alive, us included */
  alive: number
  /** mechs alive at the first observation */
  alive0: number
  zone: Observation["zone"]
  /** 0 before the first shrink starts, then +1 per shrink started */
  stage: number
  /** s until the next shrink starts (negative while one runs) */
  toShrink: number
  /** the field reads as a finals free-for-all (team bots, many early deaths: duo's FfaWatch); false = practice house rooms */
  ffa: boolean
  /** duo's endgame: few alive or a small circle */
  endgame: boolean
}

export type Ctx = {
  obs: Observation
  me: SelfObs
  t: number
  phase: Phase
  rivals: Rivals
  /** the duo brain running underneath: world, nav, steer(), planMove(), weaponsPlan(), dps(), odds(), its memory */
  host: Duo
  /** duo's own action this tick, computed before any goal steps; a goal may return it or edit a copy */
  base: Act
  /** duo's mode for base (fight, retreat, grab, loot, cube, farm, search, hide, duck, sneak, zone...) */
  baseMode: string
  /** expected damage we take over the next FLOOR_S seconds from the rivals on us (rivals.incoming) */
  incoming: number
}

export interface Goal {
  name: string
  /** s the arbiter keeps this goal once picked, unless it ends itself or a floor goal fires */
  minHold: number
  /** a flee / break line of sight goal: picked only while the hp floor is breached, and then over any commitment */
  floor?: boolean
  /** expected places gained vs the defaults, net of hpCost; -Infinity when it does not apply */
  utility(ctx: Ctx): number
  /** called once when the arbiter picks it */
  start(ctx: Ctx): void
  /** the action this tick */
  step(ctx: Ctx): Act
  /** 'done' or 'fail' ends the commitment: the arbiter picks again this tick */
  status(ctx: Ctx): Status
}

/** a rival goal must beat the held one by this many expected places to take over after minHold */
export const MARGIN = 0.15
/** the hp floor looks this far ahead */
export const FLOOR_S = 2
/** floor goals take over when hp minus incoming damage over FLOOR_S would fall below this fraction of max hp */
export const FLOOR_FRAC = 0.25

/** places we expect to lose by dying now: half the field still alive is ahead of a random death */
export function deathPlaces(ctx: Ctx): number {
  return (ctx.phase.alive - 1) / 2
}

/** expected places lost to `dmg` hp of damage: the chance it kills us, linear in the share of hp it takes */
export function hpCost(ctx: Ctx, dmg: number): number {
  return deathPlaces(ctx) * Math.min(1, Math.max(0, dmg) / Math.max(1, ctx.me.hp))
}

/** the utility formula every goal should use */
export function score(ctx: Ctx, gainPlaces: number, pSuccess: number, dmg: number): number {
  return gainPlaces * pSuccess - hpCost(ctx, dmg)
}

/** the hp floor: true when the next FLOOR_S seconds of incoming damage would leave us under FLOOR_FRAC */
export function floorBreached(ctx: Ctx): boolean {
  return ctx.me.hp - ctx.incoming < ctx.me.max_hp * FLOOR_FRAC
}
