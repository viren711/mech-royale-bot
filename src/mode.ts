// Practice or finals, from what the observations show. The board's practice is 15 house bots that "never fight each
// other", so only drones and the zone kill a house bot there; team bots kill each other from the opening. Observations
// carry no names, so the signal is deaths we did not cause. data/live, deduplicated by seed: 2 such deaths by 45 s come
// in 6 of 546 play rooms counting only house bots no mech killed (an upper bound, since there house bots wear each other
// down first), and for 1179 of the 1202 showdown seats alive at the switch, at 21 s median.
import type { Observation } from "./mechfight.ts"

export type Mode = "practice" | "finals" | "unknown"

export const FINALS_DEAD = 2
// later deaths say nothing: the zone kills house bots too
export const FINALS_BY = 45
// the shares above: a finals read wrong in 1.1% of rooms, a practice read wrong for 2% of showdown seats
const FINALS_CONF = 0.99
const PRACTICE_CONF = 0.98

export function finalsSeen(t: number, dead: number): boolean {
  return t <= FINALS_BY && dead >= FINALS_DEAD
}

/** the mode from every observation since tick 0; it reads only up to FINALS_BY, so once it is decided it stays */
export function mode(history: Observation[]): { mode: Mode; confidence: number } {
  const alive0 = history[0]?.alive ?? 0
  let kills = 0
  for (const obs of history) {
    if (obs.t > FINALS_BY) return { mode: "practice", confidence: PRACTICE_CONF }
    for (const ev of obs.events) if (ev.type === "kill") kills++
    if (finalsSeen(obs.t, alive0 - obs.alive - kills)) return { mode: "finals", confidence: FINALS_CONF }
  }
  return { mode: "unknown", confidence: 0 }
}
