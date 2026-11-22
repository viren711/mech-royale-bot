// farxr5: farx with no unstick jump in a fight or a retreat. The parent jumps and jets a random way after 1.5 s within
// 2.5 m of one spot (src/brain.ts:557-578), and dancing in a fight reads as stuck: 38 of farxw's 40 sim stuck reflexes
// had no wall ahead (sim/SCENARIOS.md:98). The move planner already scores blocked steps (bots/kiter/brain.ts:481).
import type { Action } from "../../src/mechfight.ts"
import { Brain as FarX } from "../farx/brain.ts"

type Base = new (...args: any[]) => FarX
type V2 = [number, number]

export function noStuck<B extends Base>(B: B) {
  return class extends B {
    unstick(mv: V2, act: Omit<Action, "tick">): V2 {
      if (this.mode !== "fight" && this.mode !== "retreat") return super.unstick(mv, act)
      const pos = this.me.pos
      this.stuckRef = [pos[0], pos[1]]
      this.stuckT = this.t
      this.unstickUntil = -1
      return mv
    }
  }
}

export class Brain extends noStuck(FarX) {}
