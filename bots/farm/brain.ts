// Farmer: the kiter's fighting, but it trades with a second attacker instead of backing off, detours mid-fight for
// cubes and wanted weapons in reach, farms drones and crates from farther, and picks upgrades by what they add to a
// fight against several attackers.
import type { Hello, Observation, WeaponObs } from "../../src/mechfight.ts"
import { Brain as Kiter, KITER, type KiterParams } from "../kiter/brain.ts"
import type { World } from "../../src/world.ts"
import type { Nav } from "../../src/nav.ts"
import type { Exposure } from "../../src/exposure.ts"
import { UPGRADE_PRESETS } from "../../src/knobs.ts"

type V2 = [number, number]
const d2 = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])

const WEAPONS = ["gun", "laser", "lightning", "mortar"]

export class Brain extends Kiter {
  name = "farm"
  // peace farms drones and crates only with no mech seen this close in the last 6 s
  calmR = this.kn.CALM_R
  constructor(hello: Hello, w?: World, nav?: Nav, exp?: Exposure | null, k: KiterParams = KITER) {
    super(hello, w, nav, exp, k)
  }

  fight(obs: Observation, e: any, foes: any[], endgame: boolean) {
    const r = this.engage(obs, e, foes, endgame)
    // worth a detour mid-fight: a cube (+4% HP, healed, and damage), else a weapon we want
    const pos = this.me.pos
    const retreat = this.mode === "retreat"
    const near = (p: number[], R: number) => d2(p, pos) < R && Math.abs(p[2] - pos[2]) < 4
    const byDist = (a: { pos: number[] }, b: { pos: number[] }) => d2(a.pos, pos) - d2(b.pos, pos)
    const kn = this.kn
    const cube = obs.cubes.filter((c) => near(c.pos, retreat ? kn.FIGHT_CUBE_R_RETREAT : kn.FIGHT_CUBE_R)).sort(byDist)[0]
    const want = this.wanted()
    const loot = [...this.loot.values()].filter((q) => want.includes(q.kind) && near(q.pos, retreat ? kn.FIGHT_LOOT_R_RETREAT : kn.FIGHT_LOOT_R)).sort(byDist)[0]
    const goal = cube ?? loot
    if (goal) r.move = this.steer([goal.pos[0], goal.pos[1]], obs)
    return r
  }

  /** the kiter's fight, retreating from extra attackers only below half HP */
  engage(obs: Observation, e: any, foes: any[], endgame: boolean) {
    const me = this.me
    const t = this.t
    const pos = me.pos
    const kn = this.kn
    const o = this.odds(e)
    const threats = foes.filter((f) => f !== e && this.aware(f) && d2(f.pos, pos) < kn.THREAT_R)
    for (const [id, at] of this.hitMeAt) {
      if (t - at > kn.HIT_MEMORY_S || id === e.id || foes.some((f) => f.id === id)) continue
      const b = this.hitMeFrom.get(id) ?? 0
      threats.push({ id, pos: [pos[0] + Math.cos(b) * 70, pos[1] + Math.sin(b) * 70, pos[2]], vel: [0, 0, 0], aim: [b + Math.PI, 0], hp: 1400, maxHp: 1400, weapons: ["gun"], charging: false, cubes: 0, seen: at, visible: false })
    }
    const hpFrac = me.hp / me.max_hp
    // the house bots converge on us whatever we do, so backing off from a second attacker only gives up the
    // damage we would deal; stand and trade above half HP
    let retreat = false
    if (!endgame && hpFrac < kn.RETREAT_HP && threats.length > 0) retreat = true
    if (!endgame && o.theirs < o.mine * kn.RETREAT_ODDS && hpFrac < kn.RETREAT_ODDS_HP) retreat = true
    if (!endgame && hpFrac < kn.RETREAT_LOW_HP && e.hp > me.hp) retreat = true
    this.mode = retreat ? "retreat" : "fight"
    let shoot = e
    if (!this.hasLos(this.bodyOf(e))) {
      const alt = threats.filter((f) => f.visible && this.hasLos(this.bodyOf(f))).sort((a, b) => d2(a.pos, pos) - d2(b.pos, pos))[0]
      if (alt) shoot = alt
    }
    const w = this.weaponsPlan(this.bodyOf(shoot), d2(shoot.pos, pos), shoot, true)
    const band = this.band(e)
    const cover = retreat ? this.coverFrom([e.pos[0], e.pos[1], e.pos[2] + 8 * this.scaleOf(e.cubes ?? 0)], kn.COVER_R) : null
    const pick = this.planMove(obs, e, [e, ...threats], band, retreat, cover, w.charging)
    return { move: pick.move, boost: pick.boost, aim: w.aim, fire: w.fire }
  }

