// splitall: split with every own farx lane that composes in practice (farxst zone-edge lead, farxbk torso to the
// attacker, farxdh drop-holder target, farxck laser cook-off odds, farxlc laser-charger bonus), duo in the finals
import { splitOf } from "../splitof/brain.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { stormLead } from "../farxst/brain.ts"
import { frontBack } from "../farxbk/brain.ts"
import { dropHolder } from "../farxdh/brain.ts"
import { cookOff } from "../farxck/brain.ts"
import { laserCharger } from "../farxlc/brain.ts"

export class Practice extends laserCharger(cookOff(dropHolder(frontBack(stormLead(FarX))))) {}

export const Brain = splitOf(Practice, "splitall")
