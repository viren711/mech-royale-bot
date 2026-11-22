// farxbc0/1/2/3/5/6 are farx with the planner's boosted-move cost BOOST_COST (src/knobs.ts, 4 in farx) set to 0, 1, 2, 3, 5 and 6:
// across the same fights a cheaper boost boosts at least as often, and in peace, where the cost is not read, the
// action is farx's.
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { Brain as Bc2 } from "./brain.ts"
import { Brain as Bc3 } from "../farxbc3/brain.ts"
import { Brain as Bc5 } from "../farxbc5/brain.ts"
import { Brain as Bc6 } from "../farxbc6/brain.ts"
import { Brain as Bc0 } from "../farxbc0/brain.ts"
import { Brain as Bc1 } from "../farxbc1/brain.ts"

const lines = gunzipSync(readFileSync(new URL("../../check/stream.jsonl.gz", import.meta.url))).toString().split("\n").filter(Boolean).map((l) => JSON.parse(l))
const w = new World(new URL("../../arena", import.meta.url).pathname)
const nav = new Nav(w)
const hello = lines[0]
const fights = lines.filter((o) => o.type === "obs" && o.mechs.some((m: any) => m.kind === "mech"))
const peace = lines.filter((o) => o.type === "obs" && o.mechs.length === 0).slice(0, 40)
const make = (B: any) => {
  const b = new B(hello, w, nav, null)
  b.until = Infinity
  return b
}
// the recorded fight ticks replayed at several energy levels and HP fractions, fresh brain per tick
const boosts = (B: any) => {
  let n = 0
  for (const o of fights) for (const energy of [20, 50, 90]) for (const hp of [500, 1400]) {
    if (make(B).act({ ...o, self: { ...o.self, energy, hp } }).boost) n++
  }
  return n
}

test("a cheaper boost cost boosts at least as often in the same fights, and 2 more often than 6", () => {
  const n = [Bc0, Bc1, Bc2, Bc3, FarX, Bc5, Bc6].map(boosts)
  for (let i = 1; i < n.length; i++) expect(n[i - 1]).toBeGreaterThanOrEqual(n[i])
  expect(n[0]).toBeGreaterThan(n[6])
})

test("in peace the action is farx's", () => {
  for (const B of [Bc0, Bc1, Bc2, Bc3, Bc5, Bc6]) {
    const f = make(FarX)
    const b = make(B)
    for (const o of peace) expect(b.act(o)).toEqual(f.act(o))
  }
})
