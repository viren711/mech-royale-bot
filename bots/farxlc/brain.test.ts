// farxlc gives a mech that charges a laser aimed at us (`charging` and `aim` in obs.mechs, protocol.md §3) the target
// credit of one that just hit us, so it takes that mech over one farx prefers; a charge aimed elsewhere, or none, picks as farx.
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { Brain as Lc } from "./brain.ts"

const lines = gunzipSync(readFileSync(new URL("../../check/stream.jsonl.gz", import.meta.url))).toString().split("\n").filter(Boolean).map((l) => JSON.parse(l))
const w = new World(new URL("../../arena", import.meta.url).pathname)
const nav = new Nav(w)
const hello = lines[0]
const base = lines.find((o) => o.type === "obs" && o.mechs.length > 0)
const gun = base.self.weapons[0]
const laser = { kind: "laser", cooldown: 0, charge: 0, stats: hello.config.weapons.laser }
const pos = base.self.pos
const at = (a: number, d: number) => [pos[0] + Math.cos(a) * d, pos[1] + Math.sin(a) * d, pos[2]]
// a laser holder d m away along bearing a, aiming back at us, off by `off` radians
const foe = (id: number, a: number, hp: number, charging: boolean, off = 0) => ({ id, kind: "mech", pos: at(a, 100), vel: [0, 0, 0], aim: [a + Math.PI + off, 0], hp, max_hp: 1400, cubes: 0, weapons: ["gun", "laser"], charging })
const obs = (mechs: any[]) => ({ ...base, mechs, pickups: [], crates: [], cubes: [], events: [], self: { ...base.self, weapons: [gun, laser], hp: 1400, max_hp: 1400, cubes: 0 } })
const focus = (B: any, o: any) => {
  const b = new B(hello, w, nav, null)
  b.until = Infinity
  b.act(o)
  return b.focus
}
// at the same range: a full-HP laser holder, and one at 1200 HP that farx would rather take
const weaker = foe(4, 0.3 + Math.PI / 2, 1200, false)

test("a laser charging at us is the target, where farx takes the weaker mech", () => {
  const o = obs([foe(3, 0.3, 1400, true), weaker])
  expect(focus(FarX, o)).toBe(weaker.id)
  expect(focus(Lc, o)).toBe(3)
})

test("the charge leaves no hit behind: the hit memory after the pick is farx's", () => {
  const o = obs([foe(3, 0.3, 1400, true), weaker])
  const memory = (B: any) => {
    const b = new B(hello, w, nav, null)
    b.until = Infinity
    b.act(o)
    return [...b.hitMeAt]
  }
  expect(memory(Lc)).toEqual(memory(FarX))
})

test("no charge, or a charge aimed 0.4 rad off us: the pick is farx's", () => {
  for (const a of [foe(3, 0.3, 1400, false), foe(3, 0.3, 1400, true, 0.4)]) {
    const o = obs([a, weaker])
    expect(focus(Lc, o)).toBe(focus(FarX, o))
  }
})
