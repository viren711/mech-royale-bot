// Lasers we race to (sim/SHOWDOWN.md, show-20261121T092557: a mech 76 m from the laser took it while we ran 200 m to it,
// then killed us with it). Pickups are listed only while seen (protocol.md §8 Vision), so one we should see and don't is gone.
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain as FarX } from "./brain.ts"
import { Brain as Split } from "../split/brain.ts"

const lines = gunzipSync(readFileSync(new URL("../../check/stream.jsonl.gz", import.meta.url))).toString().split("\n").filter(Boolean).map((l) => JSON.parse(l))
const w = new World(new URL("../../arena", import.meta.url).pathname)
const nav = new Nav(w)
const base = lines.find((o) => o.type === "obs" && o.mechs.length > 0)
// a ground point d m from p along yaw a
const along = (p: number[], a: number, d: number) => {
  const x = p[0] + Math.cos(a) * d
  const y = p[1] + Math.sin(a) * d
  return [x, y, w.floorAt(x, y)]
}
const clear = (p: number[], a: number) => {
  const q = along(p, a, 120)
  return w.clearAt(q[0], q[1]) > 5 && w.los(p[0], p[1], p[2] + 8, q[0], q[1], q[2] + 0.5) && w.canopyCover(p[0], p[1], p[2] + 8, q[0], q[1], q[2] + 0.5) === 0
}
// open ground and a yaw whose points 120 m out ahead and behind are both in plain sight, so only the yaw wedge hides the one behind
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

const obs = (over: any) => ({
  ...base,
  mechs: [],
  pickups: [],
  self: { ...base.self, pos, aim: [open, 0], weapons: [base.self.weapons[0], null] },
  zone: { ...base.zone, center: [pos[0], pos[1]], next_center: [pos[0], pos[1]], radius: 190, next_radius: 190, shrink_start: 999, shrink_end: 1000 },
  ...over,
})

// split plays farx in practice
for (const [name, Brain] of [["farx", FarX], ["split", Split]] as const) {
  test(`${name}: a remembered laser 120 m ahead in plain sight that is no longer listed is forgotten; one behind us is kept`, () => {
    const b = new Brain(lines[0], w, nav, null)
    const ahead = along(pos, open, 120)
    const behind = along(pos, open + Math.PI, 120)
    b.act(obs({ pickups: [{ id: 1, kind: "laser", pos: ahead }, { id: 2, kind: "laser", pos: behind }] }))
    expect([...b.loot.keys()].sort()).toEqual([1, 2])
    b.act(obs({ tick: base.tick + 2, t: base.t + 0.1 }))
    expect([...b.loot.keys()]).toEqual([2])
  })

  test(`${name}: no race to a laser an enemy stands nearer to; the same laser with no enemy is the goal`, () => {
    const laser = along(pos, open, 150)
    const enemy = { id: 9, kind: "mech", pos: along(pos, open, 130), vel: [0, 0, 0], aim: [0, 0], hp: 1400, max_hp: 1400, cubes: 0, weapons: ["gun"], charging: false }
    const lone = new Brain(lines[0], w, nav, null)
    const o1 = obs({ pickups: [{ id: 1, kind: "laser", pos: laser }] })
    lone.act(o1)
    expect(lone.laserGoal(o1, Infinity)).toEqual([laser[0], laser[1]])
    const raced = new Brain(lines[0], w, nav, null)
    const o2 = obs({ pickups: [{ id: 1, kind: "laser", pos: laser }], mechs: [enemy] })
    raced.act(o2)
    expect(raced.laserGoal(o2, Infinity)).toBeNull()
  })
}
