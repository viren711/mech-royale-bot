// farxdh: a mech capturing a landed supply drop (obs.drops[].holder), in sight and in range, is our target over farx's
// pick; with no such holder it picks as farx does.
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { Brain as Dh } from "./brain.ts"

const lines = gunzipSync(readFileSync(new URL("../../check/stream.jsonl.gz", import.meta.url))).toString().split("\n").filter(Boolean).map((l) => JSON.parse(l))
const w = new World(new URL("../../arena", import.meta.url).pathname)
const nav = new Nav(w)
const hello = lines[0]
const base = lines.find((o) => o.type === "obs" && o.mechs.length > 0)
const along = (p: number[], a: number, d: number) => {
  const x = p[0] + Math.cos(a) * d
  const y = p[1] + Math.sin(a) * d
  return [x, y, w.floorAt(x, y)]
}
const clear = (p: number[], a: number) => {
  const q = along(p, a, 120)
  return w.clearAt(q[0], q[1]) > 5 && w.los(p[0], p[1], p[2] + 8, q[0], q[1], q[2] + 0.5) && w.canopyCover(p[0], p[1], p[2] + 8, q[0], q[1], q[2] + 0.5) === 0
}
// open ground with a clear 120 m line ahead and behind
const [pos, open] = (() => {
  for (let x = -400; x <= 400; x += 23) for (let y = -300; y <= 300; y += 23) {
    const p = [x, y, w.floorAt(x, y)]
    if (w.clearAt(x, y) < 5) continue
    for (let k = 0; k < 32; k++) {
      const a = (k / 32) * Math.PI * 2
      if (clear(p, a) && clear(p, a + Math.PI)) return [p, a] as const
    }
  }
  throw new Error("no open line")
})()
const mech = (id: number, at: number[], yaw: number) => ({ id, kind: "mech", pos: at, vel: [0, 0, 0], aim: [yaw, 0], hp: 1400, max_hp: 1400, cubes: 0, weapons: ["gun"], charging: false })
// mech 8 is 60 m ahead aiming at us; mech 7 is 110 m behind facing away; the drop's ring is around mech 7
const obs = (drop: { holder: number | null; lands_in: number }) => ({
  ...base,
  mechs: [mech(8, along(pos, open, 60), open + Math.PI), mech(7, along(pos, open + Math.PI, 110), open + Math.PI)],
  pickups: [],
  crates: [],
  cubes: [],
  events: [],
  drops: [{ id: 20000, pos: along(pos, open + Math.PI, 110), radius: 8, capture_s: 4, progress: 1.5, ...drop }],
  self: { ...base.self, pos, vel: [0, 0, 0], aim: [open, 0], hp: 1400, max_hp: 1400, weapons: [base.self.weapons[0], null] },
  zone: { ...base.zone, center: [pos[0], pos[1]], next_center: [pos[0], pos[1]], radius: 400, next_radius: 400, shrink_start: 999, shrink_end: 1000 },
})
const pick = (B: any, ...frames: any[]) => {
  const b = new B(hello, w, nav, null)
  b.until = Infinity
  for (const o of frames) b.act(o)
  return b.focus
}
// a bearing where a mech 100 m out stands behind cover from our muzzle
const hidden = (() => {
  for (let k = 0; k < 64; k++) {
    const a = (k / 64) * Math.PI * 2
    const q = along(pos, a, 100)
    if (!w.los(pos[0], pos[1], pos[2] + 7, q[0], q[1], q[2] + 7)) return q
  }
  throw new Error("no cover around")
})()

test("farx picks the mech aiming at us while a holder captures a drop behind us", () => {
  expect(pick(FarX, obs({ holder: 7, lands_in: 0 }))).toBe(8)
})

test("the holder of a landed drop, in sight and in gun range, is our target", () => {
  expect(pick(Dh, obs({ holder: 7, lands_in: 0 }))).toBe(7)
})

test("with no holder, or a drop still falling, we pick as farx does", () => {
  expect(pick(Dh, obs({ holder: null, lands_in: 0 }))).toBe(8)
  expect(pick(Dh, obs({ holder: 7, lands_in: 3 }))).toBe(8)
})

test("a holder past our gun's range is left alone", () => {
  const o = obs({ holder: 7, lands_in: 0 })
  const gun = o.self.weapons[0]
  o.self.weapons = [{ ...gun, stats: { ...gun.stats, range: 100 } }, null]
  expect(pick(Dh, o)).toBe(8)
})

test("a holder we saw a moment ago but no longer see is left alone", () => {
  const o = obs({ holder: 7, lands_in: 0 })
  const later = { ...o, tick: o.tick + 10, t: o.t + 0.5, mechs: [o.mechs[0]] }
  expect(pick(Dh, o, later)).toBe(8)
})

test("a holder behind cover is left alone", () => {
  const o = obs({ holder: 7, lands_in: 0 })
  o.mechs[1].pos = hidden
  o.drops[0].pos = hidden
  expect(pick(Dh, o)).toBe(8)
})
