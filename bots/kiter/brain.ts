// Armed kiter: loot a laser (then lightning) early, farm cubes from drones and crates while no mech is near,
// then fight one enemy at a time at the range our weapons win. Movement in a fight is a short-horizon planner
// that scores candidate moves against the bullets and shells in flight, laser telegraphs, range, cover and walls.
// Zone handling, hiding, path following and unsticking come from the stealth bot.
import type { Action, Hello, Observation, WeaponObs } from "../../src/mechfight.ts"
import { Brain as Stealth } from "../../src/brain.ts"
import type { World } from "../../src/world.ts"
import type { Nav } from "../../src/nav.ts"
import type { Exposure } from "../../src/exposure.ts"
import { KNOBS } from "../../src/knobs.ts"

type V2 = [number, number]
type Body = { id: number; pos: number[]; vel: number[]; r: number; h: number; aimZ: number }
type Foe = { id: number; pos: number[]; vel: number[]; aim: number[]; hp: number; maxHp: number; weapons: string[]; charging: boolean; cubes: number; seen: number; visible: boolean }

const TAU = Math.PI * 2
const wrap = (a: number) => {
  a = (a + Math.PI) % TAU
  if (a < 0) a += TAU
  return a - Math.PI
}
const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

export type KiterParams = {
  leadK: number // fraction of the target's velocity to lead by
  dropGun: boolean // carry laser + lightning instead of keeping the gun
  dodgeW: number // weight of predicted bullet damage in the move planner
  npcR: number // hunt drones seen within this range while no mech is around
  aggro?: boolean // take on any mech in range, aware of us or not (house-bot style), instead of picking fights
}
export const KITER: KiterParams = { leadK: KNOBS.LEAD_K.v, dropGun: false, dodgeW: 1, npcR: 140 }

const RANK: Record<string, number> = {
  laser_damage: 10, laser_charge: 10, armor: 9, plating: 9, nanites: 7, lightning_efficiency: 8, lightning_range: 7,
  gun_rate: 6, gun_damage: 6, servos: 6, gyros: 5, gun_velocity: 5, gun_mag: 4, capacitor: 4, reactor: 4, jets: 3,
  sensors: 3, lightning_chain: 3, laser_pierce: 2, mortar_reload: 1, mortar_velocity: 1, mortar_splash: 1,
}

export class Brain extends Stealth {
  name = "kiter"
  k: KiterParams
  chargeSince = new Map<number, number>()
  hitMeAt = new Map<number, number>()
  hitMeFrom = new Map<number, number>() // attacker id -> bearing of its last hit
  loot = new Map<number, { kind: string; pos: number[] }>()
  shortUntil = -1
  side = 1
  sideUntil = 0
  peaceSince = 0
  focus: number | null = null
  plan = ""
  constructor(hello: Hello, w?: World, nav?: Nav, exp?: Exposure | null, k: KiterParams = KITER) {
    super(hello, w, nav, exp)
    this.k = k
  }

  act(obs: Observation): Omit<Action, "tick"> {
    const me = obs.self
    this.me = me
    const t = (this.t = obs.t)
    const act: Omit<Action, "tick"> = {}
    this.observe(obs)
    this.track(obs)
    if (obs.offer) act.pick = this.pickKit(obs.offer.choices.map((c) => c.id))

    const foes = this.foes()
    const zone = obs.zone
    const kn = this.kn
    const endgame = obs.alive <= kn.END_ALIVE || zone.radius <= kn.END_RADIUS || (zone.next_radius <= kn.END_NEXT_R && t > zone.shrink_start - kn.END_LEAD_S)
    const target = this.pickTarget(foes, endgame)
    let mv: V2 = [0, 0]
    let boost = false
    let aim: V2 | null = null
    let fire: [boolean, boolean] = [false, false]
    this.mode = "peace"

    if (target) {
      this.peaceSince = t
      const r = this.fight(obs, target, foes, endgame)
      mv = r.move
      boost = r.boost
      aim = r.aim
      fire = r.fire
    } else {
      const r = this.peace(obs, endgame)
      mv = r.move
      aim = r.aim
      fire = r.fire
      boost = !me.in_zone && me.energy > kn.ZONE_BOOST_E
      // the laser keeps its charge only while held: let a charge ride until it can be spent
      const iL = me.weapons.findIndex((w) => w?.kind === "laser")
      if (iL >= 0 && (me.weapons[iL]!.charge ?? 0) > 0 && !fire[iL]) fire[iL] = (me.weapons[iL]!.charge ?? 0) < (me.weapons[iL]!.stats.charge ?? 0.75) + 1.6
    }

    const take = this.lootChoice(obs)
    if (take?.inReach) {
      act.take = take.p.id
      if (take.drop !== undefined) act.drop = take.drop
    }
    mv = this.unstick(mv, act)
    act.move = mv
    act.boost = act.boost || boost
    act.aim = aim ?? this.idleAim(obs, mv)
    this.lastAimCmd = act.aim
    act.fire = fire
    const gi = me.weapons.findIndex((w) => w?.kind === "gun")
    if (gi >= 0) {
      const g = me.weapons[gi]!
      // top up only when nobody has been in sight for a while; mid-fight only when nearly dry and not shooting
      const lastSeen = Math.max(-99, ...[...this.enemies.values()].map((e) => e.seen))
      const ammo = g.ammo ?? 99
      const calm = t - lastSeen > 3 && t - this.lastHit > 3 && ammo < (g.stats.mag ?? 12)
      if (!(g.reload ?? 0) && (ammo === 0 || calm || (!fire[gi] && ammo <= 2))) act.reload = true
    }
    return act
  }

