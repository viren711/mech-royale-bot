// farxck counts the laser's cook-off (+60% on a mech holding a mortar, protocol.md §6 laser) in its kill time, so of two
// foes it takes the mortar holder that farx passes over; with no laser, or no mortar in sight, it picks as farx does.
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { Brain as Ck } from "./brain.ts"

const lines = gunzipSync(readFileSync(new URL("../../check/stream.jsonl.gz", import.meta.url))).toString().split("\n").filter(Boolean).map((l) => JSON.parse(l))
const w = new World(new URL("../../arena", import.meta.url).pathname)
const nav = new Nav(w)
const hello = lines[0]
const base = lines.find((o) => o.type === "obs" && o.mechs.length > 0)
const gun = base.self.weapons[0]
const laser = { kind: "laser", cooldown: 0, charge: 0, stats: hello.config.weapons.laser }
const pos = base.self.pos
const at = (a: number, d: number) => [pos[0] + Math.cos(a) * d, pos[1] + Math.sin(a) * d, pos[2]]
// an aware mech d m away along bearing a, aiming back at us
const foe = (id: number, a: number, d: number, hp: number, weapons: string[]) => ({ id, kind: "mech", pos: at(a, d), vel: [0, 0, 0], aim: [a + Math.PI, 0], hp, max_hp: 1400, cubes: 0, weapons, charging: false })
const obs = (mine: any[], mechs: any[]) => ({ ...base, mechs, pickups: [], crates: [], cubes: [], events: [], self: { ...base.self, weapons: mine, hp: 1400, max_hp: 1400, cubes: 0 } })
const played = (B: any, o: any) => {
  const b = new B(hello, w, nav, null)
  b.until = Infinity
  b.act(o)
  return b
}
const focus = (B: any, o: any) => played(B, o).focus
// same range: a mortar holder at full HP, and a laser holder at 400 HP that farx would rather finish
const mortar = foe(3, 0.3, 100, 1400, ["gun", "mortar"])
const plain = foe(4, 0.3 + Math.PI / 2, 100, 400, ["gun", "laser"])

test("holding a laser: the mortar holder is the target, where farx takes the weak laser holder", () => {
  const o = obs([gun, laser], [mortar, plain])
  expect(focus(FarX, o)).toBe(plain.id)
  expect(focus(Ck, o)).toBe(mortar.id)
})

test("no laser, or no mortar holder: the pick is farx's", () => {
  const noLaser = obs([gun, null], [mortar, plain])
  expect(focus(Ck, noLaser)).toBe(focus(FarX, noLaser))
  // a laser holder at full HP and one at 1200: close enough that a cook-off on the first would flip the pick
  const noMortar = obs([gun, laser], [{ ...mortar, weapons: ["gun", "laser"] }, { ...plain, hp: 1200 }])
  expect(focus(FarX, noMortar)).toBe(plain.id)
  expect(focus(Ck, noMortar)).toBe(plain.id)
  // and the kill times farx reckons, foe by foe
  const f = played(FarX, noMortar)
  const c = played(Ck, noMortar)
  for (const e of f.foes()) expect(c.odds(e)).toEqual(f.odds(e))
})
