// splitsb: split with farxst and farxbk together in practice, duo in the finals
import { splitOf } from "../splitof/brain.ts"
import { stormLead } from "../farxst/brain.ts"
import { frontBack } from "../farxbk/brain.ts"
import { Brain as FarX } from "../farx/brain.ts"

class P extends frontBack(stormLead(FarX)) {}

export const Brain = splitOf(P, "splitsb")
