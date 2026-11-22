// splitOf(P): split (bots/split) with a farx variant P in the practice slot. Until the field reads as the finals
// (src/mode.ts) every method P adds or overrides over farx runs P's, and P's knobs and fields are ours; once it reads
// as the finals those calls go back to split, which is duo there. P may not override act: split keeps duo's act in both
// modes (duo's FfaWatch has to see every observation), so a variant that rewrites the observation has no slot here.
import type { Hello, Observation } from "../../src/mechfight.ts"
import type { World } from "../../src/world.ts"
import type { Nav } from "../../src/nav.ts"
import type { Exposure } from "../../src/exposure.ts"
import type { Knobs } from "../../src/knobs.ts"
import { Brain as Split } from "../split/brain.ts"
import { Brain as FarX } from "../farx/brain.ts"

type Practice = new (hello: Hello, w?: World, nav?: Nav, exp?: Exposure | null) => FarX

/** every method name P's own classes define above farx */
export function overrides(P: Practice): string[] {
  const names = new Set<string>()
  for (let pr = P.prototype; pr && pr !== FarX.prototype; pr = Object.getPrototypeOf(pr)) {
    for (const k of Object.getOwnPropertyNames(pr)) if (k !== "constructor" && typeof (pr as any)[k] === "function") names.add(k)
  }
  return [...names]
}

export function splitOf(P: Practice, name: string) {
  const names = overrides(P)
  if (names.includes("act")) throw new Error(`splitOf: ${name} overrides act`)
  class S extends Split {
    practiceKn: Knobs
    finalsKn: Knobs

    constructor(hello: Hello, w?: World, nav?: Nav, exp?: Exposure | null) {
      super(hello, w, nav, exp)
      // P's own fields (its state), taken from a P built on our world, nav and exposure
      const p = new P(hello, this.w, this.nav, this.exp) as any
      for (const k of Object.keys(p)) if (!(k in this)) (this as any)[k] = p[k]
      this.practiceKn = p.kn
      this.finalsKn = this.kn
      this.kn = this.practiceKn
      this.name = name
    }

    act(obs: Observation) {
      const a = super.act(obs)
      // the knobs for the next decision; the mode is decided inside split's act
      this.kn = this.finals ? this.finalsKn : this.practiceKn
      return a
    }
  }
  for (const k of names) {
    const mine = (P.prototype as any)[k]
    const theirs = (Split.prototype as any)[k]
    Object.defineProperty(S.prototype, k, {
      configurable: true,
      writable: true,
      value: theirs === undefined ? mine : function (this: S, ...a: unknown[]) {
        return (this.finals ? theirs : mine).apply(this, a)
      },
    })
  }
  return S
}
