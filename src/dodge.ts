// Self-preservation against the two shooters the field is made of (mech-crazy rows 3 and 4).
// Gun: most rival builds aim at linear lead, our position plus our observed velocity times the bullet's flight, so a
// bullet fired off what they see now lands where we would be if we held our velocity. Jink is the move that misses it,
// a weave across the gunner's line; shotCost scores a planned path by the bullets such a shooter fires along it.
// Laser: hitscan along the shooter's aim at release, and its turn rate tracks any sideways step, so the only escape is
// out of its sight. laserThreats is the trigger, breakLos the per-decision move, hiddenFrom the done test.
import type { World } from "./world.ts"

type V2 = [number, number]
const wrap = (a: number) => {
  a = (a + Math.PI) % (Math.PI * 2)
  if (a < 0) a += Math.PI * 2
  return a - Math.PI
}

export const DT = 0.05
// seconds from the observation a shooter reads to its bullet leaving the barrel: its answer applies on the next tick
// (protocol.md §2, 2 ticks per decision), about 1.5 ticks on average
export const SHOT_LAT = 0.075
// gun cooldown 0.24 s against a decision every 0.1 s: a held trigger fires on this share of decisions
const DUTY = 0.1 / 0.24

/** a mech that may be shooting at us: feet position, velocity, torso aim, cubes; `lead` the share of our velocity its
 * gun aim takes (1 when unknown: most rival builds lead fully) */
export type Shooter = { pos: number[]; vel: number[]; aim: number[]; cubes?: number; weapons: string[]; charging: boolean; visible: boolean; lead?: number }

/** where a linear-lead gunner at muzzle m aims at a target at p moving at v, and the bullet's flight time */
export function leadPoint(m: number[], p: number[], v: number[], speed: number, lat = SHOT_LAT): { at: V2; tof: number } {
  let tof = 0
  let x = p[0], y = p[1]
  for (let k = 0; k < 4; k++) {
    x = p[0] + v[0] * (lat + tof)
    y = p[1] + v[1] * (lat + tof)
    tof = Math.max(0, Math.hypot(x - m[0], y - m[1]) - 3) / speed
  }
  return { at: [x, y], tof }
}

/** standard normal cdf (Abramowitz-Stegun 7.1.26 through erf) */
function phi(z: number): number {
  const x = Math.abs(z) / Math.SQRT2
  const t = 1 / (1 + 0.3275911 * x)
  const e = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x)
  return z >= 0 ? 0.5 * (1 + e) : 0.5 * (1 - e)
}

/** our position at time t along a path sampled every DT, held at the last step's velocity past its end */
function at(path: number[][], t: number): V2 {
  const n = path.length - 1
  const f = t / DT
  if (f >= n) {
    const a = path[n - 1], b = path[n]
    const over = f - n
    return [b[0] + (b[0] - a[0]) * over, b[1] + (b[1] - a[1]) * over]
  }
  const i = Math.floor(f), u = f - i
  return [path[i][0] + (path[i + 1][0] - path[i][0]) * u, path[i][1] + (path[i + 1][1] - path[i][1]) * u]
}

export type GunCfg = { damage: number; speed: number; range: number; spread_deg: number }

/** expected gun damage from linear-lead shooters off our state now and each of the next n - 1 decisions (2 steps
 * apart), along `path` (x, y every DT from now; path[0] is where we stand), `vel0` our velocity now, `R` our radius.
 * Two shots score braking as an escape; four see a stop or a held line as the target it is. */
export function shotCost(path: number[][], vel0: number[], shooters: Shooter[], R: number, gun: GunCfg, n = 2): number {
  let cost = 0
  const sigma = (gun.spread_deg * Math.PI) / 180
  for (const f of shooters) {
    const m = [f.pos[0], f.pos[1], f.pos[2]]
    for (let k = 0; k < n; k++) {
      const i = 2 * k
      const p = path[i]
      const L = f.lead ?? 1
      const v = k === 0 ? [vel0[0] * L, vel0[1] * L] : [((path[i][0] - path[i - 1][0]) / DT) * L, ((path[i][1] - path[i - 1][1]) / DT) * L]
      const { at: aimAt, tof } = leadPoint(m, p, v, gun.speed)
      const d = Math.hypot(aimAt[0] - m[0], aimAt[1] - m[1])
      if (d > gun.range) continue
      const q = at(path, k * 2 * DT + SHOT_LAT + tof)
      // miss across the line of fire
      const lx = (aimAt[0] - m[0]) / (d || 1), ly = (aimAt[1] - m[1]) / (d || 1)
      const miss = (q[0] - aimAt[0]) * ly - (q[1] - aimAt[1]) * lx
      const s = Math.max(0.3, d * sigma)
      cost += gun.damage * DUTY * (phi((R - miss) / s) - phi((-R - miss) / s))
    }
  }
  return cost
}

