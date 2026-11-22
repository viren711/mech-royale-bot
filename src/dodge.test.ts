// The linear-lead shooter model, the path score against it, and the laser reflex's trigger and escape.
import { test, expect } from "bun:test"
import { leadPoint, shotCost, laserThreats, breakLos, walk, Jink, DT, type Shooter } from "./dodge.ts"
import type { World } from "./world.ts"

const GUN = { damage: 45, speed: 252, range: 230, spread_deg: 0.6 }
const foe = (over: Partial<Shooter> = {}): Shooter => ({ pos: [0, 0, 0], vel: [0, 0, 0], aim: [0, 0], weapons: ["gun"], charging: false, visible: true, ...over })

/** x, y every DT for 1 s: velocity v0 that turns to v1 at ground_accel 58.5 */
function path(p0: number[], v0: number[], v1: number[]): number[][] {
  const out = [[p0[0], p0[1]]]
  let [x, y] = p0
  let [vx, vy] = v0
  for (let s = 0; s < 20; s++) {
    const dx = v1[0] - vx, dy = v1[1] - vy
    const dv = Math.hypot(dx, dy)
    const a = 58.5 * DT
    if (dv <= a) {
      vx = v1[0]
      vy = v1[1]
    } else {
      vx += (dx / dv) * a
      vy += (dy / dv) * a
    }
    x += vx * DT
    y += vy * DT
    out.push([x, y])
  }
  return out
}

test("a linear-lead gunner aims where our velocity carries us over the latency and the flight", () => {
  // 100 m out, crossing at 10 m/s: flight (100 - 3) / 252 = 0.385 s, plus 0.075 s, puts the aim 4.60 m ahead
  const { at, tof } = leadPoint([0, 0, 0], [100, 0, 0], [0, 10, 0], 252)
  expect(tof).toBeCloseTo(0.385, 2)
  expect(at[0]).toBeCloseTo(100, 5)
  expect(at[1]).toBeCloseTo(4.6, 1)
})

test("holding our velocity takes nearly every bullet, reversing it takes few", () => {
  const f = [foe({ pos: [0, 0, 0] })]
  const held = shotCost(path([100, 0], [0, 11.7], [0, 11.7]), [0, 11.7], f, 2.5, GUN)
  const back = shotCost(path([100, 0], [0, 11.7], [0, -11.7]), [0, 11.7], f, 2.5, GUN)
  // two shots at 45 x (0.1 / 0.24) each, spread 1.05 m at 100 m against a 2.5 m radius: 98% of 37.5
  expect(held).toBeGreaterThan(35)
  expect(back).toBeLessThan(10)
})

test("over four decisions of shots, stopping costs more than reversing", () => {
  const f = [foe({ pos: [0, 0, 0] })]
  const v0 = [0, 11.7]
  const stop = shotCost(path([100, 0], v0, [0, 0]), v0, f, 2.5, GUN, 4)
  const back = shotCost(path([100, 0], v0, [0, -11.7]), v0, f, 2.5, GUN, 4)
  // stopped by 0.2 s: the shots fired off our state at 0.2 and 0.3 s see us standing, 98% of 2 x 45 x (0.1 / 0.24) each
  expect(stop).toBeGreaterThan(30)
  expect(back).toBeLessThan(stop / 2)
})

test("a gunner past its range costs nothing", () => {
  const far = shotCost(path([300, 0], [0, 11.7], [0, 11.7]), [0, 11.7], [foe()], 2.5, GUN)
  expect(far).toBe(0)
})

test("a charging laser counts when its aim is within 3 degrees of us, not 6", () => {
  const me = [200, 0, 0]
  const at2 = laserThreats([foe({ charging: true, aim: [(2 * Math.PI) / 180, 0] })], me, 2.5, 280, () => 10, 0.75, 10.3)
  const at6 = laserThreats([foe({ charging: true, aim: [(6 * Math.PI) / 180, 0] })], me, 2.5, 280, () => 10, 0.75, 10.3)
  const idle = laserThreats([foe({ charging: false, aim: [0, 0] })], me, 2.5, 280, () => 10, 0.75, 10.3)
  expect(at2.length).toBe(1)
  // charging since t = 10: a full 0.75 s charge is 0.45 s off at t = 10.3
  expect(at2[0].eta).toBeCloseTo(0.45, 5)
  expect(at6.length).toBe(0)
  expect(idle.length).toBe(0)
})

// open ground at floor 0, and cover: the shooter in the south sees nothing north of y = 3
const world = { floorAt: () => 0, clearAt: () => 99, los: (_ax: number, _ay: number, _az: number, _bx: number, by: number) => by <= 3 } as unknown as World
const body = { pos: [0, 0, 0], vel: [0, 0, 0], R: 2.5, H: 9, walk: 11.7, accel: 58.5, stepUp: 1.2, grounded: true }
const shooter = foe({ pos: [0, -150, 0], charging: true, aim: [Math.PI / 2, 0] })

test("with time before the release we walk behind the cover, sideways strafes stay seen", () => {
  const th = laserThreats([shooter], body.pos, 2.5, 280, () => 0, 0.75, 0.3)
  const mv = breakLos(world, th, body, [1, 0])
  expect(mv).not.toBeNull()
  // 3 m in 0.45 s from a standstill only straight north
  expect(mv![1]).toBeGreaterThan(0.9)
})

