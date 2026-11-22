// splitlv: split with farxlv (retreat leaves instead of walking to cover) in practice, duo in the finals
import { splitOf } from "../splitof/brain.ts"
import { Brain as P } from "../farxlv/brain.ts"

export const Brain = splitOf(P, "splitlv")
