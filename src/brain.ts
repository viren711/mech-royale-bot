// The decision logic: hide in low-exposure ground inside the coming zone, stay silent, fight only when found
// or when the end is near, and loot what makes fighting easier.
import type { Action, ActorObs, Hello, Observation, PickupObs, WeaponObs } from "./mechfight.ts"
import { World } from "./world.ts"
import { Nav } from "./nav.ts"
import { Exposure } from "./exposure.ts"
import { KNOBS, KNOB_DEFAULTS, type Knobs } from "./knobs.ts"

type V2 = [number, number]
type Enemy = { id: number; pos: number[]; vel: number[]; aim: number[]; hp: number; maxHp: number; weapons: string[]; charging: boolean; cubes: number; seen: number; first: number; visible: boolean }

const TAU = Math.PI * 2
const wrap = (a: number) => { a = (a + Math.PI) % TAU; if (a < 0) a += TAU; return a - Math.PI }
const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])

export type Params = {
  expW: number // weight of static exposure when choosing a hiding spot
  distW: number // weight per meter of travel to a spot
  enemyR: number // radius of the penalty around known enemies
  centerFrac: number // stay at least this fraction of the next radius away from its center
  fightHpFrac: number // flee below this HP fraction when the enemy has more HP
  greedR: number // detour radius for loot and cubes
  oppR: number // attack an unaware low-HP enemy within this range
}
export const DEFAULTS: Params = { expW: KNOBS.HIDE_EXP_W.v, distW: KNOBS.HIDE_DIST_W.v, enemyR: KNOBS.HIDE_ENEMY_R.v, centerFrac: KNOBS.HIDE_CENTER_FRAC.v, fightHpFrac: 0.4, greedR: 30, oppR: 90 }

const UPGRADE_RANK: Record<string, number> = {
  plating: 10, armor: 9, nanites: 8, laser_damage: 7, laser_charge: 7, gun_rate: 6, gun_damage: 6, servos: 5,
  lightning_efficiency: 5, lightning_range: 5, sensors: 4, gyros: 4, gun_mag: 4, lightning_chain: 4, gun_velocity: 3,
  laser_pierce: 2, reactor: 3, capacitor: 3, jets: 2, mortar_reload: 2, mortar_velocity: 2,
}
const WEAPON_RANK: Record<string, number> = { laser: 3, lightning: 2, mortar: 1, gun: 0 }