test("cover out of reach by the release: no reflex", () => {
  const th = laserThreats([shooter], body.pos, 2.5, 280, () => 0, 0.75, 0.7)
  expect(breakLos(world, th, body, [1, 0])).toBeNull()
})

test("a gunner known to lead half our velocity aims short of a full lead", () => {
  const full = leadPoint([0, 0, 0], [100, 0, 0], [0, 10, 0], 252)
  const p = path([100, 0], [0, 10], [0, 10])
  // holding velocity: a full lead hits, half a lead misses by about 2.3 m and the spread covers part of that
  const hit = shotCost(p, [0, 10], [foe()], 2.5, GUN)
  const half = shotCost(p, [0, 10], [foe({ lead: 0.5 })], 2.5, GUN)
  expect(full.at[1]).toBeGreaterThan(4)
  expect(half).toBeLessThan(hit * 0.8)
})

const open = { floorAt: () => 0, clearAt: () => 99, los: () => true } as unknown as World
const gunner = [foe()]
const at150 = { ...body, pos: [150, 0, 0], vel: [0, 11.7, 0] }

/** share of k1 shots (a linear lead off our last 0.1 s, every 0.25 s) that pass within 2.8 m of us, a gunner at the
 * origin and us starting 130 m east, `pick` choosing our move every decision for 20 s */
function wouldHit(pick: (me: typeof body, t: number) => [number, number]): number {
  let me = { ...body, pos: [130, 0, 0], vel: [0, 11.7, 0] }
  const hist: number[][] = []
  let dir: [number, number] = [0, 1]
  for (let s = 0; s < 400; s++) {
    if (s % 2 === 0) dir = pick(me, s * DT)
    const p = walk(open, me, dir, 1)[1]
    me = { ...me, pos: p, vel: [(p[0] - me.pos[0]) / DT, (p[1] - me.pos[1]) / DT, 0] }
    hist.push(p)
  }
  let hits = 0
  let shots = 0
  for (let s = 10; s < 380; s += 5) {
    const v = [(hist[s][0] - hist[s - 2][0]) / (2 * DT), (hist[s][1] - hist[s - 2][1]) / (2 * DT)]
    const { at, tof } = leadPoint([0, 0, 0], hist[s], v, 252, 0)
    const q = hist[Math.round(s + tof / DT)]
    const L = Math.hypot(at[0], at[1])
    shots++
    if (Math.abs(((q[0] - at[0]) * at[1] - (q[1] - at[1]) * at[0]) / L) < 2.8) hits++
  }
  return hits / shots
}

test("weaving across a gunner's line makes a linear lead miss most shots that a held strafe takes", () => {
  const j = new Jink(0.4, 0.2, 0.7, 50, () => 0.5)
  const held = wouldHit(() => [0, 1])
  const weave = wouldHit((me, t) => j.move(open, me, [0, 1], gunner, t))
  expect(held).toBeGreaterThan(0.95)
  expect(weave).toBeLessThan(0.5)
})

test("a weave holds each side at least its shortest leg, so it never flips back and forth decision to decision", () => {
  const j = new Jink(0.4, 0.2, 0.7, 50, () => 0.5)
  const sides: number[] = []
  for (let t = 0; t < 3; t += 0.1) sides.push(Math.sign(j.move(open, at150, [0, 1], gunner, t)[1]))
  const flips = sides.map((s, i) => (i && s !== sides[i - 1] ? i : -1)).filter((i) => i > 0)
  // legs of 0.4 + 0.5 x 0.2 = 0.5 s: 5 flips in 3 s, never two within 0.4 s
  expect(flips.length).toBeGreaterThanOrEqual(4)
  for (let k = 1; k < flips.length; k++) expect(flips[k] - flips[k - 1]).toBeGreaterThanOrEqual(4)
})

test("a walk along the gunner's line keeps its progress and gains a sideways part", () => {
  const j = new Jink(0.4, 0.2, 0.7, 50, () => 0.5)
  const mv = j.move(open, at150, [-1, 0], gunner, 0)
  expect(mv[0]).toBeLessThan(-0.5)
  expect(Math.abs(mv[1])).toBeGreaterThan(0.5)
  expect(Math.hypot(mv[0], mv[1])).toBeCloseTo(1, 5)
})

test("no gunner, a gunner inside the shortest range, or us in the air: the wanted move stands", () => {
  const j = new Jink(0.4, 0.2, 0.7, 50, () => 0.5)
  expect(j.move(open, at150, [0, 1], gunner, 0)).not.toEqual([0, 1])
  expect(j.move(open, at150, [0, 1], [], 0)).toEqual([0, 1])
  expect(j.move(open, { ...at150, pos: [30, 0, 0] }, [0, 1], gunner, 0)).toEqual([0, 1])
  expect(j.move(open, { ...at150, grounded: false }, [0, 1], gunner, 0)).toEqual([0, 1])
})

test("a wall on one side: the weave takes the open side", () => {
  // nothing clear north of y = 1
  const wall = { floorAt: () => 0, clearAt: (_x: number, y: number) => (y > 1 ? 0 : 99), los: () => true } as unknown as World
  const still = { ...at150, vel: [0, 0, 0] }
  for (const side of [1, -1]) {
    const j = new Jink(0.4, 0.2, 0.7, 50, () => 0.5)
    j.side = side
    j.until = 10
    expect(j.move(wall, still, [0, 1], gunner, 0)[1]).toBeLessThan(0)
  }
})