  // ---------------------------------------------------------------- perception
  track(obs: Observation) {
    const t = obs.t
    for (const m of obs.mechs) {
      if (m.kind !== "mech") continue
      if (m.charging && !this.chargeSince.has(m.id)) this.chargeSince.set(m.id, t)
      if (!m.charging) this.chargeSince.delete(m.id)
    }
    for (const ev of obs.events as any[]) {
      if (ev.type === "damaged" && typeof ev.by === "number" && ev.by < 100) {
        this.hitMeAt.set(ev.by, t)
        if (typeof ev.bearing === "number") this.hitMeFrom.set(ev.by, ev.bearing)
      }
      if (ev.type === "effect" && ev.effect === "short") this.shortUntil = t + (this.cfg.weapons.lightning.short_s ?? 2)
      if (ev.type === "kill") this.chargeSince.delete(ev.target)
    }
    for (const p of obs.pickups) this.loot.set(p.id, { kind: p.kind, pos: p.pos })
    // forget remembered pickups we should see but do not
    const pos = obs.self.pos
    const seen = new Set(obs.pickups.map((p) => p.id))
    for (const [id, p] of this.loot) {
      if (seen.has(id)) continue
      if (d2(p.pos, pos) < 35 && this.w.los(pos[0], pos[1], pos[2] + 8, p.pos[0], p.pos[1], p.pos[2] + 0.5)) this.loot.delete(id)
    }
  }

  foes(): Foe[] {
    return [...this.enemies.values()].filter((e) => this.t - e.seen < this.kn.FOE_MEMORY_S) as Foe[]
  }

  aimedAtMe(e: Foe, slack = 1): boolean {
    const p = this.me.pos
    const d = d2(e.pos, p)
    const brg = Math.atan2(p[1] - e.pos[1], p[0] - e.pos[0])
    return Math.abs(wrap(e.aim[0] - brg)) < Math.max(0.1, Math.atan2(5, d)) * slack
  }

  aware(e: Foe): boolean {
    return this.aimedAtMe(e, this.kn.AWARE_SLACK) || this.t - (this.hitMeAt.get(e.id) ?? -99) < this.kn.AWARE_HIT_S
  }

  // ---------------------------------------------------------------- fight evaluation
  scaleOf(cubes: number) {
    return 1 + (this.cfg.cubes.size_per_cube ?? 0.05) * cubes
  }

  dmgMul(cubes: number) {
    return 1 + (this.cfg.cubes.damage_per_cube ?? 0.04) * Math.min(cubes, this.cfg.cubes.stat_cap ?? 10)
  }

  /** rough damage per second a loadout lands at distance d; `dodged` = the victim dodges bullets */
  dps(weapons: string[], d: number, cubes: number, dodged: boolean, laserOk = true): number {
    const W = this.cfg.weapons
    let s = 0
    for (const k of weapons) {
      if (k === "gun" && d < W.gun.range) {
        const p = dodged ? clamp(1.25 - d / 110, 0.08, 0.9) : clamp(1.4 - d / 160, 0.2, 0.95)
        s += (W.gun.damage / W.gun.cooldown) * 0.6 * p
      } else if (k === "laser" && d < W.laser.range && laserOk) s += (W.laser.damage / (W.laser.charge + W.laser.cooldown)) * 0.9
      else if (k === "lightning" && d < W.lightning.range * 0.95) s += (W.lightning.damage / W.lightning.cooldown) * 0.85
      else if (k === "mortar" && d > 25 && d < 230) s += (W.mortar.damage / W.mortar.cooldown) * 0.35
    }
    return s * this.dmgMul(cubes)
  }

  myKinds(): string[] {
    const sh = this.t < this.shortUntil
    return (this.me.weapons as (WeaponObs | null)[]).filter((w) => w && !(sh && w.kind === "laser")).map((w) => w!.kind)
  }