export class Brain {
  name = "mech"
  w: World
  nav: Nav
  exp: Exposure | null
  cfg: any
  p: Params
  /** play constants (src/knobs.ts): the class's static knobs, else the defaults */
  kn: Knobs
  rng: () => number
  enemies = new Map<number, Enemy>()
  npcs = new Map<number, { pos: number[]; seen: number; home: number[] }>()
  dangers: { pos: V2; t: number; w: number }[] = []
  lastHit = -99
  lastHitBy: number | null = null
  lastHitBearing = 0
  goal: V2 | null = null
  goalT = -99
  goalWhy = ""
  path: V2[] | null = null
  pathI = 0
  pathGoal: V2 | null = null
  pathT = -99
  strafe = 1
  strafeT = 0
  stuckRef: V2 = [0, 0]
  stuckT = 0
  unstickUntil = -1
  unstickDir: V2 = [0, 0]
  scanBase = 0
  lastAimCmd: V2 = [0, 0]
  target: number | null = null
  laserHold = false
  me: any
  t = 0
  mode = ""
  zoneKey = ""
  takeFail = new Map<number, number>()
  /** performance.now() past which heavy planning stops and keeps its best so far; main.ts sets it per decision, the sim leaves it off */
  until = Infinity
  /** t of the last path search that found nothing */
  pathFailT = -99
  constructor(hello: Hello, w?: World, nav?: Nav, exp?: Exposure | null, p: Params = DEFAULTS) {
    this.cfg = hello.config
    this.w = w ?? new World(hello.map.dir)
    this.nav = nav ?? new Nav(this.w)
    this.exp = exp === undefined ? Exposure.load(this.w) : exp
    this.p = p
    this.kn = (this.constructor as { knobs?: Knobs }).knobs ?? KNOB_DEFAULTS
    let s = (hello.seed >>> 0) || 1
    this.rng = () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 1e9) / 1e9 }
    if (this.exp && !nav) this.exp.applyNavCost(this.nav)
  }

  act(obs: Observation): Omit<Action, "tick"> {
    const me = obs.self
    this.me = me
    const t = (this.t = obs.t)
    const pos = me.pos
    const act: Omit<Action, "tick"> = {}
    this.observe(obs)

    if (obs.offer) act.pick = this.pickUpgrade(obs.offer.choices.map((c) => c.id))

    // ---- choose what to do ----
    const vis = [...this.enemies.values()].filter((e) => e.visible)
    const alive = obs.alive
    const zone = obs.zone
    const endgame = alive <= 2 || (zone.next_radius <= 25 && t > zone.shrink_start - 5) || zone.radius <= 30
    let target: Enemy | null = null
    let engage = false
    const recentlyHit = t - this.lastHit < 2.5 && this.lastHitBy !== null
    for (const e of vis) {
      const d = d2(e.pos, pos)
      const attacking = recentlyHit && this.lastHitBy === e.id
      const facing = Math.abs(wrap(Math.atan2(pos[1] - e.pos[1], pos[0] - e.pos[0]) - e.aim[0])) < 0.35
      let score = d
      if (attacking) score -= 200
      if (facing) score -= 60
      if (e.hp < 500) score -= 40
      if (!target || score < (target as any)._s) { target = e; (e as any)._s = score }
    }
    if (target) {
      const d = d2(target.pos, pos)
      const attacking = recentlyHit && this.lastHitBy === target.id
      const facing = Math.abs(wrap(Math.atan2(pos[1] - target.pos[1], pos[0] - target.pos[0]) - target.aim[0])) < 0.35
      const weak = target.hp < 0.35 * target.maxHp && target.hp < me.hp * 0.6
      engage = attacking || d < 55 || (facing && d < 160) || endgame || (weak && d < this.p.oppR)
    }
    // an unseen attacker: turn to look
    let lookYaw: number | null = null
    if (recentlyHit && (!target || !engage)) lookYaw = this.lastHitBearing

    let moveTo: V2 | null = null
    let moveDir: V2 | null = null
    let boost = false
    let aim: V2 | null = null
    let fire: [boolean, boolean] = [false, false]
    this.mode = "hide"

    if (target && engage) {
      const r = this.combat(target, vis, endgame)
      moveDir = r.move
      moveTo = r.moveTo
      boost = r.boost
      aim = r.aim
      fire = r.fire
      this.mode = r.mode
    } else {
      // not fighting: zone / hide / loot
      this.laserHold = false
      const goal = this.chooseGoal(obs, endgame)
      moveTo = goal
      if (lookYaw !== null) {
        aim = [lookYaw, 0]
        // move toward cover from that bearing
        const cover = this.coverFrom([pos[0] + Math.cos(lookYaw) * 80, pos[1] + Math.sin(lookYaw) * 80, pos[2] + 8], 30)
        if (cover && !endgame) { moveTo = cover; this.mode = "duck" }
      } else if (target) {
        // seen but unaware: keep an eye on it and get out of its sight
        aim = this.aimAt(target, 0).aim
        const cover = this.coverFrom([target.pos[0], target.pos[1], target.pos[2] + 8], 25)
        if (cover) { moveTo = cover; this.mode = "sneak" }
      }
      if (!me.in_zone) boost = me.energy > 25
    }

    // ---- loot and cubes near the route ----
    const take = this.lootChoice(obs)
    if (take) {
      if (take.inReach) { act.take = take.p.id; if (take.drop !== undefined) act.drop = take.drop }
      else if (this.mode === "hide" || this.mode === "sneak") moveTo = [take.p.pos[0], take.p.pos[1]]
    }
    if (this.mode === "hide" && !take) {
      const cube = this.cubeChoice(obs)
      if (cube) moveTo = cube
    }

    // ---- movement ----
    let mv: V2 = [0, 0]
    if (moveDir) mv = moveDir
    else if (moveTo) mv = this.steer(moveTo, obs)
    mv = this.unstick(mv, act)
    act.move = mv
    act.boost = boost
    if (!aim) aim = this.idleAim(obs, mv)
    act.aim = aim
    this.lastAimCmd = aim
    act.fire = fire
    const gun = me.weapons.findIndex((w) => w?.kind === "gun")
    if (gun >= 0) {
      const gw = me.weapons[gun] as WeaponObs
      if ((gw.ammo ?? 1) === 0 && !(gw.reload ?? 0)) act.reload = true
      if (this.mode === "hide" && (gw.ammo ?? 99) < (gw.stats.mag ?? 12) && !(gw.reload ?? 0) && t - this.lastHit > 3) act.reload = true
    }
    return act
  }

  // ---------------------------------------------------------------- perception
  observe(obs: Observation) {
    const t = obs.t
    for (const e of this.enemies.values()) e.visible = false
    for (const m of obs.mechs) {
      if (m.kind === "npc") {
        const n = this.npcs.get(m.id)
        if (n) { n.pos = m.pos; n.seen = t } else this.npcs.set(m.id, { pos: m.pos, seen: t, home: m.pos.slice() })
        continue
      }
      let e = this.enemies.get(m.id)
      if (!e) { e = { id: m.id, pos: m.pos, vel: m.vel, aim: m.aim, hp: m.hp ?? 1400, maxHp: m.max_hp ?? 1400, weapons: m.weapons ?? [], charging: !!m.charging, cubes: m.cubes ?? 0, seen: t, first: t, visible: true }; this.enemies.set(m.id, e) }
      else Object.assign(e, { pos: m.pos, vel: m.vel, aim: m.aim, hp: m.hp ?? e.hp, maxHp: m.max_hp ?? e.maxHp, weapons: m.weapons ?? e.weapons, charging: !!m.charging, cubes: m.cubes ?? e.cubes, seen: t, visible: true })
    }
    for (const ev of obs.events) {
      if (ev.type === "damaged" && ev.by !== null && ev.by !== undefined && ev.by < 100) {
        this.lastHit = t
        this.lastHitBy = ev.by
        if (ev.bearing !== null) this.lastHitBearing = ev.bearing
      } else if (ev.type === "damaged" && ev.by !== null && ev.by !== undefined && ev.bearing !== null) {
        // npc fire: remember it as a danger
        const me = obs.self.pos
        this.dangers.push({ pos: [me[0] + Math.cos(ev.bearing) * 30, me[1] + Math.sin(ev.bearing) * 30], t, w: 1 })
      } else if (ev.type === "kill") {
        this.enemies.delete((ev as any).target)
      } else if (ev.type === "take_failed") {
        this.takeFail.set((ev as any).id, t)
      }
    }
    // sounds of fighting become danger points
    const me = obs.self.pos
    for (const s of obs.sounds) {
      if (s.kind === "step" || s.kind === "reload" || s.kind === "drop" || s.kind === "death") continue
      const r = s.dist === "near" ? 40 : s.dist === "mid" ? 110 : 220
      const w = s.kind === "npc_gun" ? 0.5 : 1
      this.dangers.push({ pos: [me[0] + Math.cos(s.bearing) * r, me[1] + Math.sin(s.bearing) * r], t, w })
    }
    this.dangers = this.dangers.filter((d) => t - d.t < 12).slice(-60)
    for (const [id, e] of this.enemies) if (t - e.seen > 40) this.enemies.delete(id)
  }

  // ---------------------------------------------------------------- goals
  chooseGoal(obs: Observation, endgame: boolean): V2 {
    const t = obs.t
    const z = obs.zone
    const pos = obs.self.pos
    const key = `${z.next_center[0].toFixed(0)},${z.next_center[1].toFixed(0)},${z.next_radius}`
    const zoneChanged = key !== this.zoneKey
    // where must we be: inside the next circle by the time it closes; inside the current one now
    const tight = z.next_radius
    const goalBad = this.goal && (d2(this.goal, z.next_center) > Math.max(tight - 6, tight * 0.85) && t > z.shrink_start - 20)
    const nearEnemy = this.goal && [...this.enemies.values()].some((e) => t - e.seen < 8 && d2(e.pos, this.goal!) < 50)
    if (endgame) {
      // converge on the final circle, fighting whatever is there
      this.goalWhy = "endgame"
      this.goal = [z.next_center[0], z.next_center[1]]
      if (z.next_radius < 5) this.goal = [z.next_center[0], z.next_center[1]]
      return this.goal
    }
    if (!this.goal || zoneChanged || goalBad || nearEnemy || t - this.goalT > this.kn.REHIDE_S) {
      this.zoneKey = key
      this.goal = this.pickHide(obs)
      this.goalT = t
      this.path = null
    }
    return this.goal!
  }

  pickHide(obs: Observation): V2 {
    const z = obs.zone
    const pos = obs.self.pos
    const t = obs.t
    const C = z.next_center
    // ahead of the shrink, the region we may stay in is the next circle; once it is the last circles, the current one
    const R = z.next_radius
    const margin = Math.min(25, R * 0.2) + 6
    const inner = R * this.kn.HIDE_CENTER_FRAC
    let best: V2 = [C[0], C[1]], bs = Infinity
    const E = this.exp
    const known = [...this.enemies.values()].filter((e) => t - e.seen < 25)
    const npcs = [...this.npcs.values()]
    const step = R > 250 ? 12 : R > 120 ? 8 : 4
    const drops = obs.drops.map((d) => d.pos)
    for (let y = C[1] - R; y <= C[1] + R; y += step) {
      if (performance.now() > this.until) break
      for (let x = C[0] - R; x <= C[0] + R; x += step) {
        const dc = Math.hypot(x - C[0], y - C[1])
        if (dc > R - margin) continue
        if (this.w.clearAt(x, y) < 3.2) continue
        let s = 0
        const ev = E ? E.at(x, y) : 0.5
        s += ev * this.kn.HIDE_EXP_W
        s += Math.hypot(x - pos[0], y - pos[1]) * this.kn.HIDE_DIST_W
        if (dc < inner) s += (inner - dc) * 0.4
        for (const e of known) {
          const d = Math.hypot(x - e.pos[0], y - e.pos[1])
          if (d < this.kn.HIDE_ENEMY_R) s += (this.kn.HIDE_ENEMY_R - d) * 0.6 * Math.max(0.3, 1 - (t - e.seen) / 25)
        }
        for (const dg of this.dangers) {
          const d = Math.hypot(x - dg.pos[0], y - dg.pos[1])
          if (d < 90) s += (90 - d) * 0.25 * dg.w
        }
        for (const n of npcs) {
          const d = Math.hypot(x - n.home[0], y - n.home[1])
          if (d < 70) s += (70 - d) * 0.5
        }
        for (const dp of drops) {
          const d = Math.hypot(x - dp[0], y - dp[1])
          if (d < 60) s += (60 - d) * 0.6
        }
        s += this.rng() * 3
        if (s < bs) { bs = s; best = [x, y] }
      }
    }
    return best
  }

  /** a reachable point near us, out of sight of `from` (an eye point) */
  coverFrom(from: number[], maxR: number): V2 | null {
    const pos = this.me.pos
    let best: V2 | null = null, bs = Infinity
    // a spot scores r or r + 10, so once r reaches the best score nothing farther can beat it
    for (let r = 6; r <= maxR && r < bs; r += 6) {
      if (performance.now() > this.until) break
      for (let a = 0; a < 16; a++) {
        const ang = (a / 16) * TAU
        const x = pos[0] + Math.cos(ang) * r, y = pos[1] + Math.sin(ang) * r
        if (this.w.clearAt(x, y) < 3) continue
        const f = this.w.floorAt(x, y)
        if (this.w.los(from[0], from[1], from[2], x, y, f + 9) || this.w.los(from[0], from[1], from[2], x, y, f + 4.5)) continue
        if (!this.nav.straight(pos[0], pos[1], x, y, 2.6)) continue
        const s = r + Math.hypot(x - from[0], y - from[1]) < Math.hypot(pos[0] - from[0], pos[1] - from[1]) ? r + 10 : r
        if (s < bs) { bs = s; best = [x, y] }
      }
    }
    return best
  }

  // ---------------------------------------------------------------- combat
  combat(e: Enemy, vis: Enemy[], endgame: boolean) {
    const me = this.me
    const pos = me.pos
    const d = d2(e.pos, pos)
    const hpFrac = me.hp / me.max_hp
    const weps = me.weapons as (WeaponObs | null)[]
    const has = (k: string) => weps.findIndex((w) => w?.kind === k)
    const iL = has("laser"), iZ = has("lightning"), iG = has("gun"), iM = has("mortar")
    const fire: [boolean, boolean] = [false, false]
    // preferred range
    let pref = 90
    if (iZ >= 0) pref = 30
    else if (iL >= 0) pref = 110
    const outmatched = (hpFrac < this.p.fightHpFrac && e.hp > me.hp * 1.1) || vis.filter((v) => d2(v.pos, pos) < 120).length >= 3
    let mode = "fight"
    let moveTo: V2 | null = null
    let move: V2 | null = null
    let boost = false
    // strafe: perpendicular to the enemy, flip at random intervals
    if (this.t > this.strafeT) { this.strafe = this.rng() < 0.5 ? -1 : 1; this.strafeT = this.t + 0.5 + this.rng() * 0.9 }
    const toE = Math.atan2(e.pos[1] - pos[1], e.pos[0] - pos[0])
    if (outmatched && !endgame) {
      mode = "flee"
      const cover = this.coverFrom([e.pos[0], e.pos[1], e.pos[2] + 8], 40)
      if (cover) moveTo = cover
      else { const a = toE + Math.PI + this.strafe * 0.6; move = [Math.cos(a), Math.sin(a)] }
      boost = me.energy > 30
    } else {
      let radial = 0
      if (d > pref + 25) radial = 1
      else if (d < pref - 25) radial = -1
      const dir = (sgn: number): V2 => {
        const a = toE + sgn * Math.PI / 2
        return [Math.cos(a) + radial * Math.cos(toE) * 0.8, Math.sin(a) + radial * Math.sin(toE) * 0.8]
      }
      let [mx, my] = dir(this.strafe)
      // keep inside walkable space: if the strafe runs into a wall, flip
      if (this.w.clearAt(pos[0] + mx * 6, pos[1] + my * 6) < 2.8) { this.strafe = -this.strafe; [mx, my] = dir(this.strafe) }
      const L = Math.hypot(mx, my) || 1
      move = [mx / L, my / L]
      if (e.charging && Math.abs(wrap(Math.atan2(pos[1] - e.pos[1], pos[0] - e.pos[0]) - e.aim[0])) < 0.2) boost = me.energy > 15
    }
    // weapons
    const g = this.aimAt(e, iG >= 0 ? (weps[iG]!.stats.speed ?? 252) : 252)
    let aim = g.aim
    const muzzle = [pos[0], pos[1], pos[2] + (me.stats.muzzle_height ?? 7)]
    const ts = 1 + 0.05 * (e.cubes ?? 0)
    const losC = this.w.los(muzzle[0], muzzle[1], muzzle[2], e.pos[0], e.pos[1], e.pos[2] + 4.5 * ts)
    const losT = losC || this.w.los(muzzle[0], muzzle[1], muzzle[2], e.pos[0], e.pos[1], e.pos[2] + 8 * ts)
    const yawErr = Math.abs(wrap(me.aim[0] - aim[0]))
    const pitchErr = Math.abs(me.aim[1] - aim[1])
    const tol = Math.atan2(2.2 * ts, d)
    const onTarget = yawErr < tol + 0.01 && pitchErr < Math.atan2(4 * ts, d) + 0.02
    if (iG >= 0 && losT && onTarget && d < (weps[iG]!.stats.range ?? 230)) fire[iG] = true
    if (iZ >= 0) {
      const zw = weps[iZ]!
      const rng = zw.stats.range ?? 45
      if (d < rng * 0.95 && Math.abs(wrap(me.aim[0] - toE)) < ((zw.stats.cone_deg ?? 30) * Math.PI) / 360 && me.energy > 6 && losT) fire[iZ] = true
    }
    if (iL >= 0) {
      const lw = weps[iL]!
      const full = lw.stats.charge ?? 0.75
      const ch = lw.charge ?? 0
      const hitscan = this.aimAt(e, 0).aim
      if (lw.cooldown <= 0.05 && d < (lw.stats.range ?? 280) && losT && mode !== "flee") {
        if (ch < full - 0.03) { fire[iL] = true; aim = hitscan; this.laserHold = true }
        else {
          // release when aimed
          const ye = Math.abs(wrap(me.aim[0] - hitscan[0])), pe = Math.abs(me.aim[1] - hitscan[1])
          aim = hitscan
          if (ye < tol && pe < Math.atan2(4 * ts, d) + 0.01) { fire[iL] = false; this.laserHold = false }
          else if (ch < full + (lw.stats.hold_s ?? 2) - 0.3) fire[iL] = true
        }
      } else if (ch > 0) {
        // charging but lost the shot: release anyway if roughly aimed, else keep holding a little
        fire[iL] = ch < full + 1.2
        aim = hitscan
      }
    }
    if (iM >= 0) {
      const mw = weps[iM]!
      const sol = this.mortarAim(e, mw.stats.speed ?? 72, mw.stats.gravity ?? 22)
      if (sol && mw.cooldown <= 0 && d > 22 && d < 230) {
        // only when the gun is not the better shot this moment
        if (!(iG >= 0 && losT && onTarget) || !losT) {
          aim = sol
          if (Math.abs(wrap(me.aim[0] - sol[0])) < 0.04 && Math.abs(me.aim[1] - sol[1]) < 0.04) fire[iM] = true
        }
      }
    }
    return { move, moveTo, boost, aim, fire, mode }
  }

  /** aim [yaw,pitch] at an enemy's center, leading for a projectile of speed v (0 = hitscan) */
  aimAt(e: Enemy, v: number): { aim: V2 } {
    const me = this.me
    const mz = me.pos[2] + (me.stats.muzzle_height ?? 7)
    const ts = 1 + 0.05 * (e.cubes ?? 0)
    let tx = e.pos[0], ty = e.pos[1], tz = e.pos[2] + 4.5 * ts
    if (v > 0) {
      const age = Math.max(0, this.t - e.seen)
      const vx = e.vel[0], vy = e.vel[1], vz = Math.abs(e.vel[2]) < 1.5 ? 0 : e.vel[2]
      let tt = 0
      for (let k = 0; k < 3; k++) {
        const px = e.pos[0] + vx * (tt + age), py = e.pos[1] + vy * (tt + age), pz = e.pos[2] + 4.5 * ts + vz * Math.min(tt, 0.4)
        tt = Math.hypot(px - me.pos[0], py - me.pos[1], pz - mz) / v
        tx = px; ty = py; tz = pz
      }
    }
    const yaw = Math.atan2(ty - me.pos[1], tx - me.pos[0])
    const pitch = Math.atan2(tz - mz, Math.hypot(tx - me.pos[0], ty - me.pos[1]))
    return { aim: [yaw, pitch] }
  }

  mortarAim(e: Enemy, v: number, g: number): V2 | null {
    const me = this.me
    const mz = me.pos[2] + (me.stats.height ?? 9) + 0.5
    const dx = e.pos[0] - me.pos[0], dy = e.pos[1] - me.pos[1]
    const R = Math.hypot(dx, dy)
    const h = e.pos[2] + 1 - mz
    // low arc solution of v^2 tan... standard formula
    const v2 = v * v
    const disc = v2 * v2 - g * (g * R * R + 2 * h * v2)
    if (disc < 0) return null
    const s = Math.sqrt(disc)
    const pLow = Math.atan2(v2 - s, g * R)
    const pHigh = Math.atan2(v2 + s, g * R)
    const ok = (p: number) => p <= (this.cfg.mech.max_pitch ?? 1.3) && p >= (this.cfg.mech.min_pitch ?? -0.7)
    // lead roughly by flight time
    const p = ok(pLow) ? pLow : ok(pHigh) ? pHigh : null
    if (p === null) return null
    const tof = R / (v * Math.cos(p))
    const lx = e.pos[0] + e.vel[0] * tof * 0.7, ly = e.pos[1] + e.vel[1] * tof * 0.7
    return [Math.atan2(ly - me.pos[1], lx - me.pos[0]), p]
  }

  // ---------------------------------------------------------------- loot
  lootChoice(obs: Observation): { p: PickupObs; inReach: boolean; drop?: number } | null {
    const me = obs.self
    const weps = me.weapons
    const reach = (this.cfg.loot.pickup_radius ?? 4) - 0.4
    let best: { p: PickupObs; inReach: boolean; drop?: number } | null = null, bs = Infinity
    const charging = weps.some((w) => w?.kind === "laser" && (w.charge ?? 0) > 0)
    for (const p of obs.pickups) {
      if (p.kind === "gun") continue
      const ft = this.takeFail.get(p.id)
      if (ft !== undefined && this.t - ft < 3) continue
      if (weps.some((w) => w?.kind === p.kind)) continue
      const empty = weps.findIndex((w) => w === null)
      let drop: number | undefined
      if (empty < 0) {
        // swap the worst non-gun weapon if this one ranks higher
        const worst = weps[1]?.kind === "gun" ? 0 : 1
        const wk = weps[worst]!.kind
        if ((WEAPON_RANK[p.kind] ?? 0) <= (WEAPON_RANK[wk] ?? 0) || wk === "gun") continue
        drop = worst
      }
      const d = d2(p.pos, me.pos)
      const dz = Math.abs(p.pos[2] - me.pos[2])
      if (d > this.p.greedR || dz > 6) continue
      if (charging) continue
      const inReach = d < reach && dz < 3.8
      const s = d - (WEAPON_RANK[p.kind] ?? 0) * 8
      if (s < bs) { bs = s; best = { p, inReach, drop } }
    }
    return best
  }

  cubeChoice(obs: Observation): V2 | null {
    const me = obs.self
    let best: V2 | null = null, bs = Infinity
    for (const c of obs.cubes) {
      const d = d2(c.pos, me.pos)
      if (d > this.p.greedR || Math.abs(c.pos[2] - me.pos[2]) > 4) continue
      if ([...this.enemies.values()].some((e) => this.t - e.seen < 3 && d2(e.pos, c.pos) < 40)) continue
      if (d < bs) { bs = d; best = [c.pos[0], c.pos[1]] }
    }
    return best
  }

  pickUpgrade(ids: string[]): number {
    let bi = 0, bv = -1
    ids.forEach((id, i) => { const v = UPGRADE_RANK[id] ?? 1; if (v > bv) { bv = v; bi = i } })
    return bi
  }

  // ---------------------------------------------------------------- movement
  steer(goal: V2, obs: Observation): V2 {
    const pos = obs.self.pos
    const dg = Math.hypot(goal[0] - pos[0], goal[1] - pos[1])
    if (dg < 2.5) return [0, 0]
    // straight if clear
    if (dg < 60 && this.nav.straight(pos[0], pos[1], goal[0], goal[1], 2.6)) {
      const s = dg < 6 ? 0.5 : 1
      return [((goal[0] - pos[0]) / dg) * s, ((goal[1] - pos[1]) / dg) * s]
    }
    // a search that found nothing is retried after 1 s, one cut by the deadline on the next decision
    const needPath = (!this.path && this.t - this.pathFailT >= 1) || !this.pathGoal || Math.hypot(this.pathGoal[0] - goal[0], this.pathGoal[1] - goal[1]) > 6 || this.t - this.pathT > 4
    if (needPath) {
      this.path = this.nav.find(pos[0], pos[1], goal[0], goal[1], 60000, this.until)
      this.pathGoal = goal
      this.pathT = this.nav.cut ? -99 : this.t
      this.pathI = 0
      if (!this.path && !this.nav.cut) this.pathFailT = this.t
    }
    const path = this.path
    if (!path || path.length < 2) {
      return [(goal[0] - pos[0]) / dg, (goal[1] - pos[1]) / dg]
    }
    // advance along the path: the farthest point within 40 m we can walk to straight
    let i = this.pathI
    let bestI = i
    for (let k = i; k < Math.min(path.length, i + 30); k++) {
      const p = path[k]
      if (Math.hypot(p[0] - pos[0], p[1] - pos[1]) > 40) break
      if (this.nav.straight(pos[0], pos[1], p[0], p[1], 2.5)) bestI = k
    }
    // also drop points already passed
    while (i < path.length - 1 && Math.hypot(path[i][0] - pos[0], path[i][1] - pos[1]) < 3) i++
    this.pathI = Math.max(i, Math.min(bestI, path.length - 1)) === bestI ? bestI : i
    const p = path[Math.max(bestI, i)]
    const dx = p[0] - pos[0], dy = p[1] - pos[1]
    const L = Math.hypot(dx, dy) || 1
    return [dx / L, dy / L]
  }

  unstick(mv: V2, act: Omit<Action, "tick">): V2 {
    const pos = this.me.pos
    const moving = Math.hypot(mv[0], mv[1]) > 0.3
    if (this.t < this.unstickUntil) {
      act.jump = this.me.grounded
      act.boost = !this.me.grounded && this.me.energy > 20
      return this.unstickDir
    }
    if (!moving) { this.stuckRef = [pos[0], pos[1]]; this.stuckT = this.t; return mv }
    if (Math.hypot(pos[0] - this.stuckRef[0], pos[1] - this.stuckRef[1]) > 2.5) { this.stuckRef = [pos[0], pos[1]]; this.stuckT = this.t; return mv }
    if (this.t - this.stuckT > 1.5) {
      // stuck: jump, jet and sidestep, then replan
      const a = Math.atan2(mv[1], mv[0]) + (this.rng() < 0.5 ? 1 : -1) * (0.6 + this.rng())
      this.unstickDir = [Math.cos(a), Math.sin(a)]
      this.unstickUntil = this.t + 0.8
      this.stuckT = this.t
      this.path = null
      act.jump = true
      return this.unstickDir
    }
    return mv
  }

  idleAim(obs: Observation, mv: V2): V2 {
    const pos = obs.self.pos
    // look where trouble would come from: the most recent danger, else the next zone center, else along the move
    let yaw: number
    const recent = this.dangers.filter((d) => this.t - d.t < 6)
    const enemy = [...this.enemies.values()].filter((e) => this.t - e.seen < 10).sort((a, b) => d2(a.pos, pos) - d2(b.pos, pos))[0]
    if (enemy) yaw = Math.atan2(enemy.pos[1] - pos[1], enemy.pos[0] - pos[0])
    else if (recent.length) { const d = recent[recent.length - 1]; yaw = Math.atan2(d.pos[1] - pos[1], d.pos[0] - pos[0]) }
    else if (Math.hypot(mv[0], mv[1]) > 0.3) yaw = Math.atan2(mv[1], mv[0])
    else {
      const c = obs.zone.next_center
      const base = Math.hypot(c[0] - pos[0], c[1] - pos[1]) > 10 ? Math.atan2(c[1] - pos[1], c[0] - pos[0]) : 0
      yaw = base + Math.sin(this.t * 0.5) * 1.2
    }
    return [yaw, 0]
  }
}

