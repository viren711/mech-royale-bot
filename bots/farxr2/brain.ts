// farxr2: farx that farms no drone or crate outside the next circle. farx's prey (bots/farm/brain.ts:153) checks no
// zone while its loot and cubes do (bots/farm/brain.ts:90-116), and 14.6% of farx's squad sim deaths were to the zone,
// farming a target and then walking out (mech handoff-next.md 17:5x).
import type { Observation } from "../../src/mechfight.ts"
import { Brain as FarX } from "../farx/brain.ts"

type Base = new (...args: any[]) => FarX

const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])

export function zonePrey<B extends Base>(B: B) {
  return class extends B {
    /** the parent's prey among drones and crates inside the next circle */
    prey(obs: Observation) {
      const z = obs.zone
      const safe = (p: number[]) => d2(p, z.next_center) < z.next_radius - this.kn.ZONE_SAFE_M
      const mechs = obs.mechs.filter((m) => m.kind !== "npc" || safe(m.pos))
      const crates = (obs.crates ?? []).filter((c) => safe(c.pos))
      return super.prey({ ...obs, mechs, crates })
    }
  }
}

export class Brain extends zonePrey(FarX) {}
