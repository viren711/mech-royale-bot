// Bounded planning: the 50 ms decision budget (protocol.md §2) must hold, so heavy searches stop at a deadline and
// failed path searches are not repeated every decision.
import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import { gunzipSync } from "node:zlib"
import { World } from "./world.ts"
import { Nav } from "./nav.ts"
import { Exposure } from "./exposure.ts"
import { Brain } from "./brain.ts"

const w = new World(new URL("../arena", import.meta.url).pathname)
const nav = new Nav(w)
const exp = Exposure.load(w)
if (exp) exp.applyNavCost(nav)
const hello = JSON.parse(gunzipSync(readFileSync(new URL("../check/stream.jsonl.gz", import.meta.url))).toString().split("\n")[0])
let s = 11
const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff }
const randomOk = (): [number, number] => {
  for (;;) {
    const n = Math.floor(rnd() * nav.ok.length)
    if (nav.ok[n]) return nav.nodeXY(n)
  }
}
const far = (p: number[], q: number[]) => Math.hypot(p[0] - q[0], p[1] - q[1])
// a start and goal 400 m or more apart that A* joins
function longRoute() {
  for (;;) {
    const a = randomOk(), b = randomOk()
    if (far(a, b) < 400) continue
    const p = nav.find(a[0], a[1], b[0], b[1])
    if (p && far(p[p.length - 1], b) < 4) return { a, b }
  }
}
function countFinds(n: Nav) {
  const calls: number[] = []
  const f = n.find
  n.find = function (...args: any[]) { calls.push(args[0]); return (f as any).apply(this, args) }
  return calls
}
const obsAt = (p: number[]) => ({ self: { pos: [p[0], p[1], w.floorAt(p[0], p[1])] } }) as any

test("nav.find past its deadline stops short and says so", () => {
  const { a, b } = longRoute()
  const p = nav.find(a[0], a[1], b[0], b[1], 60000, performance.now() - 1)!
  expect(far(p[p.length - 1], b)).toBeGreaterThan(50)
  expect(nav.cut).toBe(true)
  nav.find(a[0], a[1], b[0], b[1])
  expect(nav.cut).toBe(false)
})

test("a path search that found nothing is retried after 1 s, not every decision", () => {
  // a goal with no walkable node within 20 m: inside a large building
  let goal: [number, number] | null = null
  for (let k = 0; k < 200000 && !goal; k++) {
    const x = w.minX + rnd() * w.nx, y = w.minY + rnd() * w.ny
    if (nav.nearestOk(x, y, 10) < 0) goal = [x, y]
  }
  let start = randomOk()
  while (far(start, goal!) < 100) start = randomOk()
  const n = new Nav(w)
  const b = new Brain(hello, w, n, exp)
  const calls = countFinds(n)
  for (const t of [10, 10.1, 10.2, 10.9]) {
    b.t = t
    b.steer(goal!, obsAt(start))
  }
  expect(calls.length).toBe(1)
  b.t = 11.1
  b.steer(goal!, obsAt(start))
  expect(calls.length).toBe(2)
})

test("a path search cut by the deadline is redone on the next decision", () => {
  const { a, b: g } = longRoute()
  const n = new Nav(w)
  const b = new Brain(hello, w, n, exp)
  const calls = countFinds(n)
  b.t = 20
  b.until = performance.now() - 1
  b.steer(g, obsAt(a))
  b.until = Infinity
  b.t = 20.1
  b.steer(g, obsAt(a))
  expect(calls.length).toBe(2)
  b.t = 20.2
  b.steer(g, obsAt(a))
  expect(calls.length).toBe(2)
})

test("coverFrom past the deadline gives up with what it has", () => {
  const b = new Brain(hello, w, nav, exp)
  let found = false
  for (let k = 0; k < 500 && !found; k++) {
    const p = randomOk()
    b.me = { pos: [p[0], p[1], w.floorAt(p[0], p[1])] }
    const from = [p[0] + 70, p[1], w.floorAt(p[0], p[1]) + 8]
    b.until = Infinity
    if (!b.coverFrom(from, 45)) continue
    found = true
    b.until = performance.now() - 1
    expect(b.coverFrom(from, 45)).toBeNull()
  }
  expect(found).toBe(true)
})

