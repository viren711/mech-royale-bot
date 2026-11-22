// far5 that stops running to lasers it will not get. In 4 of our 14 showdown deaths (sim/SHOWDOWN.md pool,
// show-20261121T072729, 090000, 091235, 092557) a mech nearer the laser took it while we kept walking 100 to 200 m to
// where it had lain, and that mech killed us with it: a pickup is listed only while seen (protocol.md §8 Vision), but
// the parent forgets one only within 35 m, and it never asks who is closer.
import type { Hello, Observation } from "../../src/mechfight.ts"
import type { World } from "../../src/world.ts"
import type { Nav } from "../../src/nav.ts"
import type { Exposure } from "../../src/exposure.ts"
import { Brain as Far5 } from "../far5/brain.ts"

type V2 = [number, number]

const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])
const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a))
// stay inside the vision edges, so a pickup at the limit is not forgotten on a rounding difference
const EDGE_M = 10
const EDGE_RAD = 0.05

export class Brain extends Far5 {
  constructor(hello: Hello, w?: World, nav?: Nav, exp?: Exposure | null) {
    super(hello, w, nav, exp)
    this.name = "farx"
  }

  track(obs: Observation) {
    super.track(obs)
    const listed = new Set(obs.pickups.map((p) => p.id))
    for (const [id, p] of this.loot) {
      if (!listed.has(id) && this.shouldSee(obs, p.pos)) this.loot.delete(id)
    }
  }

  /** protocol.md §8: in the near ring, or in range inside the yaw wedge, with a clear line from our eye */
  shouldSee(obs: Observation, p: number[]): boolean {
    const s = obs.self
    const V = this.cfg.vision
    const eye = s.pos[2] + 8 * this.scaleOf(s.cubes)
    const d = d2(p, s.pos)
    const near = d < V.near_range + (s.stats.near_range_bonus ?? 0) - EDGE_M
    if (!near) {
      if (d > V.range + (s.stats.vision_bonus ?? 0) - EDGE_M) return false
      const off = Math.abs(wrap(Math.atan2(p[1] - s.pos[1], p[0] - s.pos[0]) - s.aim[0]))
      if (off > (V.fov_deg * Math.PI) / 360 - EDGE_RAD) return false
      if (this.w.canopyCover(s.pos[0], s.pos[1], eye, p[0], p[1], p[2] + 0.5) > 0) return false
    }
    return this.w.los(s.pos[0], s.pos[1], eye, p[0], p[1], p[2] + 0.5)
  }

  /** the parent's laser goal among lasers no enemy we know of is nearer to */
  laserGoal(obs: Observation, maxD: number): V2 | null {
    const pos = this.me.pos
    const raced: [number, { kind: string; pos: number[] }][] = []
    for (const [id, p] of this.loot) {
      if (p.kind !== "laser") continue
      const mine = d2(p.pos, pos)
      for (const e of this.enemies.values()) {
        if (this.t - e.seen < this.kn.LASER_RACE_S && d2(e.pos, p.pos) < mine) {
          raced.push([id, p])
          break
        }
      }
    }
    for (const [id] of raced) this.loot.delete(id)
    try {
      return super.laserGoal(obs, maxD)
    } finally {
      for (const [id, p] of raced) this.loot.set(id, p)
    }
  }
}