  /** the distance band to hold against `e` given both loadouts */
  band(e: Foe): [number, number] {
    const mine = this.myKinds()
    const L = mine.includes("laser"), Z = mine.includes("lightning")
    const eL = e.weapons.includes("laser"), eZ = e.weapons.includes("lightning"), eM = e.weapons.includes("mortar")
    const zr = this.cfg.weapons.lightning.range
    const kn = this.kn
    const arc: [number, number] = [kn.ARC_BAND_LO, zr * kn.ARC_BAND_FRAC]
    if (Z && (eL || eM || !L) && !eZ) return arc
    if (Z && eZ && !L) return arc
    if (L && eZ) return [zr + kn.ARC_GAP, kn.LASER_BAND_HI]
    if (L && !eL) return [kn.LASER_BAND_LO, kn.LASER_BAND_HI]
    if (L && eL) return Z ? arc : [kn.LASER_DUEL_LO, kn.LASER_DUEL_HI]
    if (eZ) return [zr + kn.ARC_GAP, kn.GUN_VS_ARC_HI]
    if (eL) return [kn.GUN_VS_LASER_LO, kn.GUN_VS_LASER_HI]
    if (eM) return [kn.GUN_VS_MORTAR_LO, kn.GUN_VS_MORTAR_HI]
    return [kn.GUN_BAND_LO, kn.GUN_BAND_HI]
  }

  /** seconds for us to kill e vs for e to kill us, at the distance we would hold */
  odds(e: Foe): { mine: number; theirs: number } {
    const me = this.me
    const d = d2(e.pos, me.pos)
    const [lo, hi] = this.band(e)
    const dd = clamp(d, lo, hi)
    const short = e.weapons.includes("lightning") && dd < this.cfg.weapons.lightning.range
    const my = this.dps(this.myKinds(), dd, me.cubes, true, !short)
    const theirLaserOk = !this.myKinds().includes("lightning") || dd > this.cfg.weapons.lightning.range
    const their = this.dps(e.weapons, dd, e.cubes ?? 0, true, theirLaserOk) * (1 - (me.stats.armor ?? 0))
    return { mine: e.hp / Math.max(1, my), theirs: me.hp / Math.max(1, their) }
  }

  pickTarget(foes: Foe[], endgame: boolean): Foe | null {
    const me = this.me
    const kn = this.kn
    let best: Foe | null = null
    let bs = Infinity
    for (const e of foes) {
      const d = d2(e.pos, me.pos)
      if (d > kn.TARGET_R) continue
      const o = this.odds(e)
      const aware = this.aware(e)
      // unaware enemies are only worth starting on when we clearly win and nobody else is around
      const others = foes.filter((f) => f !== e && d2(f.pos, me.pos) < kn.THREAT_R).length
      const free = !aware && o.mine * kn.FREE_ODDS < o.theirs && me.hp > me.max_hp * 0.5 && others === 0 && this.myKinds().length > 1
      const weakPrey = !aware && e.hp < kn.WEAK_HP && o.mine < o.theirs && d < kn.WEAK_R
      if (!this.k.aggro && !aware && !free && !weakPrey && !endgame && d > kn.ENGAGE_R) continue
      let s = o.mine - o.theirs * kn.ODDS_THEIRS_W + d / kn.TARGET_DIST_M
      if (this.t - (this.hitMeAt.get(e.id) ?? -99) < 2) s -= kn.HIT_BONUS
      if (this.focus === e.id) s -= kn.FOCUS_BONUS
      if (s < bs) {
        bs = s
        best = e
      }
    }
    this.focus = best ? best.id : null
    return best
  }

  // ---------------------------------------------------------------- fighting
  fight(obs: Observation, e: Foe, foes: Foe[], endgame: boolean) {
    const me = this.me
    const t = this.t
    const pos = me.pos
    const d = d2(e.pos, pos)
    const o = this.odds(e)
    const threats = foes.filter((f) => f !== e && this.aware(f) && d2(f.pos, pos) < 200)
    // someone we cannot see is hitting us: a threat somewhere along the bearing of its hits
    for (const [id, at] of this.hitMeAt) {
      if (t - at > 2.5 || id === e.id || foes.some((f) => f.id === id)) continue
      const b = this.hitMeFrom.get(id) ?? 0
      threats.push({ id, pos: [pos[0] + Math.cos(b) * 70, pos[1] + Math.sin(b) * 70, pos[2]], vel: [0, 0, 0], aim: [wrap(b + Math.PI), 0], hp: 1400, maxHp: 1400, weapons: ["gun"], charging: false, cubes: 0, seen: at, visible: false })
    }
    const hpFrac = me.hp / me.max_hp
    let retreat = false
    if (!endgame && threats.length > 0) retreat = !(e.hp < 250 && o.mine < 1.5)
    if (!endgame && o.theirs < o.mine * 0.75 && hpFrac < 0.85) retreat = true
    if (!endgame && hpFrac < 0.25 && e.hp > me.hp) retreat = true
    this.mode = retreat ? "retreat" : "fight"

    // ---- weapons and aim
    // shoot the target, or while it is out of sight the nearest visible enemy that is on us
    let shoot = e
    if (!this.hasLos(this.bodyOf(e))) {
      const alt = threats.filter((f) => f.visible && this.hasLos(this.bodyOf(f))).sort((a, b) => d2(a.pos, pos) - d2(b.pos, pos))[0]
      if (alt) shoot = alt
    }
    const w = this.weaponsPlan(this.bodyOf(shoot), d2(shoot.pos, pos), shoot, true)
    // ---- movement
    const band = this.band(e)
    const charging = w.charging
    const cover = retreat ? this.coverFrom([e.pos[0], e.pos[1], e.pos[2] + 8 * this.scaleOf(e.cubes ?? 0)], 45) : null
    const pick = this.planMove(obs, e, [e, ...threats], band, retreat, cover, charging)
    return { move: pick.move, boost: pick.boost, aim: w.aim, fire: w.fire }
  }

