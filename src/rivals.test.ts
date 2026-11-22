// The rival model reads who each mech is on, how it leads, how often it lands, whether it turns on whoever hits it,
// and what all that costs us over the next seconds.
import { test, expect } from "bun:test"
import { Rivals } from "./rivals.ts"
import type { Observation } from "./mechfight.ts"
import { loadConfig } from "../sim/sim.ts"

const cfg = loadConfig()
const ME = 3
const self = (pos = [0, 0, 0], vel = [0, 0, 0]) => ({ id: ME, pos, vel, aim: [0, 0], hp: 1400, max_hp: 1400, energy: 100, max_energy: 100, grounded: true, cubes: 0, upgrades: [], weapons: [null, null], in_zone: true, stats: {} }) as any
const mech = (id: number, pos: number[], aimYaw: number, extra: any = {}) => ({ id, kind: "mech", pos, vel: [0, 0, 0], aim: [aimYaw, 0], hp: 1400, max_hp: 1400, weapons: ["gun"], ...extra })
const ob = (t: number, mechs: any[], more: Partial<Observation> = {}, me = self()): Observation =>
  ({ type: "obs", tick: Math.round(t * 20), t, alive: 10, self: me, mechs, projectiles: [], crates: [], cubes: [], pickups: [], sounds: [], beams: [], events: [], zone: { center: [0, 0], radius: 1000, next_center: [0, 0], next_radius: 500, shrink_start: 60, shrink_end: 110, dps: 20 }, offer: null, drops: [], ...more }) as Observation
const yaw = (from: number[], to: number[]) => Math.atan2(to[1] - from[1], to[0] - from[0])

test("a mech aiming at us is on us; one aiming at another mech is busy", () => {
  const r = new Rivals(cfg)
  const A = [100, 0, 0]
  const B = [0, 100, 0]
  const C = [100, 100, 0]
  r.update(ob(1, [mech(10, A, yaw(A, [0, 0])), mech(11, B, yaw(B, C)), mech(12, C, yaw(C, B))]))
  expect(r.onMe(r.map.get(10)!)).toBe(true)
  expect(r.busy(r.map.get(10)!)).toBe(false)
  expect(r.busy(r.map.get(11)!)).toBe(true)
  expect(r.map.get(11)!.target).toBe(12)
  // the reading goes stale
  r.update(ob(4, []))
  expect(r.onMe(r.map.get(10)!)).toBe(false)
})

test("gun lead: aim at the full lead point reads near 1, aim at the body near 0", () => {
  const full = new Rivals(cfg)
  const body = new Rivals(cfg)
  const A = [150, 0, 0]
  // we cross its line of fire at 10 m/s
  const me = self([0, 0, 0], [0, 10, 0])
  const tof = 150 / cfg.weapons.gun.speed
  for (let k = 0; k < 40; k++) {
    full.update(ob(k * 0.1, [mech(10, A, yaw(A, [0, 10 * tof]))], {}, me))
    body.update(ob(k * 0.1, [mech(10, A, yaw(A, [0, 0]))], {}, me))
  }
  expect(full.map.get(10)!.lead).toBeGreaterThan(0.85)
  expect(body.map.get(10)!.lead).toBeLessThan(0.15)
  expect(full.map.get(10)!.range).toBeCloseTo(150, 0)
})

test("its bullets at us and its hits set its hit rate on us", () => {
  const r = new Rivals(cfg)
  const A = [80, 0, 0]
  const prior = (() => {
    r.update(ob(0, [mech(10, A, Math.PI)]))
    return r.pHit(r.map.get(10)!, 80)
  })()
  // 10 bullets from A flying at us, every one lands
  for (let k = 1; k <= 10; k++) {
    const p = { id: 500 + k, kind: "gun", pos: [70, 0, 7], vel: [-252, 0, 0] }
    r.update(ob(k * 0.3, [mech(10, A, Math.PI)], { projectiles: [p] as any, events: [{ type: "damaged", amount: 45, weapon: "gun", bearing: 0, by: 10 }] as any }))
  }
  const a = r.map.get(10)!
  expect(a.shotsAtMe).toBe(10)
  expect(a.hitsOnMe).toBe(10)
  expect(r.pHit(a, 80)).toBeGreaterThan(prior + 0.2)
  // bullets that all miss pull it under the prior
  const m = new Rivals(cfg)
  for (let k = 1; k <= 10; k++) m.update(ob(k * 0.3, [mech(10, A, Math.PI)], { projectiles: [{ id: 500 + k, kind: "gun", pos: [70, 0, 7], vel: [-252, 0, 0] }] as any }))
  expect(m.pHit(m.map.get(10)!, 80)).toBeLessThan(prior - 0.2)
})

test("a mech that turns on us after our hit reads as retaliating, one that stays on its target does not", () => {
  const A = [60, 0, 0]
  const B = [60, 20, 0]
  const run = (turns: boolean) => {
    const r = new Rivals(cfg)
    for (let n = 0; n < 4; n++) {
      const t0 = n * 10
      r.update(ob(t0, [mech(10, A, yaw(A, B)), mech(11, B, yaw(B, A))], { events: [{ type: "hit", target: 10, amount: 45, weapon: "gun" }] as any }))
      r.update(ob(t0 + 1, [mech(10, A, turns ? yaw(A, [0, 0]) : yaw(A, B)), mech(11, B, yaw(B, A))]))
      r.update(ob(t0 + 3, [mech(10, A, yaw(A, B)), mech(11, B, yaw(B, A))]))
    }
    return r.retaliates(r.map.get(10)!)
  }
  expect(run(true)).toBeGreaterThan(0.8)
  expect(run(false)).toBeLessThan(0.2)
})

test("a laser beam names its target", () => {
  const r = new Rivals(cfg)
  const A = [100, 0, 0]
  const B = [0, 100, 0]
  // A aims nowhere near anyone, but its beam ends on B
  r.update(ob(1, [mech(10, A, 2.5, { weapons: ["laser"] }), mech(11, B, 0)], { beams: [{ by: 10, kind: "laser", path: [A, B], age: 0 }] as any }))
  expect(r.map.get(10)!.target).toBe(11)
})

test("incoming damage: only mechs on us count, and a charged laser aimed at us adds its beam", () => {
  const A = [60, 0, 0]
  const B = [0, 60, 0]
  const C = [60, 60, 0]
  const busy = new Rivals(cfg)
  busy.update(ob(1, [mech(11, B, yaw(B, C)), mech(12, C, yaw(C, B))]))
  expect(busy.incoming(self(), 2)).toBe(0)
  const gun = new Rivals(cfg)
  gun.update(ob(1, [mech(10, A, Math.PI)]))
  const g = gun.incoming(self(), 2)
  expect(g).toBeGreaterThan(0)
  const idle = new Rivals(cfg)
  idle.update(ob(1, [mech(10, A, Math.PI, { weapons: ["gun", "laser"] })]))
  const las = new Rivals(cfg)
  las.update(ob(1, [mech(10, A, Math.PI, { weapons: ["gun", "laser"], charging: true })]))
  // a laser held idle counts at its average rate; charged, its whole beam lands inside 2 s: 0.9 x 315, not 2 / 2.4 of it
  const L = cfg.weapons.laser
  expect(idle.incoming(self(), 2) - g).toBeCloseTo(((L.damage * 0.9) / (L.charge + L.cooldown)) * 2, 0)
  expect(las.incoming(self(), 2) - g).toBeCloseTo(L.damage * 0.9, 0)
})
