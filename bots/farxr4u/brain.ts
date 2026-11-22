// farxr4u: farx that opens on an unaware mech from range when the laser is ready and nobody else is close. farx starts
// on an unaware mech past 75 m only when no other foe is within 200 m (bots/kiter/brain.ts:232-233), which with 15 house
// bots almost never holds, so it leaves the first shot to them. The name farxr4 was taken (a race-window constant).
import { Brain as FarX } from "../farx/brain.ts"

type Base = new (...args: any[]) => FarX
type Foe = ReturnType<FarX["foes"]>[number]

const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])
// an unaware mech is still free with the nearest other foe past this
const AMBUSH_R = 80

export function ambush<B extends Base>(B: B) {
  return class extends B {
    /** a laser in hand that can start a charge now */
    laserReady(): boolean {
      const L = this.me.weapons.find((w) => w?.kind === "laser")
      return !!L && L.cooldown <= 0.1 && this.myKinds().includes("laser")
    }

    /** the kiter's pick (bots/kiter/brain.ts:221), with `free` also true when the laser is ready and the nearest other foe is past AMBUSH_R */
    pickTarget(foes: Foe[], endgame: boolean): Foe | null {
      const me = this.me
      const kn = this.kn
      const ready = this.laserReady()
      let best: Foe | null = null
      let bs = Infinity
      for (const e of foes) {
        const d = d2(e.pos, me.pos)
        if (d > kn.TARGET_R) continue
        const o = this.odds(e)
        const aware = this.aware(e)
        const others = foes.filter((f) => f !== e && d2(f.pos, me.pos) < kn.THREAT_R).length
        const nearest = Math.min(Infinity, ...foes.filter((f) => f !== e).map((f) => d2(f.pos, me.pos)))
        const alone = others === 0 || (ready && nearest > AMBUSH_R)
        const free = !aware && o.mine * kn.FREE_ODDS < o.theirs && me.hp > me.max_hp * 0.5 && alone && this.myKinds().length > 1
        const weakPrey = !aware && e.hp < kn.WEAK_HP && o.mine < o.theirs && d < kn.WEAK_R
        if (!this.k.aggro && !aware && !free && !weakPrey && !endgame && d > kn.ENGAGE_R) continue
        let s = o.mine - o.theirs * kn.ODDS_THEIRS_W + d / kn.TARGET_DIST_M
        if (this.t - (this.hitMeAt.get(e.id) ?? -99) < 2) s -= kn.HIT_BONUS
        if (this.focus === e.id) s -= kn.FOCUS_BONUS
        if (s < bs) {
          bs = s
          best = e
        }
      }
      this.focus = best ? best.id : null
      return best
    }
  }
}

export class Brain extends ambush(FarX) {}