/** visible gun holders whose aim is on us (within the lead angle of our bearing) and in gun range */
export function gunners(foes: Shooter[], pos: number[], range: number): Shooter[] {
  return foes.filter((f) => {
    if (!f.visible || !f.weapons.includes("gun")) return false
    const d = Math.hypot(pos[0] - f.pos[0], pos[1] - f.pos[1])
    if (d > range) return false
    const brg = Math.atan2(pos[1] - f.pos[1], pos[0] - f.pos[0])
    return Math.abs(wrap(f.aim[0] - brg)) < Math.max(0.08, Math.atan2(6, d))
  })
}

/** a laser on us: the shooter, its eye and the seconds until it can release a full charge */
export type LaserThreat = { f: Shooter; eye: number[]; eta: number }

// the reflex fires on aims within this of our bearing (3 degrees), or our body's half width when closer
export const LASER_AIM = (3 * Math.PI) / 180

/** visible mechs charging a laser with their aim on us, within laser range */
export function laserThreats(foes: Shooter[], pos: number[], R: number, range: number, since: (f: Shooter) => number, full: number, t: number): LaserThreat[] {
  const out: LaserThreat[] = []
  for (const f of foes) {
    if (!f.visible || !f.charging) continue
    const d = Math.hypot(pos[0] - f.pos[0], pos[1] - f.pos[1])
    if (d > range) continue
    const brg = Math.atan2(pos[1] - f.pos[1], pos[0] - f.pos[0])
    if (Math.abs(wrap(f.aim[0] - brg)) > Math.max(LASER_AIM, Math.atan2(R, d))) continue
    const s = 1 + 0.05 * (f.cubes ?? 0)
    out.push({ f, eye: [f.pos[0], f.pos[1], f.pos[2] + 7 * s], eta: Math.max(DT, full - (t - since(f))) })
  }
  return out
}

/** whether no threat's eye sees our body (its middle or its top) standing at (x, y) on the floor there */
export function hiddenFrom(w: World, threats: LaserThreat[], x: number, y: number, z: number, H: number): boolean {
  for (const { eye } of threats) {
    if (w.los(eye[0], eye[1], eye[2], x, y, z + H * 0.5, 2)) return false
    if (w.los(eye[0], eye[1], eye[2], x, y, z + H * 0.9, 2)) return false
  }
  return true
}

export type Body = { pos: number[]; vel: number[]; R: number; H: number; walk: number; accel: number; stepUp: number; grounded: boolean }

/** x, y, z every DT for `steps` steps holding direction `dir` at walking speed (path[0] is where we stand); walls stop
 * us, roof edges do not (we drop to the floor below) */
export function walk(w: World, me: Body, dir: V2, steps: number): number[][] {
  let vx = me.vel[0], vy = me.vel[1]
  let x = me.pos[0], y = me.pos[1]
  let z = me.pos[2]
  const out = [[x, y, z]]
  const a = me.accel * DT
  for (let s = 1; s <= steps; s++) {
    const dvx = dir[0] * me.walk - vx, dvy = dir[1] * me.walk - vy
    const dv = Math.hypot(dvx, dvy)
    if (dv <= a) {
      vx = dir[0] * me.walk
      vy = dir[1] * me.walk
    } else {
      vx += (dvx / dv) * a
      vy += (dvy / dv) * a
    }
    const nx = x + vx * DT, ny = y + vy * DT
    const nf = w.floorAt(nx, ny)
    if (w.clearAt(nx, ny) < me.R * 0.95 || nf - z > me.stepUp) {
      vx = 0
      vy = 0
    } else {
      x = nx
      y = ny
      // off a roof edge we fall; the body shows lower as it drops, counted at the floor it lands on
      z = nf
    }
    out.push([x, y, z])
  }
  return out
}

