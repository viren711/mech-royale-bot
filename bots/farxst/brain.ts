// farxst: farx that leads hunters into the storm. Outside the circle a mech loses the phase's dps with no armor or regen
// (protocol.md §9), and in squad practice a house bot that dies before us is a point whoever killed it. Retreating
// from a watcher with the circle's edge near, the planner is pulled to a line just inside the edge, so we run along it
// and the chasers behind us cut through or trail outside as the circle closes. kiter's own edge cost
// (bots/kiter/brain.ts:570, ZONE_EDGE_M 6 m) still keeps our own end points off the last meters.
import type { Observation } from "../../src/mechfight.ts"
import { Brain as FarX } from "../farx/brain.ts"

type Base = new (...args: any[]) => FarX
type Foe = ReturnType<FarX["foes"]>[number]

const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))
// we take the edge when we stand this close to it
const NEAR_M = 40
// a watcher this close is chasing us
const CHASE_R = 150
// the line we run along, this far inside the edge
const LINE_IN = 8
// planner cost per meter off that line: twice kiter's COVER_W, so the line wins over the nearest cover
const LINE_W = 6

export function stormLead<B extends Base>(B: B) {
  return class extends B {
    /** the circle as it stands now: center x, y and radius */
    circle: [number, number, number] = [0, 0, Infinity]

    track(obs: Observation) {
      super.track(obs)
      const z = obs.zone
      const f = clamp((obs.t - z.shrink_start) / Math.max(1, z.shrink_end - z.shrink_start), 0, 1)
      this.circle = [z.center[0] + (z.next_center[0] - z.center[0]) * f, z.center[1] + (z.next_center[1] - z.center[1]) * f, z.radius + (z.next_radius - z.radius) * f]
    }

    /** meters from p to the edge, negative outside */
    edgeOf(p: number[]): number {
      const [cx, cy, r] = this.circle
      return r - Math.hypot(p[0] - cx, p[1] - cy)
    }

    leading(watchers: Foe[], retreat: boolean): boolean {
      if (!retreat || this.edgeOf(this.me.pos) > NEAR_M) return false
      return watchers.some((f) => d2(f.pos, this.me.pos) < CHASE_R)
    }

    moveCost(end: number[], watchers: Foe[], retreat: boolean, path?: number[][]): number {
      const c = super.moveCost(end, watchers, retreat, path)
      if (!this.leading(watchers, retreat)) return c
      return c + Math.abs(this.edgeOf(end) - LINE_IN) * LINE_W
    }
  }
}

export class Brain extends stormLead(FarX) {}
