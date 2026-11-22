import { run, log } from "../../src/mechfight.ts"
import { Brain } from "./brain.ts"
import { warm, slowLog } from "../../src/brain.ts"

run((hello) => {
  const t0 = performance.now()
  const b = new Brain(hello)
  // warm the JIT before ready (20 s budget, protocol.md §2), so the first decisions stay inside 50 ms
  warm(b, hello)
  log(`init ${(performance.now() - t0).toFixed(0)} ms, exposure ${b.exp ? "yes" : "no"}`)
  const slow = slowLog(log)
  return { name: "farx", act: (obs, arrived) => {
    // heavy planning stops 30 ms after the observation arrived, leaving 20 ms of the 50 ms budget (protocol.md §2) for the rest of the decision and the reply
    b.until = arrived + 30
    const a = b.act(obs)
    const dt = performance.now() - arrived
    if (dt > 25) slow(obs.tick, dt, performance.now())
    return a
  } }
})
