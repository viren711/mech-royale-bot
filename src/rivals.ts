// What each other mech is doing and how good it is, from observations alone: who it aims at, how far it leads, how
// often its shots at us land, the range it fights at, whether it turns on whoever hits it, and whether it is busy with
// someone else. Goals read it for P(success) and the arbiter for the hp floor (incoming()).
import type { Observation, SelfObs } from "./mechfight.ts"

export type Rival = {
  id: number
  pos: number[]
  vel: number[]
  aim: number[]
  hp: number
  maxHp: number
  weapons: string[]
  cubes: number
  /** t last seen; visible = seen this tick */
  seen: number
  visible: boolean
  /** laser telegraph: t it started charging, null when not charging */
  chargeSince: number | null
  /** mech id it aims or shoots at (ours included), null when none; targetT = t of that reading */
  target: number | null
  targetT: number
  /** fraction of the full lead its gun aim takes on a moving target (0 aims at the body, 1 leads fully); leadN samples */
  lead: number
  leadN: number
  /** its shots we saw come at us, and the ones that hit (damaged events from it) */
  shotsAtMe: number
  hitsOnMe: number
  dmgToMe: number
  lastHitMe: number
  /** distance to its target while fighting, smoothed; rangeN samples */
  range: number
  rangeN: number
  /** times we hit it while it was on someone else and we were not nearest, and times it turned on us within RETAL_S */
  retalTries: number
  retalYes: number
}

const TAU = Math.PI * 2
const wrap = (a: number) => {
  a = (a + Math.PI) % TAU
  if (a < 0) a += TAU
  return a - Math.PI
}
const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

/** a rival is forgotten this long after it was last seen */
export const MEMORY_S = 8
/** its target reading counts this long */
export const TARGET_S = 1.5
/** a turn onto us this soon after our hit counts as retaliation */
export const RETAL_S = 2.5
const EMA = 0.1

export class Rivals {
  me = -1
  t = 0
  map = new Map<number, Rival>()
  /** gun projectiles already attributed */
  shots = new Set<number>()
  /** open retaliation trials: rival id -> t of our hit */
  trials = new Map<number, number>()
  W: any
  constructor(cfg: any) {
    this.W = cfg.weapons
  }

  update(obs: Observation) {
    const t = (this.t = obs.t)
    const self = obs.self
    this.me = self.id
    for (const r of this.map.values()) r.visible = false
    for (const m of obs.mechs) {
      if (m.kind !== "mech") continue
      let r = this.map.get(m.id)
      if (!r) {
        r = { id: m.id, pos: m.pos, vel: m.vel, aim: m.aim, hp: m.hp ?? 1400, maxHp: m.max_hp ?? 1400, weapons: m.weapons ?? [], cubes: m.cubes ?? 0, seen: t, visible: true, chargeSince: null, target: null, targetT: -99, lead: 0.5, leadN: 0, shotsAtMe: 0, hitsOnMe: 0, dmgToMe: 0, lastHitMe: -99, range: 0, rangeN: 0, retalTries: 0, retalYes: 0 }
        this.map.set(m.id, r)
      }
      r.pos = m.pos
      r.vel = m.vel
      r.aim = m.aim
      r.hp = m.hp ?? r.hp
      r.maxHp = m.max_hp ?? r.maxHp
      r.weapons = m.weapons ?? r.weapons
      r.cubes = m.cubes ?? r.cubes
      r.seen = t
      r.visible = true
      if (!m.charging) r.chargeSince = null
      else if (r.chargeSince === null) r.chargeSince = t
    }
    // bodies we can see this tick, us included, for target readings
    const bodies: { id: number; pos: number[]; vel: number[] }[] = [{ id: self.id, pos: self.pos, vel: self.vel }]
    for (const r of this.map.values()) if (r.visible) bodies.push(r)
    for (const r of this.map.values()) if (r.visible) this.readTarget(r, bodies)
    // beams name their shooter and end at what they hit: the strongest target reading there is
    for (const b of obs.beams) {
      const r = this.map.get(b.by)
      if (!r || !b.path.length) continue
      const end = b.path[b.path.length - 1]
      let hit: { id: number; pos: number[] } | null = null
      let hd = 8
      for (const o of bodies) {
        if (o.id === r.id) continue
        const d = Math.min(d2(o.pos, end), segDist(o.pos, b.path))
        if (d < hd) {
          hd = d
          hit = o
        }
      }
      if (!hit) continue
      r.target = hit.id
      r.targetT = t
      if (hit.id === self.id && b.kind === "laser" && b.age === 0) r.shotsAtMe++
    }
    this.attributeShots(obs, self)
    for (const ev of obs.events) {
      if (ev.type === "damaged" && typeof ev.by === "number") {
        const r = this.map.get(ev.by)
        if (!r) continue
        r.hitsOnMe++
        r.dmgToMe += ev.amount
        r.lastHitMe = t
        r.target = self.id
        r.targetT = t
        // a hit we never saw fired still means a shot
        if (r.hitsOnMe > r.shotsAtMe) r.shotsAtMe = r.hitsOnMe
      } else if (ev.type === "hit") {
        const r = this.map.get(ev.target)
        if (!r || this.trials.has(r.id) || r.target === self.id) continue
        const near = this.nearestTo(r, bodies)
        if (near !== null && near !== self.id) this.trials.set(r.id, t)
      } else if (ev.type === "kill") {
        this.map.delete(ev.target)
        this.trials.delete(ev.target)
      }
    }
    for (const [id, at] of this.trials) {
      const r = this.map.get(id)
      if (!r) {
        this.trials.delete(id)
        continue
      }
      const turned = r.target === self.id && r.targetT >= at
      if (!turned && t - at < RETAL_S) continue
      r.retalTries++
      if (turned) r.retalYes++
      this.trials.delete(id)
    }
    for (const [id, r] of this.map) if (t - r.seen > MEMORY_S) this.map.delete(id)
  }

