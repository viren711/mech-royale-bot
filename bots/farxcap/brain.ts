// farxcap: farx that walks to no cube once it holds stat_cap (10) of them. Past the cap a cube adds no HP or damage, only
// 5% size with no cap (protocol.md §10), so it makes us easier to hit. In the squad sim farx held more than 10 cubes in
// 18% of 400 matches. Cubes we walk over still get picked up.
import type { Observation } from "../../src/mechfight.ts"
import { Brain as FarX } from "../farx/brain.ts"

type Base = new (...args: any[]) => FarX

export function capCubes<B extends Base>(B: B) {
  return class extends B {
    act(obs: Observation) {
      if (obs.self.cubes < (this.cfg.cubes.stat_cap ?? 10)) return super.act(obs)
      return super.act({ ...obs, cubes: [] })
    }
  }
}

export class Brain extends capCubes(FarX) {}
