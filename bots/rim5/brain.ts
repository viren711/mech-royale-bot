// far5 (far + roof fixes) that keeps to the rim of the circle while it is large. House bots roam the inner 0.6 of the circle and walk to
// any entrant within 300 m, so a gang spawn within 100 m of the center scores 1.5 and one past 400 m scores 8.7
// (sim, seeds 1-480): lasers, search points and hides stay in the outer ring of the circle we must be in.
import type { Hello, Observation } from "../../src/mechfight.ts"
import type { World } from "../../src/world.ts"
import type { Nav } from "../../src/nav.ts"
import type { Exposure } from "../../src/exposure.ts"
import { Brain as Gang } from "../far5/brain.ts"

type V2 = [number, number]

const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])
// keep at least this fraction of the circle's radius from its center (0.8 scored 6.27, 0.9 6.44, 1.0 6.43)
const RING = 0.9
// a laser inside the ring is still worth it this close
const NEAR = 50
// ring play stops once the circle is this small: the last circles hold everyone
const MIN_R = 200

export class Brain extends Gang {
  ringK = RING
  constructor(hello: Hello, w?: World, nav?: Nav, exp?: Exposure | null) {
    super(hello, w, nav, exp)
    this.name = "rim5"
  }

  /** the circle gang plays in: the next one from 25 s before it shrinks, with its ring radius; null when it is small */
  ring(obs: Observation): { C: number[]; R: number; r: number } | null {
    const z = obs.zone
    const soon = this.t > z.shrink_start - 25
    const C = soon ? z.next_center : z.center
    const R = soon ? z.next_radius : z.radius
    if (R < MIN_R) return null
    return { C, R, r: R * this.ringK }
  }

  /** gang's laser goal, skipping lasers inside the ring unless one is close */
  laserGoal(obs: Observation, maxD: number): V2 | null {
    const g = this.ring(obs)
    if (!g) return super.laserGoal(obs, maxD)
    if (this.me.weapons.some((w) => w?.kind === "laser")) return null
    const pos = this.me.pos
    let goal: V2 | null = null
    let gs = maxD
    for (const [, p] of this.loot) {
      if (p.kind !== "laser" || Math.abs(p.pos[2] - pos[2]) > 8 || d2(p.pos, g.C) > g.R - 10) continue
      const d = d2(p.pos, pos)
      if (d >= gs || (d2(p.pos, g.C) < g.r && d > NEAR)) continue
      gs = d
      goal = [p.pos[0], p.pos[1]]
    }
    return goal
  }

  searchPoint(C: number[], R: number): V2 {
    const p = super.searchPoint(C, R)
    if (R < MIN_R) return p
    return this.onRing(C, R, p)
  }

  pickHide(obs: Observation): V2 {
    const p = super.pickHide(obs)
    const g = this.ring(obs)
    if (!g) return p
    return this.onRing(g.C, g.R, p)
  }

  /** p if it lies in the ring, else the clear ring point nearest its bearing from C */
  onRing(C: number[], R: number, p: V2): V2 {
    const r = R * this.ringK
    const d = d2(p, C)
    if (d >= r) return p
    const pos = this.me.pos
    const base = d > 1 ? Math.atan2(p[1] - C[1], p[0] - C[0]) : Math.atan2(pos[1] - C[1], pos[0] - C[0])
    const mid = (r + R - 30) / 2
    for (let k = 0; k < 9; k++) {
      const ang = base + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 0.12
      const x = C[0] + Math.cos(ang) * mid
      const y = C[1] + Math.sin(ang) * mid
      if (this.w.clearAt(x, y) >= 5) return [x, y]
    }
    return [C[0] + Math.cos(base) * mid, C[1] + Math.sin(base) * mid]
  }
}
