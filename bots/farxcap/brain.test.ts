// farxcap walks to no cube once it holds stat_cap (10) cubes, and walks to them as farx does below it.
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { Brain as Cap } from "./brain.ts"

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
const obs = (cubes: number, over: any) => ({
  ...base,
  mechs: [],
  pickups: [],
  crates: [],
  cubes: [],
  events: [],
  self: { ...base.self, pos, vel: [0, 0, 0], aim: [open, 0], weapons: [base.self.weapons[0], null], cubes },
  zone: { ...base.zone, center: [pos[0], pos[1]], next_center: [pos[0], pos[1]], radius: 190, next_radius: 190, shrink_start: 999, shrink_end: 1000 },
  ...over,
})
const make = (B: any) => new B(hello, w, nav, null)
const act = (b: any, o: any) => {
  b.until = Infinity
  return b.act(o)
}
const dot = (m: number[], a: number) => m[0] * Math.cos(a) + m[1] * Math.sin(a)
const behind = open + Math.PI
// an aware mech 100 m ahead, aiming at us
const enemy = { id: 9, kind: "mech", pos: along(pos, open, 100), vel: [0, 0, 0], aim: [behind, 0], hp: 1400, max_hp: 1400, cubes: 0, weapons: ["gun"], charging: false }

for (const [mode, dist, mechs] of [["peace", 60, []], ["fight", 20, [enemy]]] as const) {
  test(`${mode}: a cube ${dist} m behind is walked to with 9 cubes, and at 10 the action is farx's with no cube in sight`, () => {
    const cube = { id: 5001, pos: along(pos, behind, dist) }
    const below = obs(9, { mechs, cubes: [cube] })
    expect(dot(act(make(Cap), below).move, behind)).toBeGreaterThan(0.9)
    const cap = make(Cap)
    const a = act(cap, obs(10, { mechs, cubes: [cube] }))
    expect(dot(a.move, behind)).toBeLessThan(0.5)
    expect(a).toEqual(act(make(FarX), obs(10, { mechs, cubes: [] })))
  })
}
