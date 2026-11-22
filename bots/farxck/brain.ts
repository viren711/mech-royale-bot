// farxck: farx that counts the laser's cook-off in its fight odds. A laser hit on a mech holding a mortar deals +60%
// (`weapons.laser.cookoff`, protocol.md §6 laser), but kiter's dps() scores a loadout without its victim
// (bots/kiter/brain.ts dps, odds), so farx sees a mortar holder as no easier to kill than anyone else. Here our time to
// kill a mortar holder takes the extra laser damage, which moves the target pick and the retreat call toward it.
import { Brain as FarX } from "../farx/brain.ts"

type Base = new (...args: any[]) => FarX
type Foe = ReturnType<FarX["foes"]>[number]

const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

export function cookOff<B extends Base>(B: B) {
  return class extends B {
    odds(e: Foe) {
      const o = super.odds(e)
      const cook = this.cfg.weapons.laser.cookoff ?? 0
      if (cook <= 0 || e.hp <= 0 || !e.weapons.includes("mortar") || !this.myKinds().includes("laser")) return o
      // the distance and lightning short that kiter's odds() uses for our laser
      const [lo, hi] = this.band(e)
      const dd = clamp(d2(e.pos, this.me.pos), lo, hi)
      if (e.weapons.includes("lightning") && dd < this.cfg.weapons.lightning.range) return o
      const extra = this.dps(["laser"], dd, this.me.cubes, true) * cook
      // o.mine is e.hp over our damage per second
      return { ...o, mine: e.hp / (e.hp / o.mine + extra) }
    }
  }
}

export class Brain extends cookOff(FarX) {}