  /** the body r's aim points at, within a body's width; its gun lead and fighting range from that */
  readTarget(r: Rival, bodies: { id: number; pos: number[]; vel: number[] }[]) {
    let best: { id: number; pos: number[]; vel: number[] } | null = null
    let bs = 1
    for (const o of bodies) {
      if (o.id === r.id) continue
      const d = d2(o.pos, r.pos)
      if (d < 1 || d > 300) continue
      const err = Math.abs(wrap(r.aim[0] - Math.atan2(o.pos[1] - r.pos[1], o.pos[0] - r.pos[0])))
      // a full lead at 250 m on a running mech is about 0.6 rad off the body: score against the larger of the two
      const tof = d / (this.W.gun.speed ?? 252)
      const lx = o.pos[0] + o.vel[0] * tof
      const ly = o.pos[1] + o.vel[1] * tof
      const errL = Math.abs(wrap(r.aim[0] - Math.atan2(ly - r.pos[1], lx - r.pos[0])))
      const s = Math.min(err, errL) / Math.max(0.06, Math.atan2(6, d))
      if (s < bs) {
        bs = s
        best = o
      }
    }
    if (!best) return
    r.target = best.id
    r.targetT = this.t
    const d = d2(best.pos, r.pos)
    r.range = r.rangeN ? r.range + (d - r.range) * EMA : d
    r.rangeN++
    if (!r.weapons.includes("gun")) return
    const b0 = Math.atan2(best.pos[1] - r.pos[1], best.pos[0] - r.pos[0])
    const tof = d / (this.W.gun.speed ?? 252)
    const b1 = Math.atan2(best.pos[1] + best.vel[1] * tof - r.pos[1], best.pos[0] + best.vel[0] * tof - r.pos[0])
    const span = wrap(b1 - b0)
    // the target must cross fast enough that a lead shows against aim noise
    if (Math.abs(span) < 0.03) return
    const k = clamp(wrap(r.aim[0] - b0) / span, -0.5, 1.5)
    r.lead = r.leadN ? r.lead + (k - r.lead) * EMA : k
    r.leadN++
  }

