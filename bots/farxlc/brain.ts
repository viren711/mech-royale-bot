// farxlc: farx that targets a mech charging a laser at us. Everyone who sees a charging laser sees `charging: true` and
// the holder's aim (protocol.md §3 mechs, §6 laser), and a full charge is 315 damage along that aim when it lets go. In
// pickTarget, a visible mech charging with its aim on us gets the credit of a mech that hit us in the last 2 s
// (HIT_BONUS, src/knobs.ts): the hit is about to land. Written from protocol.md.
import { Brain as FarX } from "../farx/brain.ts"

type Base = new (...args: any[]) => FarX
type Foe = ReturnType<FarX["foes"]>[number]

export function laserCharger<B extends Base>(B: B) {
  return class extends B {
    pickTarget(foes: Foe[], endgame: boolean): Foe | null {
      const on = foes.filter((e) => e.visible && e.charging && e.weapons.includes("laser") && this.aimedAtMe(e))
      if (on.length === 0) return super.pickTarget(foes, endgame)
      // kiter's pickTarget reads the credit from hitMeAt: stamp it for this call only
      const was = on.map((e) => [e.id, this.hitMeAt.get(e.id)] as const)
      for (const e of on) this.hitMeAt.set(e.id, this.t)
      try {
        return super.pickTarget(foes, endgame)
      } finally {
        for (const [id, at] of was) {
          if (at === undefined) this.hitMeAt.delete(id)
          else this.hitMeAt.set(id, at)
        }
      }
    }
  }
}

export class Brain extends laserCharger(FarX) {}
