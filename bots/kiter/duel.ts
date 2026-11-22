// bun bots/kiter/duel.ts [--a ../bots/kiter/brain.ts] [--b ../src/brain.ts | house:expert] [--n 40] [--dist 120] [--load gun,laser] [--loadB gun] [--T 90]
// 1v1 duels in the local sim: two bots placed `dist` apart with line of sight and a fixed loadout, the other 14 slots dead,
// no drones or loot, a zone that never closes. Prints damage dealt by each side, wins and fight length. Sides swap every round.
import { World } from "../../src/world.ts"
import { Nav } from "../../src/nav.ts"
import { Exposure } from "../../src/exposure.ts"
import { Sim, loadConfig, type Ctrl } from "../../sim/sim.ts"
import { House } from "../../sim/house.ts"

const args = process.argv.slice(2)
const opt = (k: string, d: string) => {
  const i = args.indexOf("--" + k)
  return i >= 0 ? args[i + 1] : d
}
const N = +opt("n", "40")
const dist = +opt("dist", "120")
const T = +opt("T", "90")
const seed0 = +opt("seed", "1000")
const loadA = opt("load", "gun,laser").split(",")
const loadB = opt("loadB", opt("load", "gun,laser")).split(",")
const specs = [opt("a", "../bots/kiter/brain.ts"), opt("b", "../src/brain.ts")]

const root = new URL("../../", import.meta.url)
const w = new World(new URL("arena", root).pathname)
const nav = new Nav(w)
const navH = new Nav(w)
const exp = Exposure.load(w)
if (exp) exp.applyNavCost(nav)
const cfg = loadConfig()
const mods: (null | any)[] = []
for (const s of specs) {
  if (s.startsWith("house:")) mods.push(null)
  else mods.push((await import(new URL(s, new URL("sim/", root)).href)).Brain)
}
const make = (k: number, hello: any): Ctrl => {
  const s = specs[k]
  if (!s.startsWith("house:")) return new mods[k](hello, w, nav, exp)
  const h = new House(w, navH, s.slice(6), hello.seed, cfg)
  // a bot facing a house bot is an entrant to it, as in practice matches
  h.foes = () => cur.mechs.filter((m) => m.alive && !(m.ctrl instanceof House))
  return h
}
let cur: Sim
const idle: Ctrl = { name: "idle", act: () => ({}) }
const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a))

const dealt = [0, 0]
const wins = [0, 0]
let draws = 0
let len = 0
const hpLeft = [0, 0]
const byWeapon = [new Map<string, number>(), new Map<string, number>()]
const shots = [0, 0]
const lasers = [0, 0]
for (let g = 0; g < N; g++) {
  const swap = g % 2 === 1
  const sim = new Sim(w, nav, cfg, seed0 + g, Array.from({ length: 16 }, (_, i) => (id: number, hello: any) => (i < 2 ? make(swap ? 1 - i : i, hello) : idle)))
  cur = sim
  for (const m of sim.mechs.slice(2)) m.alive = false
  sim.npcs = []
  sim.pickups = []
  // two points `dist` apart with eye-level sight between them
  let P: number[] | null = null
  let Q: number[] | null = null
  for (let k = 0; k < 2000 && !Q; k++) {
    const p = sim.randomPoint(cfg.zone.start_center, 300)
    if (!p) continue
    const a = sim.rng() * Math.PI * 2
    const q = [p[0] + Math.cos(a) * dist, p[1] + Math.sin(a) * dist]
    if (w.clearAt(q[0], q[1]) < 4 || w.clearAt(p[0], p[1]) < 4) continue
    if (!w.los(p[0], p[1], w.floorAt(p[0], p[1]) + 8, q[0], q[1], w.floorAt(q[0], q[1]) + 4.5)) continue
    P = p
    Q = q
  }
  const mid = [(P![0] + Q![0]) / 2, (P![1] + Q![1]) / 2]
  Object.assign(sim.zone, { center: mid, radius: 2000, next_center: mid, next_radius: 150, shrink_start: 1e8, shrink_end: 1e9, dps: 20 })
  const ab = [sim.mechs[0], sim.mechs[1]]
  const pts = [P!, Q!]
  for (let i = 0; i < 2; i++) {
    const m = ab[i]
    const o = pts[1 - i]
    m.pos = [pts[i][0], pts[i][1], w.floorAt(pts[i][0], pts[i][1])]
    m.aim = [wrap(Math.atan2(o[1] - pts[i][1], o[0] - pts[i][0]) + (sim.rng() - 0.5) * 0.6), 0]
    m.aimCmd = m.aim.slice()
    const load = (swap ? 1 - i : i) === 0 ? loadA : loadB
    m.weapons = [0, 1].map((s) => (load[s] ? { kind: load[s], cooldown: 0, ammo: cfg.weapons.gun.mag, reload: 0, charge: 0, equip: 0 } : null))
  }
  const tally = [0, 0]
  const orig = sim.damage.bind(sim)
  sim.damage = (v, amt, weapon, by, from) => {
    const hp0 = v.hp
    orig(v, amt, weapon, by, from)
    if (!by || by.id >= 2) return
    const k = swap ? 1 - by.id : by.id
    tally[k] += hp0 - Math.max(0, v.hp)
    byWeapon[k].set(weapon, (byWeapon[k].get(weapon) ?? 0) + hp0 - Math.max(0, v.hp))
  }
  const origSound = sim.sound.bind(sim)
  sim.sound = (kind, p, except) => {
    if (kind === "gun" && except >= 0 && except < 2) shots[swap ? 1 - except : except]++
    if (kind === "laser" && except >= 0 && except < 2) lasers[swap ? 1 - except : except]++
    origSound(kind, p, except)
  }
  while (sim.t < T && ab[0].alive && ab[1].alive) sim.step()
  const side = (i: number) => ab[swap ? 1 - i : i]
  for (let i = 0; i < 2; i++) {
    dealt[i] += tally[i]
    hpLeft[i] += side(i).alive ? side(i).hp : 0
  }
  if (side(0).alive && !side(1).alive) wins[0]++
  else if (side(1).alive && !side(0).alive) wins[1]++
  else draws++
  len += sim.t
}
const name = (i: number) => `${specs[i]} [${(i ? loadB : loadA).join("+")}]`
console.log(`duels n=${N} dist=${dist} T=${T}`)
for (let i = 0; i < 2; i++) console.log(`${name(i).padEnd(46)} dealt ${(dealt[i] / N).toFixed(0).padStart(5)}  wins ${wins[i]}  hp left ${(hpLeft[i] / N).toFixed(0)}  gun shots ${(shots[i] / N).toFixed(1)} lasers ${(lasers[i] / N).toFixed(1)}  ${[...byWeapon[i]].map(([k, v]) => `${k} ${(v / N).toFixed(0)}`).join(" ")}`)
console.log(`draws ${draws}  mean length ${(len / N).toFixed(1)} s  dealt ratio A/B ${(dealt[0] / Math.max(1, dealt[1])).toFixed(2)}`)
