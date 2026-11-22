// farxlv: farx whose retreat leaves instead of walking to cover from its target. farm's retreat (bots/farm/brain.ts:68)
// steers to a spot out of the target's sight within COVER_R; with COVER_R 0 it finds none, and the move planner's
// retreat scores alone pick the step: out of every attacker's sight and farther from each (bots/kiter/brain.ts:532-538).
// In the sim cells (sim/PREDICT.md), paired against farx: +0.10 ± 0.03 points over 720 matches (seeds 1-240) on the
// Mac, +0.20 ± 0.05 over 432 (seeds 1-144) on vast. farxp5's pressure trigger on top of it added nothing.
import { knobsFromEnv } from "../../src/knobs.ts"
import { Brain as FarX } from "../farx/brain.ts"

export class Brain extends FarX {
  // KNOB_<NAME> in env moves a knob over these, for sweeps on the sim
  static knobs = knobsFromEnv({ KNOB_COVER_R: "0", ...process.env })
}