// gang searching for a laser walks to one search point for up to 20 s: the path cache (6 m, 4 s) keeps searches rare
// skipped while gang steers the parent's peace every decision again (bots/gang/brain.ts, real-score bisect)
test.skip("gang searching for a laser reuses its path", async () => {
  const { Brain: Gang } = await import("../bots/gang/brain.ts")
  const n = new Nav(w)
  if (exp) exp.applyNavCost(n)
  const b = new Gang(hello, w, n, exp)
  const calls = countFinds(n)
  const base = JSON.parse(gunzipSync(readFileSync(new URL("../check/stream.jsonl.gz", import.meta.url))).toString().split("\n")[151])
  base.pickups = []
  base.mechs = []
  base.events = []
  base.self.hp = base.self.max_hp
  const modes = new Set<string>()
  for (let k = 0; k < 40; k++) {
    const o = structuredClone(base)
    o.t = 30 + k * 0.1
    o.tick = 600 + k * 2
    o.self.pos = [-150 + k * 1.1, 0, w.floorAt(-150 + k * 1.1, 0)]
    b.act(o)
    modes.add(b.mode)
  }
  expect([...modes]).toEqual(["search"])
  // 40 decisions in 4 s: a fresh path at most every few decisions, not one or two each
  expect(calls.length).toBeLessThan(10)
})

// hit by a mech we can't see while searching: face the shot, as farm and kiter do, not the last mech we saw
// reverted on purpose: far5 with this scored 5.38 real against 5.67/5.60 without it (bots/gang/brain.ts peace aim)
test.skip("gang searching for a laser turns to an unseen attacker", async () => {
  const { Brain: Gang } = await import("../bots/gang/brain.ts")
  const b = new Gang(hello, w, nav, exp)
  const o = JSON.parse(gunzipSync(readFileSync(new URL("../check/stream.jsonl.gz", import.meta.url))).toString().split("\n")[151])
  o.pickups = []
  o.events = []
  o.self.pos = [-150, 0, w.floorAt(-150, 0)]
  // a mech seen 30 m east, then gone; then a hit from the north west
  o.mechs = [{ id: 40, kind: "mech", pos: [-120, 0, w.floorAt(-120, 0)], vel: [0, 0, 0], aim: [0, 0], hp: 1400, max_hp: 1400, cubes: 0, weapons: ["gun"], charging: false }]
  o.self.hp = o.self.max_hp
  o.t = 30
  o.tick = 600
  b.act(o)
  o.mechs = []
  o.t = 34
  o.tick = 680
  o.events = [{ type: "damaged", amount: 45, weapon: "gun", bearing: 2.4, by: 41 }]
  const a = b.act(o)
  expect(b.mode).toBe("search")
  expect(a.aim![0]).toBeCloseTo(2.4, 5)
})

// warm() runs before ready on throwaway brains: the brain it warms must decide exactly as an unwarmed one
test("warm leaves the brain it warms deciding as a fresh one", async () => {
  const { Brain: Far } = await import("../bots/far/brain.ts")
  const { warm } = await import("./brain.ts")
  const stream = gunzipSync(readFileSync(new URL("../check/stream.jsonl.gz", import.meta.url))).toString().trim().split("\n").slice(1, 121).map((l) => JSON.parse(l))
  const warmed = new Far(hello, w, nav, exp)
  warm(warmed, hello)
  const fresh = new Far(hello, w, new Nav(w), exp)
  if (exp) exp.applyNavCost(fresh.nav)
  for (const o of stream) expect(JSON.stringify(warmed.act(o))).toBe(JSON.stringify(fresh.act(o)))
})

test("slow decisions log at most one line a second and 30 in all", async () => {
  const { slowLog } = await import("./brain.ts")
  const lines: string[] = []
  const slow = slowLog((l) => lines.push(l))
  // 100 slow decisions 10 ms apart: one second's worth
  for (let k = 0; k < 100; k++) slow(k, 40, 1000 + k * 10)
  expect(lines.length).toBe(1)
  // then one every 2 s for 100 more: the cap ends it at 30
  for (let k = 0; k < 100; k++) slow(100 + k, 40, 5000 + k * 2000)
  expect(lines.length).toBe(30)
})