  /** the kiter's peace with cubes picked up from 140 m instead of 80 */
  peace(obs: Observation, endgame: boolean): { move: V2; aim: V2 | null; fire: [boolean, boolean] } {
    const r = this.peaceGoal(obs, endgame)
    return { move: this.steer(r.goal, obs), aim: r.aim, fire: r.fire }
  }

  /** where peace goes and how it aims and fires, before the path search to the goal */
  peaceGoal(obs: Observation, endgame: boolean): { goal: V2; aim: V2 | null; fire: [boolean, boolean] } {
    const me = this.me
    const t = this.t
    const pos = me.pos
    let fire: [boolean, boolean] = [false, false]
    let aim: V2 | null = null
    let goal: V2 = this.chooseGoal(obs, endgame)
    this.mode = "hide"
    const zone = obs.zone
    const kn = this.kn
    const safe = (p: number[]) => {
      const R = t > zone.shrink_start - kn.ZONE_LEAD_S ? zone.next_radius : zone.radius
      const C = t > zone.shrink_start - kn.ZONE_LEAD_S ? zone.next_center : zone.center
      return d2(p, C) < R - kn.ZONE_SAFE_M
    }
    const mechNear = [...this.enemies.values()].some((e) => t - e.seen < kn.CALM_S && d2(e.pos, pos) < this.calmR)
    if (t - this.lastHit < 2 && this.lastHitBy !== null) aim = [this.lastHitBearing, 0]
    if (!endgame) {
      const want = this.wanted()
      let lootGoal: number[] | null = null
      let ls = Infinity
      const lootR = t < kn.LOOT_EARLY_S ? kn.LOOT_R_EARLY : kn.LOOT_R_LATE
      for (const [, p] of this.loot) {
        if (!want.includes(p.kind) || !safe(p.pos)) continue
        const d = d2(p.pos, pos)
        if (d > lootR || Math.abs(p.pos[2] - pos[2]) > 8) continue
        const s = d - (p.kind === want[0] ? kn.LOOT_FIRST_BONUS : 0)
        if (s < ls) {
          ls = s
          lootGoal = p.pos
        }
      }
      if (lootGoal) {
        goal = [lootGoal[0], lootGoal[1]]
        this.mode = "loot"
      } else if (!mechNear) {
        const cube = obs.cubes.filter((c) => d2(c.pos, pos) < kn.CUBE_R && Math.abs(c.pos[2] - pos[2]) < 4 && safe(c.pos)).sort((a, b) => d2(a.pos, pos) - d2(b.pos, pos))[0]
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
              const want = hasZ ? kn.DRONE_STANDOFF_ARC : kn.DRONE_STANDOFF
              if (d > want + 15 || !w.los) goal = [prey.pos[0], prey.pos[1]]
              else {
                const away = Math.atan2(pos[1] - prey.pos[1], pos[0] - prey.pos[0]) + this.side * 0.6
                goal = [prey.pos[0] + Math.cos(away) * want, prey.pos[1] + Math.sin(away) * want]
                if (t > this.sideUntil) {
                  this.side = -this.side
                  this.sideUntil = t + 1 + this.rng()
                }
              }
            } else if (!w.los || d > kn.CRATE_WALK_R) goal = [prey.pos[0], prey.pos[1]]
            else goal = [pos[0], pos[1]]
          }
        }
      }
    }
    return { goal, aim, fire }
  }

  /** a drone within 200 m or a crate within 150 m worth shooting now: healthy, under the cube cap */
  prey(obs: Observation): { id: number; pos: number[]; vel: number[] } | null {
    const me = this.me
    const pos = me.pos
    const kn = this.kn
    if (me.hp < me.max_hp * kn.PREY_HP_FRAC || me.cubes >= kn.CUBE_CAP) return null
    let best: { id: number; pos: number[]; vel: number[] } | null = null
    let bs = Infinity
    for (const m of obs.mechs) {
      if (m.kind !== "npc") continue
      const d = d2(m.pos, pos)
      if (d > kn.DRONE_R) continue
      if (d < bs) {
        bs = d
        best = m
      }
    }
    for (const c of obs.crates ?? []) {
      const d = d2(c.pos, pos)
      if (d > kn.CRATE_R || d + kn.CRATE_BIAS > bs) continue
      bs = d + kn.CRATE_BIAS
      best = { id: c.id, pos: c.pos, vel: [0, 0, 0] }
    }
    return best
  }

  pickKit(ids: string[]): number {
    const kinds = (this.me.weapons as (WeaponObs | null)[]).filter(Boolean).map((w) => w!.kind)
    const rank = UPGRADE_PRESETS[this.kn.UPGRADES]
    let bi = 0
    let bv = -1
    ids.forEach((id, i) => {
      const req = id.split("_")[0]
      // an upgrade for a weapon we no longer hold only pays if we pick that kind up again
      const v = WEAPONS.includes(req) && !kinds.includes(req) ? 1 : rank[id] ?? 1
      if (v > bv) {
        bv = v
        bi = i
      }
    })
    return bi
  }
}
