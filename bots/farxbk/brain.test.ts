// farxbk: retreating with the nearest attacker outside the torso's front arc, it turns its front to that attacker;
// otherwise it acts as farx does.
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { Brain as Bk } from "./brain.ts"

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
const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a))
// our target 100 m ahead, aiming at us; hp: ours of 1400
const obs = (hp: number, events: any[]) => ({
  ...base,
  mechs: [{ id: 9, kind: "mech", pos: along(pos, open, 100), vel: [0, 0, 0], aim: [open + Math.PI, 0], hp: 1400, max_hp: 1400, cubes: 0, weapons: ["gun"], charging: false }],
  pickups: [],
  crates: [],
  cubes: [],
  events,
  self: { ...base.self, pos, vel: [0, 0, 0], aim: [open, 0], hp, max_hp: 1400, weapons: [base.self.weapons[0], null] },
  zone: { ...base.zone, center: [pos[0], pos[1]], next_center: [pos[0], pos[1]], radius: 190, next_radius: 190, shrink_start: 999, shrink_end: 1000 },
})
// an unseen mech hit us from this bearing
const hitFrom = (b: number) => [{ type: "damaged", amount: 45, weapon: "gun", bearing: b, by: 11, rear: true }]
const make = (B: any) => new B(hello, w, nav, null)
const act = (b: any, o: any) => {
  b.until = Infinity
  return b.act(o)
}

test("retreating, an attacker hitting us from behind gets our front while farx keeps aiming at its target", () => {
  const o = obs(300, hitFrom(open + Math.PI))
  const farx = make(FarX)
  const fa = act(farx, o)
  expect(farx.mode).toBe("retreat")
  expect(Math.abs(wrap(fa.aim[0] - open))).toBeLessThan(0.3)
  const bk = make(Bk)
  const ba = act(bk, o)
  expect(bk.mode).toBe("retreat")
  expect(Math.abs(wrap(ba.aim[0] - (open + Math.PI)))).toBeLessThan(0.05)
  expect(ba.move).toEqual(fa.move)
})

test("retreating, a seen attacker 90 m behind gets our front and our gun while farx aims at its target 60 m ahead", () => {
  const o = obs(300, hitFrom(open + Math.PI))
  o.mechs[0].pos = along(pos, open, 60)
  o.mechs.push({ ...o.mechs[0], id: 11, pos: along(pos, open + Math.PI, 90), aim: [open, 0] })
  const farx = make(FarX)
  const fa = act(farx, o)
  expect(farx.mode).toBe("retreat")
  expect(Math.abs(wrap(fa.aim[0] - open))).toBeLessThan(0.3)
  const bk = make(Bk)
  const ba = act(bk, o)
  expect(Math.abs(wrap(ba.aim[0] - (open + Math.PI)))).toBeLessThan(0.05)
  // the gun plan is the attacker's: farx's shot at the target ahead is held while the torso turns away from it
  expect(fa.fire[0]).toBe(true)
  expect(ba.fire[0]).toBe(false)
  expect(ba.move).toEqual(fa.move)
})

test("retreating, a hit from behind 3 s ago (past the 2.5 s hit memory): farx's action", () => {
  const farx = make(FarX)
  const bk = make(Bk)
  const o1 = obs(300, hitFrom(open + Math.PI))
  act(farx, o1)
  act(bk, o1)
  const o2 = { ...obs(300, []), tick: base.tick + 60, t: base.t + 3 }
  expect(act(bk, o2)).toEqual(act(farx, o2))
  expect(farx.mode).toBe("retreat")
})

for (const [why, hp, from] of [
  ["not retreating (full HP)", 1400, open + Math.PI],
  ["retreating, the attacker already inside the front arc", 300, open + 0.8],
  ["retreating, nobody hitting us but the target", 300, null],
] as const) {
  test(`${why}: farx's action`, () => {
    const o = obs(hp, from === null ? [] : hitFrom(from))
    const farx = make(FarX)
    const want = act(farx, o)
    const bk = make(Bk)
    expect(act(bk, o)).toEqual(want)
    expect(bk.mode).toBe(farx.mode)
  })
}
