// splitlvr5: split with farxr5 (no unstick jump in a fight or a retreat) plus farxlv's leave-instead-of-cover retreat (COVER_R 0) in practice, duo in the finals
import { splitOf } from "../splitof/brain.ts"
import { KNOB_DEFAULTS } from "../../src/knobs.ts"
import { Brain as B } from "../farxr5/brain.ts"

export class Practice extends B {
  static knobs = { ...((B as any).knobs ?? KNOB_DEFAULTS), COVER_R: 0 }
}

export const Brain = splitOf(Practice, "splitlvr5")
