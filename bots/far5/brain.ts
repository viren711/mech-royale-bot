// Gang that holds the long band: house guns and lasers miss past 80 m (sim and replay agree on the gun: 0.56 at 60-90 m,
// 0.27 at 90-120 m) while ours still hit, so against laser or mortar holders and whenever two foes are on us it keeps
// 90-130 m or more instead of closing to 25-70 m. Lightning bands (we carry it, fight inside 45 m) are left alone.
import type { Observation } from "../../src/mechfight.ts"
import { Brain as Gang } from "../gang/brain.ts"

type V2 = [number, number]
type Foe = ReturnType<Gang["foes"]>[number]
const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])

export class Brain extends Gang {
  crowd = 0

  fight(obs: Observation, e: Foe, foes: Foe[], endgame: boolean) {
    const pos = this.me.pos
    this.crowd = foes.filter((f) => f.visible && d2(f.pos, pos) < this.kn.CROWD_R).length
    return super.fight(obs, e, foes, endgame)
  }

  band(e: Foe): [number, number] {
    const b = super.band(e)
    if (this.myKinds().includes("lightning") && b[0] < 20) return b
    const eL = e.weapons.includes("laser"), eM = e.weapons.includes("mortar")
    if (!eL && !eM && this.crowd < this.kn.CROWD_N) return b
    return [Math.max(b[0], this.kn.LONG_LO), Math.max(b[1], this.kn.LONG_HI)]
  }

  /** run f with pickups on a roof taller than a step above us forgotten: out of reach on foot, walking at one pins us to the wall foot */
  reachable<T>(f: () => T): T {
    const step = this.cfg.mech.step_up ?? 1.2
    const z = this.me.pos[2]
    const hidden: [number, { kind: string; pos: number[] }][] = []
    for (const [id, p] of this.loot) {
      if (p.pos[2] - z > step && p.pos[2] - this.w.groundAt(p.pos[0], p.pos[1]) > step) hidden.push([id, p])
    }
    for (const [id] of hidden) this.loot.delete(id)
    try {
      return f()
    } finally {
      for (const [id, p] of hidden) this.loot.set(id, p)
    }
  }

  laserGoal(obs: Observation, maxD: number): V2 | null {
    return this.reachable(() => super.laserGoal(obs, maxD))
  }

  peace(obs: Observation, endgame: boolean) {
    return this.reachable(() => super.peace(obs, endgame))
  }

  /** inside a building footprint (a roof) every planned step is blocked and all candidates tie on the first, due east */
  planMove(obs: Observation, e: Foe, watchers: Foe[], band: [number, number], retreat: boolean, cover: V2 | null, charging: boolean) {
    const best = super.planMove(obs, e, watchers, band, retreat, cover, charging)
    const pos = this.me.pos
    const R = this.me.stats.radius ?? this.cfg.mech.radius
    if (this.w.clearAt(pos[0], pos[1]) >= R * 0.95) return best
    // away from the target when retreating, else toward where the circle is going
    const C = obs.zone.next_center ?? obs.zone.center
    const to = retreat ? [pos[0] - e.pos[0], pos[1] - e.pos[1]] : [C[0] - pos[0], C[1] - pos[1]]
    const len = Math.hypot(to[0], to[1])
    if (len < 1) return { move: [0, 0] as V2, boost: false }
    return { move: [to[0] / len, to[1] / len] as V2, boost: false }
  }
}
