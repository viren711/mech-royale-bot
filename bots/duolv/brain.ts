// duolv: duo whose retreat leaves instead of walking to cover from its target, as farxlv (bots/farxlv) does for farx
import { knobsFromEnv } from "../../src/knobs.ts"
import { Brain as Duo } from "../duo/brain.ts"

export class Brain extends Duo {
  // KNOB_<NAME> in env moves a knob over these, for sweeps on the sim
  static knobs = knobsFromEnv({ KNOB_COVER_R: "0", ...process.env })
}