  bodyOf(e: { id: number; pos: number[]; vel: number[]; cubes?: number }): Body {
    const npc = e.id >= 100 && e.id < 1000
    const crate = e.id >= 1000 && e.id < 5000
    const s = this.scaleOf(e.cubes ?? 0)
    if (crate) return { id: e.id, pos: e.pos, vel: [0, 0, 0], r: this.cfg.crates?.radius ?? 1.4, h: this.cfg.crates?.height ?? 2.4, aimZ: (this.cfg.crates?.height ?? 2.4) * 0.5 }
    if (npc) return { id: e.id, pos: e.pos, vel: e.vel ?? [0, 0, 0], r: this.cfg.npc.radius, h: this.cfg.npc.height, aimZ: this.cfg.npc.height * 0.5 }
    return { id: e.id, pos: e.pos, vel: e.vel, r: this.cfg.mech.radius * s, h: this.cfg.mech.height * s, aimZ: 4.5 * s }
  }

  /** target position after dt seconds (straight-line motion, ballistic when airborne) */
  predict(b: Body, dt: number): number[] {
    const age = Math.max(0, this.t - (this.enemies.get(b.id)?.seen ?? this.t))
    const tt = dt + age
    const k = this.k.leadK
    const x = b.pos[0] + b.vel[0] * tt * k
    const y = b.pos[1] + b.vel[1] * tt * k
    let z = b.pos[2]
    if (Math.abs(b.vel[2]) > 0.8) {
      z = b.pos[2] + b.vel[2] * tt - 0.5 * (this.cfg.mech.gravity ?? 22) * tt * tt
      const f = this.w.floorAt(x, y)
      if (f <= b.pos[2] + 0.5) z = Math.max(z, f)
    }
    return [x, y, z]
  }

  /** muzzle point at time dt from now (we keep moving at our current velocity) */
  muzzle(dt: number): number[] {
    const me = this.me
    return [me.pos[0] + me.vel[0] * dt, me.pos[1] + me.vel[1] * dt, me.pos[2] + (me.stats.muzzle_height ?? 7)]
  }

  /** [yaw, pitch] that puts a shot of speed v (0 = hitscan) fired `lat` s from now through the target */
  solve(b: Body, v: number, lat: number): { aim: V2; at: number[]; dist: number } {
    const m = this.muzzle(lat)
    let p = this.predict(b, lat)
    if (v > 0) {
      for (let i = 0; i < 4; i++) {
        const tof = Math.hypot(p[0] - m[0], p[1] - m[1], p[2] + b.aimZ - m[2]) / v
        p = this.predict(b, lat + tof)
      }
    }
    const dx = p[0] - m[0], dy = p[1] - m[1]
    const hd = Math.hypot(dx, dy)
    return { aim: [Math.atan2(dy, dx), Math.atan2(p[2] + b.aimZ - m[2], hd)], at: p, dist: hd }
  }

  /** our torso aim one tick from now, slewing from the actual aim toward `cmd` */
  nextAim(cmd: V2): V2 {
    const me = this.me
    const dt = 1 / (this.cfg.match.tick_hz ?? 20)
    const ty = (me.stats.turn_rate ?? 4) * dt
    const tp = (me.stats.pitch_rate ?? 3) * dt
    const dy = wrap(cmd[0] - me.aim[0])
    const dp = cmd[1] - me.aim[1]
    return [wrap(me.aim[0] + clamp(dy, -ty, ty)), me.aim[1] + clamp(dp, -tp, tp)]
  }

  /** would a shot along our aim (after one tick of slew toward cmd) pass through the body at the solved point */
  onTarget(cmd: V2, sol: { aim: V2; dist: number }, b: Body, slack = 1): boolean {
    const a = this.nextAim(cmd)
    if (Math.abs(wrap(this.me.aim[0] - sol.aim[0])) > 0.25) return false
    const d = Math.max(1, sol.dist)
    const ye = Math.abs(wrap(a[0] - sol.aim[0]))
    const pe = Math.abs(a[1] - sol.aim[1])
    return ye < Math.atan2(Math.max(0.4, b.r - 0.45) * slack, d) && pe < Math.atan2(Math.max(0.5, Math.min(b.aimZ, b.h - b.aimZ) - 0.3) * slack, d)
  }

  /** line of sight from our muzzle to the body; moves the aim point up when only the top shows */
  hasLos(b: Body): boolean {
    const m = this.muzzle(0)
    const p = b.pos
    if (this.w.los(m[0], m[1], m[2], p[0], p[1], p[2] + b.aimZ)) return true
    // only the upper body shows over cover: aim there
    if (!this.w.los(m[0], m[1], m[2], p[0], p[1], p[2] + b.h * 0.85)) return false
    b.aimZ = b.h * 0.78
    return true
  }