  /** new gun bullets: the shooter is the mech the bullet's path traces back to; count those coming at us */
  attributeShots(obs: Observation, self: SelfObs) {
    const live = new Set<number>()
    for (const p of obs.projectiles) {
      live.add(p.id)
      if (p.kind !== "gun" || this.shots.has(p.id)) continue
      this.shots.add(p.id)
      const sp = Math.hypot(p.vel[0], p.vel[1])
      if (sp < 1) continue
      const ux = p.vel[0] / sp
      const uy = p.vel[1] / sp
      let by: Rival | null = null
      let bd = 6
      for (const r of this.map.values()) {
        if (!r.visible) continue
        // behind the bullet along its path, within a few meters of the line
        const rx = r.pos[0] - p.pos[0]
        const ry = r.pos[1] - p.pos[1]
        const along = rx * ux + ry * uy
        if (along > 2 || along < -260) continue
        const off = Math.abs(rx * uy - ry * ux)
        if (off < bd) {
          bd = off
          by = r
        }
      }
      if (!by) continue
      const mx = self.pos[0] - p.pos[0]
      const my = self.pos[1] - p.pos[1]
      if (mx * ux + my * uy > 0 && Math.abs(mx * uy - my * ux) < 6) by.shotsAtMe++
    }
    for (const id of this.shots) if (!live.has(id)) this.shots.delete(id)
  }

  nearestTo(r: Rival, bodies: { id: number; pos: number[] }[]): number | null {
    let best: number | null = null
    let bd = Infinity
    for (const o of bodies) {
      if (o.id === r.id) continue
      const d = d2(o.pos, r.pos)
      if (d < bd) {
        bd = d
        best = o.id
      }
    }
    return best
  }

  /** rivals seen in the last MEMORY_S seconds */
  list(): Rival[] {
    return [...this.map.values()]
  }

  /** r is on us: aims at us now or hit us in the last 2 s */
  onMe(r: Rival): boolean {
    return (r.target === this.me && this.t - r.targetT < TARGET_S) || this.t - r.lastHitMe < 2
  }

  /** r is fighting another mech right now */
  busy(r: Rival): boolean {
    return r.target !== null && r.target !== this.me && this.t - r.targetT < TARGET_S
  }

  /** chance r turns on whoever hits it rather than staying on its target (0.5 with no evidence) */
  retaliates(r: Rival): number {
    return (r.retalYes + 0.5) / (r.retalTries + 1)
  }

  /** chance a shot of r's at us lands at distance d: a range prior, pulled toward what we saw land */
  pHit(r: Rival, d: number): number {
    const prior = clamp(1.25 - d / 110, 0.08, 0.9)
    return (r.hitsOnMe + 4 * prior) / (r.shotsAtMe + 4)
  }

  /** hp per second r takes off us at distance d while on us */
  dps(r: Rival, d: number): number {
    const W = this.W
    const mul = 1 + 0.04 * Math.min(r.cubes, 10)
    let s = 0
    for (const k of r.weapons) {
      if (k === "gun" && d < W.gun.range) s += (W.gun.damage / W.gun.cooldown) * 0.6 * this.pHit(r, d)
      else if (k === "laser" && d < W.laser.range) s += (W.laser.damage / (W.laser.charge + W.laser.cooldown)) * 0.9
      else if (k === "lightning" && d < W.lightning.range) s += (W.lightning.damage / W.lightning.cooldown) * 0.85
      else if (k === "mortar" && d > 25 && d < 230) s += (W.mortar.damage / W.mortar.cooldown) * 0.35
    }
    return s * mul
  }

  /** expected damage to `self` over the next `horizon` seconds: rivals on us at full rate, a charged laser aimed at us whole */
  incoming(self: SelfObs, horizon: number): number {
    let s = 0
    for (const r of this.map.values()) {
      if (!this.onMe(r)) continue
      const d = d2(r.pos, self.pos)
      s += this.dps(r, d) * horizon
      if (r.chargeSince !== null && r.target === this.me && d < this.W.laser.range) {
        // the beam lands inside the horizon: count it whole instead of its averaged rate
        const left = this.W.laser.charge - (this.t - r.chargeSince)
        if (left < horizon) s += this.W.laser.damage * 0.9 * (1 - horizon / (this.W.laser.charge + this.W.laser.cooldown))
      }
    }
    return s * (1 - (self.stats.armor ?? 0))
  }
}

/** distance from p to a polyline, in the plane */
function segDist(p: number[], path: number[][]): number {
  let best = Infinity
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1]
    const b = path[i]
    const vx = b[0] - a[0]
    const vy = b[1] - a[1]
    const L = vx * vx + vy * vy
    const u = L > 0 ? clamp(((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L, 0, 1) : 0
    best = Math.min(best, Math.hypot(a[0] + vx * u - p[0], a[1] + vy * u - p[1]))
  }
  return best
}
