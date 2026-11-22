// farxdh: farx that shoots the drop holder. A mech capturing a landed supply drop has to stay inside its 8 m ring alone
// for 4 s (protocol.md §7 Supply drops), and obs.drops[].holder names it (protocol.md §6), so it is a target that
// cannot kite. While a holder is in sight and inside our longest weapon's range, it is our target over farx's pick.
import type { Observation } from "../../src/mechfight.ts"
import { Brain as FarX } from "../farx/brain.ts"

type Base = new (...args: any[]) => FarX
type Foe = ReturnType<FarX["foes"]>[number]

const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])

export function dropHolder<B extends Base>(B: B) {
  return class extends B {
    holders = new Set<number>()

    track(obs: Observation) {
      super.track(obs)
      this.holders = new Set(obs.drops.filter((d) => d.holder !== null && d.lands_in <= 0).map((d) => d.holder as number))
    }

    /** the nearest holder we see, have a line to and outrange */
    holderTarget(foes: Foe[]): Foe | null {
      if (this.holders.size === 0) return null
      const me = this.me
      const reach = Math.max(0, ...me.weapons.map((w) => w?.stats.range ?? 0))
      let best: Foe | null = null
      let bd = reach
      for (const e of foes) {
        if (!this.holders.has(e.id) || !e.visible) continue
        const d = d2(e.pos, me.pos)
        if (d < bd && this.hasLos(this.bodyOf(e))) {
          bd = d
          best = e
        }
      }
      return best
    }

    pickTarget(foes: Foe[], endgame: boolean): Foe | null {
      const h = this.holderTarget(foes)
      if (!h) return super.pickTarget(foes, endgame)
      this.focus = h.id
      return h
    }
  }
}

export class Brain extends dropHolder(FarX) {}