  /** aim and triggers against one body. Laser: charge on the gun's lead, swing to the hitscan line for release. */
  weaponsPlan(b: Body, d: number, e: Foe | null, mech: boolean) {
    const me = this.me
    const weps = me.weapons as (WeaponObs | null)[]
    const fire: [boolean, boolean] = [false, false]
    const los = this.hasLos(b)
    const iG = weps.findIndex((w) => w?.kind === "gun")
    const iL = weps.findIndex((w) => w?.kind === "laser")
    const iZ = weps.findIndex((w) => w?.kind === "lightning")
    const scan = this.solve(b, 0, 0.05)
    let aim: V2 = scan.aim
    let charging = false
    const g = iG >= 0 ? weps[iG]! : null
    const gunReady = g && (g.ammo ?? 1) > 0 && !(g.reload ?? 0) && d < (g.stats.range ?? 230) * 0.98
    const lead = g ? this.solve(b, g.stats.speed ?? 252, clamp(g.cooldown, 0.05, 0.1)) : scan
    if (gunReady) aim = lead.aim
    if (iL >= 0) {
      const L = weps[iL]!
      const full = L.stats.charge ?? 0.75
      const ch = L.charge ?? 0
      const maxHold = full + (L.stats.hold_s ?? 2)
      const shorted = this.t < this.shortUntil
      // an arc gun in range will short the charge: do not start one
      const shortRisk = !!e && e.weapons.includes("lightning") && d < (this.cfg.weapons.lightning.range ?? 45) + 5 && this.aimedAtMe(e, 2.5)
      if (ch > 0) {
        charging = true
        if (ch >= full - 0.12 || !gunReady) aim = scan.aim
        if (ch >= full - 0.02 && los && d < (L.stats.range ?? 280) && this.onTarget(scan.aim, scan, b)) fire[iL] = false
        else fire[iL] = ch < maxHold - 0.2 || !los
        // about to auto-fire into nothing: let it go on the best line we have
        if (ch >= maxHold - 0.2) fire[iL] = false
      } else if (!shorted && !shortRisk && los && d < (L.stats.range ?? 280) && L.cooldown <= 0.1) {
        fire[iL] = true
        charging = true
      }
    }
    if (g && gunReady && los && this.onTarget(aim, lead, b)) fire[iG] = true
    if (iZ >= 0) {
      const Z = weps[iZ]!
      const cone = ((Z.stats.cone_deg ?? 30) * Math.PI) / 360
      const brg = Math.atan2(b.pos[1] - me.pos[1], b.pos[0] - me.pos[0])
      const inCone = Math.abs(wrap(this.nextAim(aim)[0] - brg)) < cone - 0.04
      const reserve = mech ? 3 : 25
      if (d < (Z.stats.range ?? 45) - 1.5 && inCone && los && me.energy >= (Z.stats.energy ?? 3) + reserve - 3) fire[iZ] = true
      // nothing else to do at arc range: point straight at it
      if (d < (Z.stats.range ?? 45) && !charging && !gunReady) aim = scan.aim
    }
    return { aim, fire, charging, los }
  }

