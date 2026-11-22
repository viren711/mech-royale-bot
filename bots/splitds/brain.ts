// splitds: split with farxdh (drop-holder target) and farxst (zone-edge lead) in practice, the two the board-score
// predictor ranks first among the farx lanes (sim/PREDICT.md), duo in the finals
import { splitOf } from "../splitof/brain.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { stormLead } from "../farxst/brain.ts"
import { dropHolder } from "../farxdh/brain.ts"

export class Practice extends dropHolder(stormLead(FarX)) {}

export const Brain = splitOf(Practice, "splitds")
