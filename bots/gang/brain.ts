// Farm bot tuned against a swarm: house bots near us converge on our live position, so fights are one against many.
// Most kiter deaths come before it holds a laser (52 of 80 sim deaths with the gun alone), so the laser comes first:
// race to the nearest one we know of, breaking off a fight for one close by; search the circle for one.
import type { Hello, Observation } from "../../src/mechfight.ts"
import type { World } from "../../src/world.ts"
import type { Nav } from "../../src/nav.ts"
import type { Exposure } from "../../src/exposure.ts"
import { Brain as Farm } from "../farm/brain.ts"

type V2 = [number, number]
type Foe = ReturnType<Farm["foes"]>[number]

const TAU = Math.PI * 2
const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])

export class Brain extends Farm {
  search: V2 | null = null
  searchT = 0
  searched: V2[] = []
  rush = false // boost this tick: racing to a laser
  constructor(hello: Hello, w?: World, nav?: Nav, exp?: Exposure | null) {
    super(hello, w, nav, exp)
    this.name = "gang"
  }

  act(obs: Observation) {
    this.rush = false
    const a = super.act(obs)
    if (this.rush && this.me.energy > this.kn.RUSH_E) a.boost = true
    return a
  }

  /** the nearest laser we know of on our level inside the circle we must be in */
  laserGoal(obs: Observation, maxD: number): V2 | null {
    if (this.me.weapons.some((w) => w?.kind === "laser")) return null
    const pos = this.me.pos
    const zone = obs.zone
    const kn = this.kn
    const soon = this.t > zone.shrink_start - kn.ZONE_LEAD_S
    const C = soon ? zone.next_center : zone.center
    const R = soon ? zone.next_radius : zone.radius
    let goal: V2 | null = null
    let gs = maxD
    for (const [, p] of this.loot) {
      if (p.kind !== "laser" || Math.abs(p.pos[2] - pos[2]) > kn.LASER_DZ || d2(p.pos, C) > R - kn.ZONE_SAFE_M) continue
      const d = d2(p.pos, pos)
      if (d < gs) {
        gs = d
        goal = [p.pos[0], p.pos[1]]
      }
    }
    return goal
  }

  fight(obs: Observation, e: Foe, foes: Foe[], endgame: boolean) {
    const r = super.fight(obs, e, foes, endgame)
    // gun only: break off toward a laser close by, shooting on the way
    const goal = endgame ? null : this.laserGoal(obs, this.kn.LASER_GRAB_R)
    if (!goal) return r
    this.mode = "grab"
    this.rush = true
    return { ...r, move: this.steer(goal, obs), boost: this.me.energy > this.kn.RUSH_E }
  }

  peace(obs: Observation, endgame: boolean) {
    if (endgame || this.me.weapons.some((w) => w?.kind === "laser")) return super.peace(obs, endgame)
    // without a laser we lose every swarm fight: walk to the nearest one we know of, else search for one
    const pos = this.me.pos
    const t = this.t
    const zone = obs.zone
    const kn = this.kn
    const C = t > zone.shrink_start - kn.ZONE_LEAD_S ? zone.next_center : zone.center
    const R = t > zone.shrink_start - kn.ZONE_LEAD_S ? zone.next_radius : zone.radius
    let goal = this.laserGoal(obs, Infinity)
    if (!goal) {
      // the parent's peace, steered even when we drop it, as far5 8ed48da shipped (5.67 and 5.60 real); steering only the
      // kept goal (6d99b67) scored 5.38 to 5.40 real on the same far5, though the sim saw no change
      const base = super.peace(obs, endgame)
      if (this.mode === "loot" || this.mode === "cube" || this.mode === "farm") return base
      if (!this.search || d2(this.search, pos) < 15 || t > this.searchT || d2(this.search, C) > R - 20) {
        this.search = this.searchPoint(C, R)
        this.searchT = t + kn.SEARCH_S
      }
      goal = this.search
      this.mode = "search"
    } else {
      this.mode = "loot"
      this.rush = true
    }
    const move = this.steer(goal, obs)
    // look along the way: a sweep across it scored lower in the sim
    const ahead = Math.hypot(move[0], move[1]) > 0.3 ? Math.atan2(move[1], move[0]) : this.me.aim[0]
    // hit in the last 2 s: no aim, as far5 8ed48da shipped (5.67 and 5.60 real); facing the hit bearing here
    // (ef561c0) scored 5.38 real on the same far5, though the sim liked it
    const aim: V2 = [ahead, 0]
    return { move, aim: this.lastHit > t - 2 ? null : aim, fire: [false, false] as [boolean, boolean] }
  }

  /** open ground 80 to 160 m away inside the circle, away from enemies we know of and places we searched */
  searchPoint(C: number[], R: number): V2 {
    const pos = this.me.pos
    let best: V2 = [C[0], C[1]]
    let bs = Infinity
    for (let k = 0; k < 24; k++) {
      const ang = this.rng() * TAU
      const r = this.kn.SEARCH_MIN + this.rng() * this.kn.SEARCH_SPAN
      const x = pos[0] + Math.cos(ang) * r
      const y = pos[1] + Math.sin(ang) * r
      if (Math.hypot(x - C[0], y - C[1]) > R - 30 || this.w.clearAt(x, y) < 5) continue
      let s = this.rng() * 20
      for (const e of this.enemies.values()) if (this.t - e.seen < 20) s += Math.max(0, this.kn.SEARCH_AVOID_R - d2(e.pos, [x, y]))
      if (this.searched.some((p) => d2(p, [x, y]) < 60)) s += 80
      if (s < bs) {
        bs = s
        best = [x, y]
      }
    }
    this.searched.push(best)
    return best
  }
}