  // ---------------------------------------------------------------- the move planner
  planMove(obs: Observation, e: Foe, watchers: Foe[], band: [number, number], retreat: boolean, cover: V2 | null, charging: boolean) {
    const me = this.me
    const t = this.t
    const pos = me.pos
    const M = this.cfg.mech
    const R = me.stats.radius ?? M.radius
    const H = me.stats.height ?? M.height
    const walk = me.stats.walk_speed ?? M.walk_speed
    const boostSp = me.stats.boost_speed ?? M.boost_speed
    const accel = me.grounded ? M.ground_accel : M.air_accel
    const kn = this.kn
    const toE = Math.atan2(e.pos[1] - pos[1], e.pos[0] - pos[0])
    const dNow = d2(e.pos, pos)
    if (t > this.sideUntil) {
      this.side = this.rng() < 0.5 ? -1 : 1
      this.sideUntil = t + kn.SIDE_MIN_S + this.rng() * kn.SIDE_SPAN_S
    }
    const zone = obs.zone
    const zf = clamp((t - zone.shrink_start) / Math.max(1, zone.shrink_end - zone.shrink_start), 0, 1)
    const zc = [zone.center[0] + (zone.next_center[0] - zone.center[0]) * zf, zone.center[1] + (zone.next_center[1] - zone.center[1]) * zf]
    const zr = zone.radius + (zone.next_radius - zone.radius) * zf
    const laserOnMe = watchers.filter((f) => f.charging && this.aimedAtMe(f, 1.6))
    const hasZ = this.myKinds().includes("lightning")
    const energyFloor = hasZ ? kn.BOOST_FLOOR_ARC : kn.BOOST_FLOOR
    // projectiles that can reach us
    const shots = obs.projectiles.filter((p) => {
      const rel = [pos[0] - p.pos[0], pos[1] - p.pos[1]]
      const sp = Math.hypot(p.vel[0], p.vel[1]) || 1
      const along = (rel[0] * p.vel[0] + rel[1] * p.vel[1]) / sp
      return along > -6 && along < sp * 1.0 + 20 && p.kind !== "mortar"
    })
    const shells = obs.projectiles.filter((p) => p.kind === "mortar").map((p) => this.shellImpact(p)).filter((s): s is { at: number[]; t: number } => !!s && s.t < kn.SHELL_HORIZON_S)
    const W = this.cfg.weapons
    const DT = 0.05
    const N = 16
    let best: { move: V2; boost: boolean } = { move: [0, 0], boost: false }
    let bs = Infinity
    const ePred = [e.pos[0] + e.vel[0] * 0.4, e.pos[1] + e.vel[1] * 0.4, e.pos[2]]
    for (let c = 0; c <= 32; c++) {
      // past the decision deadline: the best candidate scored so far
      if (c > 0 && performance.now() > this.until) break
      const boost = c > 16
      if (boost && me.energy < energyFloor) break
      const k = c > 16 ? c - 17 : c
      const stop = k === 16
      const ang = (k / 16) * TAU
      const dir: V2 = stop ? [0, 0] : [Math.cos(ang), Math.sin(ang)]
      if (stop && boost) continue
      let sp = boost ? boostSp : walk
      if (charging) sp *= M.charge_move_mult ?? 0.5
      let vx = me.vel[0], vy = me.vel[1]
      let x = pos[0], y = pos[1]
      const path: number[][] = [[x, y]]
      let blocked = false
      for (let s = 0; s < N; s++) {
        const tvx = dir[0] * sp, tvy = dir[1] * sp
        const dvx = tvx - vx, dvy = tvy - vy
        const dv = Math.hypot(dvx, dvy)
        const a = accel * DT
        if (dv <= a) {
          vx = tvx
          vy = tvy
        } else {
          vx += (dvx / dv) * a
          vy += (dvy / dv) * a
        }
        const nx = x + vx * DT, ny = y + vy * DT
        if (this.w.clearAt(nx, ny) < R * 0.95 || Math.abs(this.w.floorAt(nx, ny) - this.w.floorAt(x, y)) > (M.step_up ?? 1.2)) {
          blocked = true
          vx = 0
          vy = 0
        } else {
          x = nx
          y = ny
        }
        path.push([x, y])
      }
      const end = path[N]
      let score = 0
      // bullets in flight: exact closest approach per 0.05 s segment
      let hurt = 0
      for (const p of shots) {
        const dmg = (p.kind === "npc" ? this.cfg.npc.damage : W.gun.damage * kn.BULLET_DMG_K)
        let dmin = Infinity
        let zAt = 0
        for (let s = 0; s < N; s++) {
          const t0 = s * DT
          const bx0 = p.pos[0] + p.vel[0] * t0 - path[s][0], by0 = p.pos[1] + p.vel[1] * t0 - path[s][1]
          const rvx = p.vel[0] - (path[s + 1][0] - path[s][0]) / DT, rvy = p.vel[1] - (path[s + 1][1] - path[s][1]) / DT
          const rv2 = rvx * rvx + rvy * rvy || 1e-9
          const f = clamp(-(bx0 * rvx + by0 * rvy) / rv2, 0, DT)
          const cx = bx0 + rvx * f, cy = by0 + rvy * f
          const dd = Math.hypot(cx, cy)
          if (dd < dmin) {
            dmin = dd
            zAt = p.pos[2] + p.vel[2] * (t0 + f)
          }
        }
        if (zAt < pos[2] - 0.5 || zAt > pos[2] + H + 0.5) continue
        hurt += dmg * clamp((R + 1.3 - dmin) / 1.1, 0, 1)
      }
      score += hurt * this.k.dodgeW
      // shells: where we stand when they land
      for (const s of shells) {
        const i = Math.min(N, Math.round(s.t / DT))
        const px = path[i][0] + (s.t > N * DT ? vx * (s.t - N * DT) : 0), py = path[i][1] + (s.t > N * DT ? vy * (s.t - N * DT) : 0)
        const dd = Math.hypot(px - s.at[0], py - s.at[1])
        const rad = W.mortar.splash_radius + R + 1
        if (dd < rad) score += W.mortar.splash * (1 - 0.7 * dd / rad) * kn.SHELL_K
      }
      // a laser aimed at us: being seen at release is the cost, sideways speed helps a little
      for (const f of laserOnMe) {
        const seen = this.w.los(f.pos[0], f.pos[1], f.pos[2] + 8, end[0], end[1], this.w.floorAt(end[0], end[1]) + H * 0.5)
        const brg = Math.atan2(end[1] - f.pos[1], end[0] - f.pos[0])
        const fd = d2(f.pos, end)
        const off = Math.abs(wrap(brg - f.aim[0])) * fd
        score += seen ? W.laser.damage * clamp(1.2 - off / (R + 2), 0.3, 1) : 0
      }
      const dEnd = Math.hypot(end[0] - ePred[0], end[1] - ePred[1])
      if (retreat) {
        // get out of their sight, toward cover if we know some
        for (const f of watchers) {
          const fEye = f.pos[2] + 8 * this.scaleOf(f.cubes ?? 0)
          if (this.w.los(f.pos[0], f.pos[1], fEye, end[0], end[1], this.w.floorAt(end[0], end[1]) + H * 0.8)) score += kn.RETREAT_SEEN_COST
          score -= Math.min(40, d2(f.pos, end) - d2(f.pos, pos)) * 1.2
        }
        if (cover) score += Math.hypot(end[0] - cover[0], end[1] - cover[1]) * kn.COVER_W
      } else {
        // hold the band, keep sight of the target, keep moving sideways in the current direction
        const lo = band[0], hi = band[1]
        if (dEnd < lo) score += (lo - dEnd) * kn.BAND_W
        if (dEnd > hi) score += (dEnd - hi) * kn.BAND_W
        const sees = this.w.los(end[0], end[1], this.w.floorAt(end[0], end[1]) + (me.stats.muzzle_height ?? 7), e.pos[0], e.pos[1], e.pos[2] + 4.5)
        if (!sees) score += kn.LOS_LOST_COST
        if (!stop) {
          const want = toE + this.side * Math.PI / 2
          score += (1 - Math.cos(wrap(ang - want))) * kn.STRAFE_W
        } else score += kn.STOP_COST
        // other enemies seeing us is a cost
        for (const f of watchers) {
          if (f === e) continue
          const fEye = f.pos[2] + 8 * this.scaleOf(f.cubes ?? 0)
          if (this.w.los(f.pos[0], f.pos[1], fEye, end[0], end[1], this.w.floorAt(end[0], end[1]) + H * 0.8)) score += kn.WATCHER_COST
        }
      }
      // keep every watcher inside our front arc: moving away from two enemies narrows their spread
      if (watchers.length > 1) {
        const a0 = Math.atan2(watchers[0].pos[1] - end[1], watchers[0].pos[0] - end[0])
        for (const f of watchers.slice(1)) {
          const sep = Math.abs(wrap(Math.atan2(f.pos[1] - end[1], f.pos[0] - end[0]) - a0))
          if (sep > Math.PI / 2) score += (sep - Math.PI / 2) * kn.SPREAD_W
        }
      }
      if (blocked) score += kn.BLOCKED_COST
      score += Math.max(0, kn.WALL_CLEAR - this.w.clearAt(end[0], end[1])) * kn.WALL_W
      const dz = Math.hypot(end[0] - zc[0], end[1] - zc[1])
      if (dz > zr - kn.ZONE_EDGE_M) score += (dz - zr + kn.ZONE_EDGE_M) * kn.ZONE_EDGE_W
      if (boost) score += kn.BOOST_COST + (hasZ ? kn.BOOST_COST_ARC : 0)
      score += this.moveCost(end, watchers, retreat, path)
      if (score < bs) {
        bs = score
        best = { move: dir, boost }
      }
    }
    return best
  }

