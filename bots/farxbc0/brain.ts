// farxbc0: farx with the move planner's boosted-move cost BOOST_COST (src/knobs.ts, read in bots/kiter/brain.ts planMove) at 0
// instead of 4: a lower cost boosts more of the fight moves, a higher one fewer.
import { KNOB_DEFAULTS } from "../../src/knobs.ts"
import { Brain as FarX } from "../farx/brain.ts"

export class Brain extends FarX {
  static knobs = { ...KNOB_DEFAULTS, BOOST_COST: 0 }
}