/**
 * Runs throwaway brains sharing `b`'s map through made-up peace and fight decisions (foes, a charging laser, bullets,
 * shells, crates, cubes, pickups, hits), so the JIT has compiled them before the first real one: cold (audit on this Mac), a fresh brain's
 * first fight decisions ran 70 to 170 ms against the 50 ms budget (protocol.md §2). Stops at `ms`.
 */
export function warm(b: Brain, hello: Hello, ms = 1500) {
  const end = performance.now() + ms
  const make = b.constructor as new (h: Hello, w: World, n: Nav, e: Exposure | null) => Brain
  const cfg = hello.config
  const z = cfg.zone
  const w = b.w
  const C = z.start_center
  // open ground near the start center, so paths and cover have somewhere to go
  let home = [C[0], C[1]]
  for (let r = 7; r < 300 && w.clearAt(home[0], home[1]) < 8; r += 7) home = [C[0] + Math.cos(r) * r, C[1] + Math.sin(r) * r]
  const at = (x: number, y: number): [number, number, number] => [x, y, w.floorAt(x, y)]
  const kinds = ["gun", "laser", "mortar", "lightning"] as const
  // runs alternate gun only and gun and laser, and weapons in sight or none, to reach every peace mode (loot, search, hide, farm)
  for (let run = 0; run < 12 && performance.now() < end; run++) {
    const brain = new make(hello, w, b.nav, b.exp)
    const withLaser = run % 2 === 1
    const loot = run % 4 < 2
    for (let k = 0; k < 50 && performance.now() < end; k++) {
      const t = 5 + run * 30 + k * 0.1
      const fight = k >= 20
      const ang = run + k * 0.05
      const pos = at(home[0] + Math.cos(ang) * k, home[1] + Math.sin(ang) * k)
      const foes: ActorObs[] = []
      for (let i = 0; fight && i < 1 + (k % 4); i++) {
        const a = ang + i * 1.3
        const d = 40 + i * 35
        const kind = kinds[1 + (i % 3)]
        foes.push({ id: 20 + i, kind: "mech", pos: at(pos[0] + Math.cos(a) * d, pos[1] + Math.sin(a) * d), vel: [4, -2, 0], aim: [a + Math.PI, 0], hp: 900, max_hp: 1400, cubes: i, weapons: ["gun", kind], charging: kind === "laser" && k % 3 === 0 })
      }
      const laser: WeaponObs = { kind: "laser", cooldown: 0, charge: fight && k % 4 > 1 ? 0.4 : 0, stats: cfg.weapons.laser }
      const obs: Observation = {
        type: "obs",
        tick: Math.round(t * 20),
        t,
        alive: 12,
        self: { id: hello.slot, pos, vel: [5, 2, 0], aim: [ang, 0], hp: fight ? 1400 - (k - 20) * (run % 3) * 15 : 1400, max_hp: 1400, energy: 80, max_energy: 100, grounded: true, cubes: run, upgrades: [], weapons: [{ kind: "gun", cooldown: 0, ammo: 12, reload: 0, stats: cfg.weapons.gun }, withLaser ? laser : null], in_zone: true, stats: cfg.mech },
        mechs: [...foes, { id: 900, kind: "npc", pos: at(pos[0] + 90, pos[1] - 40), vel: [0, 0, 0], aim: [0, 0], hp: 300, max_hp: 300 }],
        projectiles: fight ? [
          { id: 5000 + k, kind: "gun", pos: [pos[0] + 30, pos[1] + 5, pos[2] + 7], vel: [-250, -30, 0] },
          { id: 6000 + k, kind: "mortar", pos: [pos[0] - 20, pos[1] + 40, pos[2] + 25], vel: [10, -20, 4] },
        ] : [],
        crates: !loot ? [] : [{ id: 700, pos: at(pos[0] - 60, pos[1] + 30), hp: 200 }],
        cubes: !loot ? [] : [{ id: 800 + run, pos: at(pos[0] + 25, pos[1] + 20) }],
        pickups: !loot ? [] : kinds.map((kind, i) => ({ id: 1000 + i, kind, pos: at(pos[0] + Math.cos(i * 1.6) * (30 + i * 40), pos[1] + Math.sin(i * 1.6) * (30 + i * 40)) })),
        sounds: [{ kind: "gun", bearing: ang + 2, dist: "mid", age: 0.2 }],
        beams: fight && k % 5 === 0 ? [{ by: 20, kind: "laser", path: [foes[0].pos, pos], age: 0 }] : [],
        events: fight && k % 3 === 1 ? [{ type: "damaged", amount: 45, weapon: "gun", bearing: ang + 1, by: 21 }] : [],
        zone: { center: [C[0], C[1]], radius: z.start_radius, next_center: [C[0], C[1]], next_radius: z.phases[0].radius, shrink_start: 60, shrink_end: 110, dps: 20 },
        offer: null,
        drops: [],
      }
      brain.until = performance.now() + 30
      brain.act(obs)
    }
  }
}

/** stderr line for a slow decision, at most one per `gapMs` and `cap` in all, so a slow host can't flood the log */
export function slowLog(say: (line: string) => void, gapMs = 1000, cap = 30) {
  let lastT = -Infinity
  let lines = 0
  let slow = 0
  return (tick: number, ms: number, now: number) => {
    slow++
    if (now - lastT < gapMs || lines >= cap) return
    lastT = now
    lines++
    say(`slow tick ${tick} ${ms.toFixed(0)} ms (${slow} slow so far)`)
  }
}