  /** a subclass's extra cost for a planned move ending at `end`; `path` is x, y every 0.05 s from where we stand */
  moveCost(_end: number[], _watchers: Foe[], _retreat: boolean, _path?: number[][]): number {
    return 0
  }

  /** where and when a mortar shell lands */
  shellImpact(p: { pos: number[]; vel: number[] }): { at: number[]; t: number } | null {
    const g = this.cfg.weapons.mortar.gravity ?? 22
    let [x, y, z] = p.pos
    let vz = p.vel[2]
    const dt = 0.05
    for (let s = 1; s < 100; s++) {
      x += p.vel[0] * dt
      y += p.vel[1] * dt
      vz -= g * dt
      z += vz * dt
      if (this.w.solid(x, y, z)) return { at: [x, y, z], t: s * dt }
    }
    return null
  }

  // ---------------------------------------------------------------- peace: loot, cubes, drones, crates, then hide
  peace(obs: Observation, endgame: boolean): { move: V2; aim: V2 | null; fire: [boolean, boolean] } {
    const me = this.me
    const t = this.t
    const pos = me.pos
    let fire: [boolean, boolean] = [false, false]
    let aim: V2 | null = null
    let goal: V2 = this.chooseGoal(obs, endgame)
    this.mode = "hide"
    const zone = obs.zone
    const safe = (p: number[]) => {
      const R = t > zone.shrink_start - 25 ? zone.next_radius : zone.radius
      const C = t > zone.shrink_start - 25 ? zone.next_center : zone.center
      return d2(p, C) < R - 10
    }
    const mechNear = [...this.enemies.values()].some((e) => t - e.seen < 6 && d2(e.pos, pos) < 160)
    // an unseen shooter: face it
    if (t - this.lastHit < 2 && this.lastHitBy !== null) aim = [this.lastHitBearing, 0]
    if (!endgame) {
      const want = this.wanted()
      let lootGoal: number[] | null = null
      let ls = Infinity
      const lootR = t < 100 ? 170 : 60
      for (const [, p] of this.loot) {
        if (!want.includes(p.kind) || !safe(p.pos)) continue
        const d = d2(p.pos, pos)
        if (d > lootR || Math.abs(p.pos[2] - pos[2]) > 8) continue
        const s = d - (p.kind === want[0] ? 40 : 0)
        if (s < ls) {
          ls = s
          lootGoal = p.pos
        }
      }
      if (lootGoal) {
        goal = [lootGoal[0], lootGoal[1]]
        this.mode = "loot"
      } else if (!mechNear) {
        const cube = obs.cubes.filter((c) => d2(c.pos, pos) < 80 && Math.abs(c.pos[2] - pos[2]) < 4 && safe(c.pos)).sort((a, b) => d2(a.pos, pos) - d2(b.pos, pos))[0]
        if (cube) {
          goal = [cube.pos[0], cube.pos[1]]
          this.mode = "cube"
        } else {
          const prey = this.prey(obs)
          if (prey) {
            const b = this.bodyOf(prey)
            const d = d2(prey.pos, pos)
            const w = this.weaponsPlan(b, d, null, false)
            aim = w.aim
            fire = w.fire
            this.mode = "farm"
            const isNpc = prey.id < 1000
            // drones: stand off outside their reach and keep sight; crates: walk up to the drop
            if (isNpc) {
              const hasZ = this.myKinds().includes("lightning")
              const want = hasZ ? 30 : 60
              if (d > want + 15 || !w.los) goal = [prey.pos[0], prey.pos[1]]
              else {
                const away = Math.atan2(pos[1] - prey.pos[1], pos[0] - prey.pos[0]) + this.side * 0.6
                goal = [prey.pos[0] + Math.cos(away) * want, prey.pos[1] + Math.sin(away) * want]
                if (t > this.sideUntil) {
                  this.side = -this.side
                  this.sideUntil = t + 1 + this.rng()
                }
              }
            } else if (!w.los || d > 120) goal = [prey.pos[0], prey.pos[1]]
            else goal = [pos[0], pos[1]]
          }
        }
      }
    }
    const move = this.steer(goal, obs)
    return { move, aim, fire }
  }

