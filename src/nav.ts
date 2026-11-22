// A* on a 2 m grid over the ground layer. Node passable when the 1 m clearance there is >= CLEAR.
import { World } from "./world.ts"

export const NS = 2
const CLEAR = 2.8

export class Nav {
  w: World
  nx: number
  ny: number
  ok: Uint8Array
  cost: Float32Array // extra per-node cost multiplier (exposure etc.), >= 1
  g: Float32Array
  from: Int32Array
  stamp: Uint32Array
  closed: Uint32Array
  cur = 1
  heap: Int32Array
  hf: Float32Array
  hn = 0
  /** the last find() stopped at its `until` deadline */
  cut = false
  constructor(w: World) {
    this.w = w
    this.nx = Math.floor((w.nx - 1) / NS) + 1
    this.ny = Math.floor((w.ny - 1) / NS) + 1
    const n = this.nx * this.ny
    this.ok = new Uint8Array(n)
    this.cost = new Float32Array(n).fill(1)
    for (let j = 0; j < this.ny; j++)
      for (let i = 0; i < this.nx; i++) {
        const k = j * NS * w.nx + i * NS
        this.ok[j * this.nx + i] = w.clear[k] >= CLEAR ? 1 : 0
      }
    this.g = new Float32Array(n)
    this.from = new Int32Array(n)
    this.stamp = new Uint32Array(n)
    this.closed = new Uint32Array(n)
    this.heap = new Int32Array(n * 2)
    this.hf = new Float32Array(n * 2)
  }
  node(x: number, y: number): number {
    let i = Math.round((x - this.w.minX) / NS), j = Math.round((y - this.w.minY) / NS)
    i = Math.max(0, Math.min(this.nx - 1, i)); j = Math.max(0, Math.min(this.ny - 1, j))
    return j * this.nx + i
  }
  nodeXY(n: number): [number, number] {
    return [this.w.minX + (n % this.nx) * NS, this.w.minY + Math.floor(n / this.nx) * NS]
  }
  /** nearest passable node to (x,y) within r nodes, or -1 */
  nearestOk(x: number, y: number, r = 6): number {
    const n0 = this.node(x, y)
    if (this.ok[n0]) return n0
    const i0 = n0 % this.nx, j0 = (n0 / this.nx) | 0
    let best = -1, bd = 1e9
    for (let dj = -r; dj <= r; dj++)
      for (let di = -r; di <= r; di++) {
        const i = i0 + di, j = j0 + dj
        if (i < 0 || j < 0 || i >= this.nx || j >= this.ny) continue
        const k = j * this.nx + i
        if (!this.ok[k]) continue
        const d = di * di + dj * dj
        if (d < bd) { bd = d; best = k }
      }
    return best
  }
  push(n: number, f: number) {
    let i = this.hn++
    const H = this.heap, F = this.hf
    while (i > 0) {
      const p = (i - 1) >> 1
      if (F[p] <= f) break
      H[i] = H[p]; F[i] = F[p]; i = p
    }
    H[i] = n; F[i] = f
  }
  pop(): number {
    const H = this.heap, F = this.hf
    const top = H[0]
    const n = H[--this.hn], f = F[this.hn]
    let i = 0
    for (;;) {
      let c = 2 * i + 1
      if (c >= this.hn) break
      if (c + 1 < this.hn && F[c + 1] < F[c]) c++
      if (F[c] >= f) break
      H[i] = H[c]; F[i] = F[c]; i = c
    }
    H[i] = n; F[i] = f
    return top
  }
  /** path of world points from start to goal; null if none within budget. Past `until` (performance.now()) it stops
   *  and returns the path to the node nearest the goal so far, as when the node budget runs out. */
  find(sx: number, sy: number, gx: number, gy: number, budget = 60000, until = Infinity): [number, number][] | null {
    this.cut = false
    const s = this.nearestOk(sx, sy), t = this.nearestOk(gx, gy, 10)
    if (s < 0 || t < 0) return null
    const stamp = ++this.cur
    const nx = this.nx, ok = this.ok, cost = this.cost, g = this.g, from = this.from, st = this.stamp, cl = this.closed
    const ti = t % nx, tj = (t / nx) | 0
    const h = (n: number) => {
      const di = Math.abs((n % nx) - ti), dj = Math.abs(((n / nx) | 0) - tj)
      return (Math.max(di, dj) + 0.4142 * Math.min(di, dj)) * NS
    }
    this.hn = 0
    g[s] = 0; from[s] = -1; st[s] = stamp
    this.push(s, h(s))
    let it = 0, best = s, bestH = h(s)
    const D = [1, -1, nx, -nx, nx + 1, nx - 1, -nx + 1, -nx - 1]
    const L = [NS, NS, NS, NS, NS * 1.4142, NS * 1.4142, NS * 1.4142, NS * 1.4142]
    while (this.hn > 0) {
      const n = this.pop()
      if (cl[n] === stamp) continue
      cl[n] = stamp
      if (n === t) { best = n; break }
      const hh = h(n)
      if (hh < bestH) { bestH = hh; best = n }
      if (++it > budget) break
      if ((it & 1023) === 0 && performance.now() > until) {
        this.cut = true
        break
      }
      const ni = n % nx
      for (let d = 0; d < 8; d++) {
        const m = n + D[d]
        if (m < 0 || m >= ok.length || !ok[m]) continue
        const mi = m % nx
        if (Math.abs(mi - ni) > 1) continue
        if (d >= 4 && (!ok[n + D[d] - (D[d] > 0 ? nx : -nx)] || !ok[n + (D[d] > 0 ? nx : -nx)])) continue // no corner cutting
        const ng = g[n] + L[d] * 0.5 * (cost[n] + cost[m])
        if (st[m] === stamp && ng >= g[m]) continue
        st[m] = stamp; g[m] = ng; from[m] = n
        this.push(m, ng + h(m))
      }
    }
    if (best === s && s !== t) return null
    const path: [number, number][] = []
    for (let n = best; n !== -1; n = from[n]) path.push(this.nodeXY(n))
    path.reverse()
    return path
  }
  /** straight walk from a to b stays in clearance */
  straight(ax: number, ay: number, bx: number, by: number, need = 2.6): boolean {
    const d = Math.hypot(bx - ax, by - ay)
    const n = Math.ceil(d / 1)
    for (let s = 1; s <= n; s++) {
      const f = s / n
      if (this.w.clearAt(ax + (bx - ax) * f, ay + (by - ay) * f) < need) return false
    }
    return true
  }
}
