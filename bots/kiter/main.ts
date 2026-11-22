import { run, log } from "../../src/mechfight.ts"
import { Brain } from "./brain.ts"

run((hello) => {
  const t0 = performance.now()
  const b = new Brain(hello)
  // warm the JIT on path search before ready, so the first decisions stay inside 50 ms
  const w = b.w, cx = w.minX + w.nx / 2, cy = w.minY + w.ny / 2
  for (let k = 0; k < 6; k++) b.nav.find(cx + Math.cos(k) * 200, cy + Math.sin(k) * 200, cx - Math.cos(k) * 100, cy - Math.sin(k) * 100)
  log(`init ${(performance.now() - t0).toFixed(0)} ms, exposure ${b.exp ? "yes" : "no"}`)
  return { name: "kiter", act: (obs) => {
    const t1 = performance.now()
    // heavy planning stops 30 ms in, leaving 20 ms of the 50 ms budget (protocol.md §2) for the rest of the decision and the reply
    b.until = t1 + 30
    const a = b.act(obs)
    const dt = performance.now() - t1
    if (dt > 25) log(`slow tick ${obs.tick} ${dt.toFixed(0)} ms`)
    return a
  } }
})
