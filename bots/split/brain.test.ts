// farx while the match reads as practice, duo once it reads as the finals (src/mode.ts).
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain } from "./brain.ts"
import { Brain as FarX } from "../farx/brain.ts"

const lines = gunzipSync(readFileSync(new URL("../../check/stream.jsonl.gz", import.meta.url))).toString().split("\n").filter(Boolean).map((l) => JSON.parse(l))
const w = new World(new URL("../../arena", import.meta.url).pathname)
const nav = new Nav(w)
const obs = lines.filter((o) => o.type === "obs")
const at = (t: number, alive: number, events: any[] = []) => ({ ...obs[0], t, tick: Math.round(t * 20), alive, events })

test("the mechs we kill do not count, and the switch holds", () => {
  const b = new Brain(lines[0], w, nav, null)
  b.act(at(1, 16))
  b.act(at(10, 13, [{ type: "kill", target: 3 }, { type: "kill", target: 4 }, { type: "kill", target: 5 }]))
  b.act(at(30, 12))
  expect(b.finals).toBe(false)
  b.act(at(40, 11))
  expect(b.finals).toBe(true)
  b.act(at(60, 11))
  expect(b.finals).toBe(true)
})

// every action of a whole recorded stream, from fresh brains with no time cap
const play = (b: any, stream: any[]) => stream.map((o) => JSON.stringify(b.act(o)))

test("in practice every decision is farx's", () => {
  // the recorded stream loses 2 mechs by 23 s; practice house bots would not have killed them
  const stream = obs.map((o) => ({ ...o, alive: obs[0].alive }))
  const split = play(new Brain(lines[0], w, nav, null), stream)
  const farx = play(new FarX(lines[0], w, nav, null), stream)
  expect(split).toEqual(farx)
})

test("once the field reads as the finals it searches duo's ring", () => {
  const b = new Brain(lines[0], w, nav, null)
  const z = obs[0].zone
  const dr = () => Math.hypot(...b.searchPoint(z.center, z.radius).map((v: number, k: number) => v - z.center[k])) / z.radius
  b.act(at(1, 16))
  const inner = Array.from({ length: 20 }, dr)
  b.act(at(20, 14))
  expect(b.finals).toBe(true)
  const ring = Array.from({ length: 20 }, dr)
  // rim5 keeps 0.9 of the radius from the center; far5 searches anywhere
  expect(Math.min(...inner)).toBeLessThan(0.9)
  expect(Math.min(...ring)).toBeGreaterThanOrEqual(0.9 - 1e-9)
})

test("duo's own switch on time alone does not reach practice", () => {
  const b = new Brain(lines[0], w, nav, null)
  const f = new FarX(lines[0], w, nav, null)
  const seen = obs.find((o) => o.mechs.length)
  const late = { ...seen, t: 151, tick: 3020, alive: 16, events: [] }
  for (const o of [at(1, 16), late]) {
    b.act(o)
    f.act(o)
  }
  // duo plays farm from 150 s; split read practice at 45 s
  expect(b.ffa).toBe(true)
  expect(b.finals).toBe(false)
  const e = { ...seen.mechs[0], visible: true, weapons: ["gun", "laser"] }
  expect(b.band(e)).toEqual(f.band(e))
  expect(JSON.stringify(b.peace(late, false))).toEqual(JSON.stringify(f.peace(late, false)))
  const foes = b.foes(late)
  expect(foes.length).toBeGreaterThan(0)
  expect(JSON.stringify(b.fight(late, foes[0], foes, false))).toEqual(JSON.stringify(f.fight(late, f.foes(late)[0], f.foes(late), false)))
})
