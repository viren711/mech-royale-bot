// One entry for two games: farx, the best of our bots on the practice board (5.71), until the field reads as the
// finals (src/mode.ts), then duo, the best of ours in the rivals arena (sim/ARENA.md).
import { log, type Observation } from "../../src/mechfight.ts"
import { Brain as Duo } from "../duo/brain.ts"
import { Brain as FarX } from "../farx/brain.ts"
import { mode } from "../../src/mode.ts"

type Foe = ReturnType<Duo["foes"]>[number]
type V2 = [number, number]

// The practice slot: a brain on far5, as duo is. Until the finals show, each method below runs PRACTICE's, which covers
// every method duo, rim5 and farx override; a practice brain that overrides another, or sets state in its
// constructor, needs that routed here too.
const PRACTICE = FarX.prototype

/** duo, which sees every observation from tick 0; until the finals show, every call duo overrides goes to PRACTICE */
export class Brain extends Duo {
  name = "split"
  finals = false
  // every observation until the mode is decided
  history: Observation[] = []
  decided = false

  act(obs: Observation) {
    if (!this.decided) {
      this.history.push(obs)
      const m = mode(this.history)
      this.decided = m.mode !== "unknown"
      this.finals = m.mode === "finals"
      if (this.decided) {
        log(`${m.mode} at ${obs.t.toFixed(1)} s, ${obs.alive} alive`)
        if (process.env.SPLIT_DBG) console.log(`DBG split ${m.mode} t=${obs.t.toFixed(1)}`)
        this.history = []
      }
    }
    return super.act(obs)
  }

  track(obs: Observation) {
    if (this.finals) return super.track(obs)
    return PRACTICE.track.call(this, obs)
  }

  shouldSee(obs: Observation, p: number[]): boolean {
    return PRACTICE.shouldSee.call(this, obs, p)
  }

  laserGoal(obs: Observation, maxD: number): V2 | null {
    if (this.finals) return super.laserGoal(obs, maxD)
    return PRACTICE.laserGoal.call(this, obs, maxD)
  }

  searchPoint(C: number[], R: number): V2 {
    if (this.finals) return super.searchPoint(C, R)
    return PRACTICE.searchPoint.call(this, C, R)
  }

  pickHide(obs: Observation): V2 {
    if (this.finals) return super.pickHide(obs)
    return PRACTICE.pickHide.call(this, obs)
  }

  fight(obs: Observation, e: Foe, foes: Foe[], endgame: boolean) {
    if (this.finals) return super.fight(obs, e, foes, endgame)
    return PRACTICE.fight.call(this, obs, e, foes, endgame)
  }

  peace(obs: Observation, endgame: boolean) {
    if (this.finals) return super.peace(obs, endgame)
    return PRACTICE.peace.call(this, obs, endgame)
  }

  band(e: Foe): [number, number] {
    if (this.finals) return super.band(e)
    return PRACTICE.band.call(this, e)
  }
}