  /** weapon kinds still worth picking up, best first */
  wanted(): string[] {
    const kinds = (this.me.weapons as (WeaponObs | null)[]).filter(Boolean).map((w) => w!.kind)
    const out: string[] = []
    if (!kinds.includes("laser")) out.push("laser")
    if (!kinds.includes("lightning") && (kinds.includes("mortar") || kinds.length < 2 || (this.k.dropGun && kinds.includes("gun")))) out.push("lightning")
    return out
  }

  /** a drone or crate worth shooting now: early, healthy, nobody around */
  prey(obs: Observation): { id: number; pos: number[]; vel: number[] } | null {
    const me = this.me
    const pos = me.pos
    if (me.hp < me.max_hp * 0.6 || me.cubes >= 10) return null
    let best: { id: number; pos: number[]; vel: number[] } | null = null
    let bs = Infinity
    for (const m of obs.mechs) {
      if (m.kind !== "npc") continue
      const d = d2(m.pos, pos)
      if (d > this.k.npcR) continue
      if (d < bs) {
        bs = d
        best = m
      }
    }
    for (const c of obs.crates ?? []) {
      const d = d2(c.pos, pos)
      if (d > 90 || d + 30 > bs) continue
      bs = d + 30
      best = { id: c.id, pos: c.pos, vel: [0, 0, 0] }
    }
    return best
  }

  /** take wanted loot in reach; dropping the gun or a mortar when both slots are full */
  lootChoice(obs: Observation) {
    const me = obs.self
    const weps = me.weapons
    const reach = (this.cfg.loot.pickup_radius ?? 4) - 0.4
    if (weps.some((w) => w?.kind === "laser" && (w.charge ?? 0) > 0)) return null
    const want = this.wanted()
    for (const p of obs.pickups) {
      if (!want.includes(p.kind)) continue
      const ft = this.takeFail.get(p.id)
      if (ft !== undefined && this.t - ft < 3) continue
      const d = d2(p.pos, me.pos)
      if (d > reach || Math.abs(p.pos[2] - me.pos[2]) > 3.8) continue
      let drop: number | undefined
      if (!weps.some((w) => w === null)) {
        drop = weps.findIndex((w) => w?.kind === "mortar")
        if (drop < 0 && p.kind === "laser") drop = weps.findIndex((w) => w?.kind === "lightning")
        if (drop < 0 && this.k.dropGun) drop = weps.findIndex((w) => w?.kind === "gun")
        if (drop < 0) continue
      }
      return { p, inReach: true, drop }
    }
    return null
  }

  pickKit(ids: string[]): number {
    const kinds = (this.me.weapons as (WeaponObs | null)[]).filter(Boolean).map((w) => w!.kind)
    let bi = 0
    let bv = -1
    ids.forEach((id, i) => {
      let v = RANK[id] ?? 1
      if (id.startsWith("laser") && !kinds.includes("laser")) v = 1
      if (id.startsWith("lightning") && !kinds.includes("lightning")) v = 1
      if (v > bv) {
        bv = v
        bi = i
      }
    })
    return bi
  }
}
