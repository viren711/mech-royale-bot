// farxlv and duolv retreat away from the attackers instead of to cover from the target, where farx and duo pick cover
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { Brain as Duo } from "../duo/brain.ts"
import { Brain as FarXlv } from "./brain.ts"
import { Brain as Duolv } from "../duolv/brain.ts"

const lines = gunzipSync(readFileSync(new URL("../../check/stream.jsonl.gz", import.meta.url))).toString().split("\n").filter(Boolean).map((l) => JSON.parse(l))
const w = new World(new URL("../../arena", import.meta.url).pathname)
const nav = new Nav(w)
const base = lines.find((o) => o.type === "obs" && o.mechs.length > 0)
const at = (p: number[], a: number, d: number) => {
  const x = p[0] + Math.cos(a) * d
  const y = p[1] + Math.sin(a) * d
  return [x, y, w.floorAt(x, y)]
}
// two gun mechs 70 m out aiming at us, at 45% HP: farm's rule backs off from a second attacker below half HP
const obs = (pos: number[]) => {
  const foe = (id: number, a: number) => {
    const q = at(pos, a, 70)
    return { id, kind: "mech", pos: q, vel: [0, 0, 0], aim: [Math.atan2(pos[1] - q[1], pos[0] - q[0]), 0], hp: 1400, max_hp: 1400, cubes: 0, weapons: ["gun"], charging: false }
  }
  return {
    ...base,
    t: 50,
    tick: 1000,
    alive: 12,
    mechs: [foe(9, 0), foe(10, 0.4)],
    pickups: [],
    cubes: [],
    crates: [],
    projectiles: [],
    beams: [],
    events: [],
    offer: null,
    self: { ...base.self, pos, vel: [0, 0, 0], aim: [0, 0], hp: base.self.max_hp * 0.45, cubes: 0, weapons: [base.self.weapons[0], null] },
    zone: { ...base.zone, center: [pos[0], pos[1]], next_center: [pos[0], pos[1]], radius: 400, next_radius: 400, shrink_start: 999, shrink_end: 1000 },
  }
}
const spy = (B: any) =>
  class extends B {
    covers: (number[] | null)[] = []
    planMove(...a: any[]) {
      this.covers.push(a[5])
      return super.planMove(...a)
    }
  }

for (const [name, Old, New] of [["farxlv", FarX, FarXlv], ["duolv", Duo, Duolv]] as const) {
  test(`${name}: a retreat with cover from the target in reach goes without it; the parent takes it`, () => {
    let checked = 0
    for (let x = -300; x <= 300 && checked < 3; x += 37) for (let y = -200; y <= 200 && checked < 3; y += 37) {
      if (w.clearAt(x, y) < 6) continue
      const pos = [x, y, w.floorAt(x, y)]
      const old = new (spy(Old))(lines[0], w, nav, null)
      old.act(obs(pos))
      if (old.mode !== "retreat" || !old.covers[0]) continue
      const lv = new (spy(New))(lines[0], w, nav, null)
      lv.act(obs(pos))
      expect(lv.mode).toBe("retreat")
      expect(lv.covers).toEqual([null])
      checked++
    }
    expect(checked).toBe(3)
  })
}
