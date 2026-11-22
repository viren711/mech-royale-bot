// farxst: retreating from a chaser with the circle's edge near, we run toward a line just inside the edge; otherwise we
// move as farx does.
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { Brain as St } from "./brain.ts"

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
  for (const d of [40, 80, 120]) {
    const q = along(p, a, d)
    if (w.clearAt(q[0], q[1]) < 8 || !w.los(p[0], p[1], p[2] + 8, q[0], q[1], q[2] + 0.5)) return false
  }
  return true
}
// open ground, clear 120 m ahead (the chaser), behind (our way out) and to the left (the edge)
const [pos, open] = (() => {
  for (let x = -400; x <= 400; x += 23) for (let y = -300; y <= 300; y += 23) {
    const p = [x, y, w.floorAt(x, y)]
    if (w.clearAt(x, y) < 8) continue
    for (let k = 0; k < 32; k++) {
      const a = (k / 32) * Math.PI * 2
      if (clear(p, a) && clear(p, a + Math.PI) && clear(p, a + Math.PI / 2)) return [p, a] as const
    }
  }
  throw new Error("no open ground")
})()
const toEdge = open + Math.PI / 2
const R = 190
// the edge `edge` m to our left; a mech `far` m ahead aiming at us; we have `hp` of 1400
const obs = (o: { edge?: number; far?: number; hp?: number } = {}) => {
  const c = along(pos, toEdge + Math.PI, R - (o.edge ?? 25))
  return {
    ...base,
    mechs: [{ id: 9, kind: "mech", pos: along(pos, open, o.far ?? 100), vel: [0, 0, 0], aim: [open + Math.PI, 0], hp: 1400, max_hp: 1400, cubes: 0, weapons: ["gun"], charging: false }],
    pickups: [],
    crates: [],
    cubes: [],
    events: [],
    self: { ...base.self, pos, vel: [0, 0, 0], aim: [open, 0], hp: o.hp ?? 300, max_hp: 1400, weapons: [base.self.weapons[0], null] },
    zone: { ...base.zone, center: [c[0], c[1]], next_center: [c[0], c[1]], radius: R, next_radius: R, shrink_start: 999, shrink_end: 1000 },
  }
}
const run = (B: any, o: any) => {
  const b = new B(hello, w, nav, null)
  b.until = Infinity
  const a = b.act(o)
  return { mode: b.mode, move: a.move as number[] }
}
// how much of a move heads to the edge
const edgeward = (m: number[]) => (m[0] * Math.cos(toEdge) + m[1] * Math.sin(toEdge)) / (Math.hypot(m[0], m[1]) || 1)

test("retreating from a chaser 25 m from the edge, we head for the edge while farx does not", () => {
  const f = run(FarX, obs())
  const s = run(St, obs())
  expect(f.mode).toBe("retreat")
  expect(s.mode).toBe("retreat")
  expect(edgeward(f.move)).toBeLessThan(0.35)
  expect(edgeward(s.move)).toBeGreaterThan(0.5)
})

test("we already on the line, we run along it rather than out", () => {
  const s = run(St, obs({ edge: 8 }))
  expect(s.mode).toBe("retreat")
  // the planner's 16 headings are 22.5 degrees apart: under 0.2 is straight along
  expect(Math.abs(edgeward(s.move))).toBeLessThan(0.2)
})

test("the edge is where the shrinking circle stands now, not where the phase began", () => {
  const o = obs()
  // halfway through a shrink from 250 m to 130 m: 190 m now, the phase's radius 60 m farther out
  o.zone = { ...o.zone, radius: 250, next_radius: 130, shrink_start: o.t - 10, shrink_end: o.t + 10 }
  const s = run(St, o)
  expect(s.mode).toBe("retreat")
  expect(edgeward(s.move)).toBeGreaterThan(0.5)
})

test("with the edge 60 m off, at full HP, or with the chaser 170 m off, we move as farx does", () => {
  for (const o of [{ edge: 60 }, { hp: 1400 }, { edge: 15, far: 170 }]) {
    const f = run(FarX, obs(o))
    const s = run(St, obs(o))
    expect(s.move).toEqual(f.move)
  }
})
