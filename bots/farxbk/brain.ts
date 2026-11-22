// farxbk: farx that, while retreating, turns its torso to the nearest mech that hit us when that one is outside the front
// arc. Legs and torso are independent (protocol.md §4 action, `move`), so the retreat path stays farx's. A hit from outside
// the front arc deals x1.5 (protocol.md "Rear armor"), and farx keeps aiming at its target while others hit it from
// behind: in the squad sim 14.7% of the damage farx takes in retreat is a rear hit (400 matches).
import type { Observation } from "../../src/mechfight.ts"
import type { Brain as Kiter } from "../kiter/brain.ts"
import { Brain as FarX } from "../farx/brain.ts"

// any brain on the kiter's fight: farx, duo, split
type Base = new (...args: any[]) => Kiter
type Foe = ReturnType<Kiter["foes"]>[number]

const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])
const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a))
// an unseen shooter's assumed range, as farm's threats take it (bots/farm/brain.ts:51)
const UNSEEN_D = 70
// turn before the attacker leaves the arc: torso slew and the 7° bearing noise
const MARGIN = (20 * Math.PI) / 180

export function frontBack<B extends Base>(B: B) {
  return class extends B {
    fight(obs: Observation, e: Foe, foes: Foe[], endgame: boolean) {
      const r = super.fight(obs, e, foes, endgame)
      if (this.mode !== "retreat") return r
      const pos = this.me.pos
      let near: Foe | null = null
      let brg = 0
      let bd = Infinity
      for (const [id, at] of this.hitMeAt) {
        if (this.t - at > this.kn.HIT_MEMORY_S) continue
        const f = foes.find((x) => x.id === id) ?? null
        const d = f ? d2(f.pos, pos) : UNSEEN_D
        if (d >= bd) continue
        bd = d
        near = f
        brg = f ? Math.atan2(f.pos[1] - pos[1], f.pos[0] - pos[0]) : this.hitMeFrom.get(id) ?? r.aim[0]
      }
      const half = (this.cfg.mech.front_arc_deg * Math.PI) / 360 - MARGIN
      if (bd === Infinity || Math.abs(wrap(brg - r.aim[0])) < half) return r
      if (near?.visible) {
        const w = this.weaponsPlan(this.bodyOf(near), bd, near, true)
        if (w.los) return { ...r, aim: w.aim, fire: w.fire }
      }
      return { ...r, aim: [brg, r.aim[1]] }
    }
  }
}

export class Brain extends frontBack(FarX) {}
