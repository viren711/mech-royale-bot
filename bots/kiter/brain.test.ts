// The move planner stops scoring candidates once the decision deadline has passed (protocol.md §2, 50 ms budget).
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Brain } from "./brain.ts"

const lines = gunzipSync(readFileSync(new URL("../../check/stream.jsonl.gz", import.meta.url))).toString().split("\n").filter(Boolean).map((l) => JSON.parse(l))
const w = new World(new URL("../../arena", import.meta.url).pathname)
const nav = new Nav(w)

test("planMove past the deadline scores one candidate, not all 33", () => {
  const b = new Brain(lines[0], w, nav, null)
  const obs = lines.find((o) => o.type === "obs" && o.mechs.length > 0)
  b.act(obs)
  const e = b.foes()[0]
  let los = 0
  const f = w.los
  w.los = function (...a: any[]) { los++; return (f as any).apply(this, a) }
  b.planMove(obs, e, [e], [20, 60], false, null, false)
  const full = los
  los = 0
  b.until = performance.now() - 1
  b.planMove(obs, e, [e], [20, 60], false, null, false)
  w.los = f
  expect(full).toBeGreaterThanOrEqual(17)
  expect(los).toBeLessThanOrEqual(1)
})
