// each split variant plays its farx variant in practice and split (duo) once the field reads as the finals
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { splitOf, overrides } from "./brain.ts"
import { Brain as Split } from "../split/brain.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { Brain as St, stormLead } from "../farxst/brain.ts"
import { Brain as Bk, frontBack } from "../farxbk/brain.ts"
import { Brain as Dh } from "../farxdh/brain.ts"
import { Brain as Ck } from "../farxck/brain.ts"
import { Brain as Lc } from "../farxlc/brain.ts"
import { Brain as Bc2 } from "../farxbc2/brain.ts"
import { Brain as R2 } from "../farxr2/brain.ts"
import { Brain as Cap } from "../farxcap/brain.ts"
import { Brain as R4u } from "../farxr4u/brain.ts"
import { Brain as R5 } from "../farxr5/brain.ts"
import { Brain as Lv } from "../farxlv/brain.ts"
import { Brain as SplitLv } from "../splitlv/brain.ts"
import { Brain as SplitSb } from "../splitsb/brain.ts"
import { Brain as SplitAll, Practice as All } from "../splitall/brain.ts"
import { Brain as SplitDs, Practice as Ds } from "../splitds/brain.ts"

const lines = gunzipSync(readFileSync(new URL("../../check/stream.jsonl.gz", import.meta.url))).toString().split("\n").filter(Boolean).map((l) => JSON.parse(l))
const w = new World(new URL("../../arena", import.meta.url).pathname)
const nav = new Nav(w)
const obs = lines.filter((o) => o.type === "obs")
const play = (b: any, stream: any[]) => stream.map((o) => JSON.stringify(b.act(o)))
// the recorded stream with nobody dying: practice all the way
const practice = obs.map((o) => ({ ...o, alive: obs[0].alive }))
const at = (t: number, alive: number) => ({ ...obs[0], t, tick: Math.round(t * 20), alive, events: [] })

class Sb extends frontBack(stormLead(FarX)) {}
const cases: [string, any, any][] = [
  ["st", St, splitOf(St, "splitst")],
  ["bk", Bk, splitOf(Bk, "splitbk")],
  ["dh", Dh, splitOf(Dh, "splitdh")],
  ["ck", Ck, splitOf(Ck, "splitck")],
  ["lc", Lc, splitOf(Lc, "splitlc")],
  ["bc2", Bc2, splitOf(Bc2, "splitbc2")],
  ["r2", R2, splitOf(R2, "splitr2")],
  ["r4u", R4u, splitOf(R4u, "splitr4u")],
  ["r5", R5, splitOf(R5, "splitr5")],
  ["lv", Lv, SplitLv],
  ["sb", Sb, SplitSb],
  ["all", All, SplitAll],
  ["ds", Ds, SplitDs],
]

for (const [n, P, S] of cases) {
  test(`split${n}: in practice every decision is the variant's`, () => {
    const s = play(new S(lines[0], w, nav, null), practice)
    const p = play(new P(lines[0], w, nav, null), practice)
    expect(s).toEqual(p)
  })

  test(`split${n}: once the finals show, every decision is split's`, () => {
    const s = new S(lines[0], w, nav, null)
    const r = new Split(lines[0], w, nav, null)
    for (const o of [at(1, 16), at(20, 14)]) {
      s.act(o)
      r.act(o)
    }
    expect(s.finals).toBe(true)
    const late = obs.filter((o) => o.t > 20).map((o) => ({ ...o, alive: 14 }))
    expect(play(s, late)).toEqual(play(r, late))
  })
}

test("the variants differ from farx in practice, so the test above can fail", () => {
  const f = play(new FarX(lines[0], w, nav, null), practice)
  const differ = cases.filter(([, , S]) => JSON.stringify(play(new S(lines[0], w, nav, null), practice)) !== JSON.stringify(f)).map(([n]) => n)
  console.log("differ from farx on the stream:", differ.join(" "))
  expect(differ.length).toBeGreaterThan(0)
})

test("a variant that rewrites the observation in act is refused", () => {
  expect(overrides(Cap)).toContain("act")
  expect(() => splitOf(Cap, "splitcap")).toThrow()
})

test("each method a variant overrides goes to the variant in practice and to split in the finals", () => {
  class Mark extends Error {}
  for (const [n, P] of cases) {
    // a variant whose every override throws Mark, so a call reaching it is seen
    class Q extends P {}
    const names = overrides(P)
    for (const k of names) Object.defineProperty(Q.prototype, k, { value: () => { throw new Mark(k) }, writable: true, configurable: true })
    const S = splitOf(Q, `split${n}`) as any
    for (const k of names) {
      const call = (finals: boolean) => {
        try {
          S.prototype[k].call({ finals })
          return "other"
        } catch (e) {
          return e instanceof Mark ? "variant" : "other"
        }
      }
      expect(`${n}.${k} ${call(false)}`).toBe(`${n}.${k} variant`)
      const split = (Split.prototype as any)[k]
      expect(`${n}.${k} ${call(true)}`).toBe(`${n}.${k} ${split === undefined ? "variant" : "other"}`)
    }
  }
})
