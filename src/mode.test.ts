// Practice house bots "never fight each other" (the board's rules), so deaths we did not cause say team bots.
import { test, expect } from "bun:test"
import { finalsSeen, mode } from "./mode.ts"

const o = (t: number, alive: number, kills = 0) =>
  ({ t, tick: Math.round(t * 20), alive, events: Array.from({ length: kills }, (_, i) => ({ type: "kill", target: i })) }) as any

test("two deaths we did not cause by 45 s read as the finals, one or a late pair as practice", () => {
  expect(finalsSeen(21, 2)).toBe(true)
  expect(finalsSeen(45, 2)).toBe(true)
  expect(finalsSeen(44, 1)).toBe(false)
  expect(finalsSeen(46, 2)).toBe(false)
  expect(finalsSeen(120, 6)).toBe(false)
})

test("the mode from the history: unknown while the window is open, then finals or practice for good", () => {
  expect(mode([o(0, 16), o(10, 15)]).mode).toBe("unknown")
  // 3 gone, all 3 ours
  expect(mode([o(0, 16), o(10, 13, 3), o(30, 13)]).mode).toBe("unknown")
  expect(mode([o(0, 16), o(10, 13, 3), o(30, 12), o(40, 11)]).mode).toBe("finals")
  // the window closed with one death we did not cause
  expect(mode([o(0, 16), o(30, 15), o(46, 15)]).mode).toBe("practice")
  // a late pair does not reopen it, a finals read does not close
  expect(mode([o(0, 16), o(30, 15), o(46, 15), o(50, 12)]).mode).toBe("practice")
  expect(mode([o(0, 16), o(20, 14), o(60, 14)]).mode).toBe("finals")
  const f = mode([o(0, 16), o(20, 14)])
  const p = mode([o(0, 16), o(46, 16)])
  expect(f.confidence).toBeGreaterThan(0.9)
  expect(p.confidence).toBeGreaterThan(0.9)
  expect(mode([o(0, 16)]).confidence).toBe(0)
})
