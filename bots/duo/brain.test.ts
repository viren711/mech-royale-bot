// Mode detection: practice (house bots) keeps rim5's play, a free-for-all among team bots switches to farm's.
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain, ffaSeen } from "./brain.ts"

const lines = gunzipSync(readFileSync(new URL("../../check/stream.jsonl.gz", import.meta.url))).toString().split("\n").filter(Boolean).map((l) => JSON.parse(l))
const w = new World(new URL("../../arena", import.meta.url).pathname)
const nav = new Nav(w)
const obs0 = lines.find((o) => o.type === "obs")

test("a field losing mechs fast early reads as a free-for-all, a slow one as practice", () => {
  // show-20261121T060000 (team bots): deaths at 7, 12, 17 s
  expect(ffaSeen(17, 3)).toBe(true)
  // a typical house room: 1 death by 20 s, 3 by 30 s
  expect(ffaSeen(20, 1)).toBe(false)
  expect(ffaSeen(30, 3)).toBe(false)
  // past the window deaths say nothing: house rooms lose more mechs by 60 s than showdowns
  expect(ffaSeen(60, 9)).toBe(false)
  // unsure late: the finals count
  expect(ffaSeen(150, 0)).toBe(true)
})

test("the mechs we kill do not count, and the switch keeps what the brain knows", () => {
  const b = new Brain(lines[0], w, nav, null)
  const at = (t: number, alive: number, events: any[] = []) => ({ ...obs0, t, tick: Math.round(t * 20), alive, events })
  b.act(at(1, 16))
  b.act(at(10, 14, [{ type: "kill", target: 3 }, { type: "kill", target: 4 }]))
  b.act(at(15, 13))
  expect(b.ffa).toBe(false)
  const loot = b.loot
  const enemies = b.enemies
  b.act(at(18, 11))
  expect(b.ffa).toBe(true)
  expect(b.loot).toBe(loot)
  expect(b.enemies).toBe(enemies)
  // farm's fight drives from here: one more tick runs without throwing
  expect(() => b.act(at(18.1, 11))).not.toThrow()
})
