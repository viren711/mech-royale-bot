// Two modes in one brain. The board is 48 matches against house bots, where rim5 (far5 kept to the rim of the circle)
// scores best; the finals are a free-for-all among team bots, where farm's fight and peace trade better. Observations
// carry no names, so the mode comes from how fast the field dies: team-bot showdowns in data/live lose 3 mechs by 20 s
// or 5 by 30 s in 14 of 19 matches, house rooms in 9 of 157.
import { log, type Observation } from "../../src/mechfight.ts"
import { Brain as Rim5 } from "../rim5/brain.ts"
import { Brain as Farm } from "../farm/brain.ts"

type Foe = ReturnType<Rim5["foes"]>[number]

/** a free-for-all once at least `dead` mechs we did not kill are gone by `t` seconds */
export const FFA_AT = [
  { t: 20, dead: 3 },
  { t: 30, dead: 5 },
]

// no early signal by then: still FFA, since the finals count and a late switch in practice costs little
export const FFA_LATE = 150

export function ffaSeen(t: number, dead: number, late = FFA_LATE): boolean {
  return t >= late || FFA_AT.some((c) => t <= c.t && dead >= c.dead)
}

/** counts the mechs gone that we did not kill; `seen` turns true for good once ffaSeen fires */
export class FfaWatch {
  seen = false
  alive0 = 0
  kills = 0
  t = 0
  constructor(public late = FFA_LATE) {}

  update(obs: Observation): boolean {
    if (!this.alive0) this.alive0 = obs.alive
    for (const ev of obs.events) if (ev.type === "kill") this.kills++
    const dead = this.alive0 - obs.alive - this.kills
    if (!this.seen && ffaSeen(obs.t, dead, this.late)) {
      this.seen = true
      log(`free-for-all at ${obs.t.toFixed(1)} s, ${obs.alive} alive, ${this.kills} kills`)
      if (process.env.DUO_DBG) console.log(`DBG duo ffa t=${obs.t.toFixed(1)} dead=${dead}`)
    }
    if (process.env.DUO_DBG && obs.t >= 90 && this.t < 90) console.log(`DBG duo dead90=${dead}`)
    this.t = obs.t
    return this.seen
  }
}

/** rim5 until the field reads as a free-for-all, then farm's fight, peace and band; the roof fixes and rim hides stay */
export class Brain extends Rim5 {
  name = "duo"
  ffa = false
  watch = new FfaWatch()

  act(obs: Observation) {
    this.ffa = this.watch.update(obs)
    return super.act(obs)
  }

  fight(obs: Observation, e: Foe, foes: Foe[], endgame: boolean) {
    if (this.ffa) return Farm.prototype.fight.call(this, obs, e, foes, endgame)
    return super.fight(obs, e, foes, endgame)
  }

  peace(obs: Observation, endgame: boolean) {
    if (this.ffa) return this.reachable(() => Farm.prototype.peace.call(this, obs, endgame))
    return super.peace(obs, endgame)
  }

  band(e: Foe): [number, number] {
    if (this.ffa) return Farm.prototype.band.call(this, e)
    return super.band(e)
  }
}