const dirOf = (c: number): V2 => (c === 16 ? [0, 0] : [Math.cos((c / 16) * Math.PI * 2), Math.sin((c / 16) * Math.PI * 2)])

/** the walk out of every threat's sight by its release: 16 directions and a stop, each held. The move seen for the
 * fewest steps from just before the earliest release through 0.4 s after it, first hidden at the earliest step, or null
 * when none hides us at the release. `prefer` breaks ties. */
export function breakLos(w: World, threats: LaserThreat[], me: Body, prefer: V2): V2 | null {
  if (!threats.length) return null
  const eta = Math.min(...threats.map((x) => x.eta))
  const lo = Math.max(0, Math.floor(eta / DT) - 2)
  const hi = Math.ceil((eta + 0.4) / DT)
  const pl = Math.hypot(prefer[0], prefer[1])
  let best: V2 | null = null
  let bs = Infinity
  for (let c = 0; c <= 16; c++) {
    const dir = dirOf(c)
    const path = walk(w, me, dir, hi)
    let seen = 0
    let first = -1
    for (let s = Math.max(1, lo); s <= hi; s += 2) {
      const [x, y, z] = path[s]
      if (!hiddenFrom(w, threats, x, y, z, me.H)) seen++
      else if (first < 0) first = s
    }
    if (first < 0 || first > Math.ceil(eta / DT) + 1) continue
    // ties: the earliest hide, then the move nearest the one we would make anyway
    const align = pl > 0.1 && c < 16 ? (dir[0] * prefer[0] + dir[1] * prefer[1]) / pl : 0
    const score = seen * 10 + first - align * 0.5
    if (score < bs) {
      bs = score
      best = dir
    }
  }
  return best
}

/** The weave a linear lead misses. A bullet fired off our velocity now lands where that velocity carries us over its
 * flight, so what it misses is a change of sideways velocity within the flight: at 58.5 m/s² a reversal clears the
 * 2.8 m a hit needs in about 0.3 s. Scoring moves one decision at a time (shotCost) picks a reversal every decision,
 * and those cancel into a 3 m/s jitter every shot hits; the weave instead holds each side across the nearest gunner's
 * line for a leg of `lo` to `lo + span` seconds (0.4 to 0.6 s took a k1 lead's share at 130 m from 61% for duo's
 * strafe timer to 23% in a closed loop), at least `lat` of the move sideways, the move's part along the line kept. */
export class Jink {
  side = 1
  until = -1
  constructor(public lo = 0.4, public span = 0.2, public lat = 0.7, public minD = 50, public rng: () => number = Math.random) {}

  /** `want` turned onto this leg's side of the nearest gunner farther than minD; `want` itself in the air (12 m/s²
   * cannot weave) or with no such gunner */
  move(w: World, me: Body, want: V2, shooters: Shooter[], t: number): V2 {
    if (!me.grounded) return want
    let f: Shooter | null = null
    let fd = Infinity
    for (const s of shooters) {
      const d = Math.hypot(me.pos[0] - s.pos[0], me.pos[1] - s.pos[1])
      if (d >= this.minD && d < fd) {
        fd = d
        f = s
      }
    }
    if (!f) return want
    if (t > this.until) this.flip(t)
    const lx = (me.pos[0] - f.pos[0]) / fd, ly = (me.pos[1] - f.pos[1]) / fd
    const along = want[0] * lx + want[1] * ly
    const across = Math.max(Math.abs(want[0] * -ly + want[1] * lx), this.lat)
    const dir = (side: number): V2 => {
      const x = along * lx - side * across * ly, y = along * ly + side * across * lx
      const L = Math.hypot(x, y)
      return [x / L, y / L]
    }
    // a wall within 0.3 s on this side: the other side now, or the wanted move when both are shut
    if (!this.open(w, me, dir(this.side))) {
      if (!this.open(w, me, dir(-this.side))) return want
      this.flip(t)
    }
    return dir(this.side)
  }

  flip(t: number) {
    this.side = -this.side
    this.until = t + this.lo + this.rng() * this.span
  }

  open(w: World, me: Body, dir: V2): boolean {
    const p = walk(w, me, dir, 6)
    return Math.hypot(p[6][0] - p[5][0], p[6][1] - p[5][1]) > 0
  }
}
