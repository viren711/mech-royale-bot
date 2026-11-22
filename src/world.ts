// Static world model: 1 m point grid aligned with terrain.i16 (protocol.md §11).
import { readFileSync } from "node:fs"
import { join } from "node:path"

export const NONE = -1e9

export class World {
  nx: number
  ny: number
  minX: number
  minY: number
  ground: Float32Array // terrain height at grid point
  bTop: Float32Array // max top of building/stadium covering the point, NONE if none
  bBase: Float32Array
  rTop: Float32Array // bridge slab
  rBase: Float32Array
  floor: Float32Array // walkable surface of the ground layer
  wall: Uint8Array // 1 = a wall for a mech on the ground layer
  clear: Float32Array // distance (m) to nearest wall point
  canopy: Float32Array // crown height band: bottom
  canopyTop: Float32Array
  bounds: { minX: number; maxX: number; minY: number; maxY: number }
  constructor(dir: string) {
    const w = JSON.parse(readFileSync(join(dir, "v2/world.json"), "utf8"))
    const t = w.terrain
    this.nx = t.nx
    this.ny = t.ny
    this.minX = t.minX
    this.minY = t.minY
    this.bounds = w.bounds
    const raw = readFileSync(join(dir, "v2/terrain.i16"))
    const i16 = new Int16Array(raw.buffer, raw.byteOffset, raw.byteLength >> 1)
    const n = this.nx * this.ny
    this.ground = new Float32Array(n)
    for (let k = 0; k < n; k++) this.ground[k] = i16[k] * 0.01
    this.bTop = new Float32Array(n).fill(NONE)
    this.bBase = new Float32Array(n).fill(-NONE)
    this.rTop = new Float32Array(n).fill(NONE)
    this.rBase = new Float32Array(n).fill(-NONE)
    for (const p of w.prisms) {
      const isBridge = p.kind === "bridge"
      const top = isBridge ? this.rTop : this.bTop
      const base = isBridge ? this.rBase : this.bBase
      this.raster(p.ring, p.holes, (k) => {
        if (p.top > top[k]) top[k] = p.top
        if (p.base < base[k]) base[k] = p.base
      })
    }
    this.canopy = new Float32Array(n).fill(NONE)
    this.canopyTop = new Float32Array(n).fill(NONE)
    const F: string[] = w.trees.fields
    const D: number[] = w.trees.data
    const nf = F.length
    const fi = (s: string) => F.indexOf(s)
    const [iz, ih, ir, icb, icx, icy] = [fi("z"), fi("height"), fi("crownR"), fi("crownBase"), fi("crownX"), fi("crownY")]
    for (let k = 0; k < D.length; k += nf) {
      const cx = D[k + icx], cy = D[k + icy], r = D[k + ir]
      const zb = D[k + iz] + D[k + icb], zt = D[k + iz] + D[k + ih]
      const i0 = Math.max(0, Math.floor(cx - r - this.minX)), i1 = Math.min(this.nx - 1, Math.ceil(cx + r - this.minX))
      const j0 = Math.max(0, Math.floor(cy - r - this.minY)), j1 = Math.min(this.ny - 1, Math.ceil(cy + r - this.minY))
      for (let j = j0; j <= j1; j++)
        for (let i = i0; i <= i1; i++) {
          const x = this.minX + i, y = this.minY + j
          if ((x - cx) ** 2 + (y - cy) ** 2 > r * r) continue
          const q = j * this.nx + i
          if (this.canopy[q] === NONE || zb < this.canopy[q]) this.canopy[q] = zb
          if (zt > this.canopyTop[q]) this.canopyTop[q] = zt
        }
    }
    // ground-layer floor and walls
    this.floor = new Float32Array(n)
    this.wall = new Uint8Array(n)
    for (let k = 0; k < n; k++) {
      let f = this.ground[k]
      if (this.rTop[k] !== NONE && this.rBase[k] - f < 9) f = Math.max(f, this.rTop[k])
      if (this.bTop[k] !== NONE) {
        if (this.bTop[k] - f <= 1.2) f = Math.max(f, this.bTop[k])
        else if (this.bBase[k] - f < 9) this.wall[k] = 1
      }
      this.floor[k] = f
    }
    // cliffs: a rise of more than ~1.3 m to a neighbour within 1 m is a wall on the low side? Mark the high side
    // only when the drop is big (walkers on the high side can step down; low side sees a wall). Mark both sides of steep steps.
    for (let j = 1; j < this.ny - 1; j++)
      for (let i = 1; i < this.nx - 1; i++) {
        const k = j * this.nx + i
        if (this.wall[k]) continue
        const f = this.floor[k]
        if (
          Math.abs(this.floor[k + 1] - f) > 1.3 ||
          Math.abs(this.floor[k - 1] - f) > 1.3 ||
          Math.abs(this.floor[k + this.nx] - f) > 1.3 ||
          Math.abs(this.floor[k - this.nx] - f) > 1.3
        )
          this.wall[k] = 2
      }
    // map edge
    const m = Math.ceil
    for (let j = 0; j < this.ny; j++)
      for (let i = 0; i < this.nx; i++) {
        const x = this.minX + i, y = this.minY + j
        if (x <= this.bounds.minX + 0.5 || x >= this.bounds.maxX - 0.5 || y <= this.bounds.minY + 0.5 || y >= this.bounds.maxY - 0.5)
          this.wall[j * this.nx + i] = 3
      }
    void m
    this.clear = edt(this.wall, this.nx, this.ny)
  }
  raster(ring: number[], holes: number[][], fn: (k: number) => void) {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity
    for (let a = 0; a < ring.length; a += 2) {
      x0 = Math.min(x0, ring[a]); x1 = Math.max(x1, ring[a])
      y0 = Math.min(y0, ring[a + 1]); y1 = Math.max(y1, ring[a + 1])
    }
    const i0 = Math.max(0, Math.ceil(x0 - this.minX)), i1 = Math.min(this.nx - 1, Math.floor(x1 - this.minX))
    const j0 = Math.max(0, Math.ceil(y0 - this.minY)), j1 = Math.min(this.ny - 1, Math.floor(y1 - this.minY))
    for (let j = j0; j <= j1; j++) {
      const y = this.minY + j
      for (let i = i0; i <= i1; i++) {
        const x = this.minX + i
        if (!pip(x, y, ring)) continue
        let inHole = false
        for (const h of holes) if (pip(x, y, h)) { inHole = true; break }
        if (!inHole) fn(j * this.nx + i)
      }
    }
  }
  idx(x: number, y: number): number {
    let i = Math.round(x - this.minX), j = Math.round(y - this.minY)
    if (i < 0) i = 0; else if (i >= this.nx) i = this.nx - 1
    if (j < 0) j = 0; else if (j >= this.ny) j = this.ny - 1
    return j * this.nx + i
  }
  groundAt(x: number, y: number): number {
    const fx = Math.min(Math.max(x - this.minX, 0), this.nx - 1.001), fy = Math.min(Math.max(y - this.minY, 0), this.ny - 1.001)
    const i = Math.floor(fx), j = Math.floor(fy), u = fx - i, v = fy - j
    const k = j * this.nx + i, g = this.ground
    return (g[k] * (1 - u) + g[k + 1] * u) * (1 - v) + (g[k + this.nx] * (1 - u) + g[k + this.nx + 1] * u) * v
  }
  floorAt(x: number, y: number): number { return this.floor[this.idx(x, y)] }
  clearAt(x: number, y: number): number { return this.clear[this.idx(x, y)] }
  /** solid at a 3D point (buildings, bridges, terrain) */
  solid(x: number, y: number, z: number): boolean {
    const k = this.idx(x, y)
    if (z < this.ground[k]) return true
    if (z <= this.bTop[k] && z >= this.bBase[k]) return true
    if (z <= this.rTop[k] && z >= this.rBase[k]) return true
    return false
  }
  /** line of sight between two 3D points against buildings, bridges and terrain. step in meters. */
  los(ax: number, ay: number, az: number, bx: number, by: number, bz: number, step = 1): boolean {
    const dx = bx - ax, dy = by - ay, dz = bz - az
    const len = Math.hypot(dx, dy)
    const n = Math.max(1, Math.ceil(len / step))
    const nx = this.nx, ny = this.ny, minX = this.minX, minY = this.minY
    const G = this.ground, BT = this.bTop, BB = this.bBase, RT = this.rTop, RB = this.rBase
    for (let s = 1; s < n; s++) {
      const f = s / n
      let i = Math.round(ax + dx * f - minX), j = Math.round(ay + dy * f - minY)
      if (i < 0 || j < 0 || i >= nx || j >= ny) return false
      const k = j * nx + i
      const z = az + dz * f
      if (z < G[k] - 0.3) return false
      if (z <= BT[k] && z >= BB[k]) return false
      if (z <= RT[k] && z >= RB[k]) return false
    }
    return true
  }
  /** canopy opacity along a sight line (0 = clear). Rough: fraction of samples inside a crown band. */
  canopyCover(ax: number, ay: number, az: number, bx: number, by: number, bz: number, step = 1): number {
    const dx = bx - ax, dy = by - ay, dz = bz - az
    const len = Math.hypot(dx, dy)
    const n = Math.max(1, Math.ceil(len / step))
    let c = 0
    for (let s = 1; s < n; s++) {
      const f = s / n
      const k = this.idx(ax + dx * f, ay + dy * f)
      const z = az + dz * f
      if (z >= this.canopy[k] && z <= this.canopyTop[k]) c += step
    }
    return c
  }
}

function pip(x: number, y: number, r: number[]): boolean {
  let ins = false
  const n = r.length >> 1
  for (let a = 0, b = n - 1; a < n; b = a++) {
    const xa = r[2 * a], ya = r[2 * a + 1], xb = r[2 * b], yb = r[2 * b + 1]
    if (ya > y !== yb > y && x < ((xb - xa) * (y - ya)) / (yb - ya) + xa) ins = !ins
  }
  return ins
}

/** exact Euclidean distance transform (Felzenszwalb) of nonzero cells */
export function edt(mask: Uint8Array, nx: number, ny: number): Float32Array {
  const INF = 1e12
  const f = new Float64Array(nx * ny)
  for (let k = 0; k < nx * ny; k++) f[k] = mask[k] ? 0 : INF
  const tmp = new Float64Array(Math.max(nx, ny))
  const d = new Float64Array(Math.max(nx, ny))
  const v = new Int32Array(Math.max(nx, ny))
  const z = new Float64Array(Math.max(nx, ny) + 1)
  const dt1 = (n: number) => {
    let kk = 0
    v[0] = 0; z[0] = -INF; z[1] = INF
    for (let q = 1; q < n; q++) {
      let s = (tmp[q] + q * q - (tmp[v[kk]] + v[kk] * v[kk])) / (2 * q - 2 * v[kk])
      while (s <= z[kk]) { kk--; s = (tmp[q] + q * q - (tmp[v[kk]] + v[kk] * v[kk])) / (2 * q - 2 * v[kk]) }
      kk++; v[kk] = q; z[kk] = s; z[kk + 1] = INF
    }
    kk = 0
    for (let q = 0; q < n; q++) { while (z[kk + 1] < q) kk++; d[q] = (q - v[kk]) ** 2 + tmp[v[kk]] }
  }
  for (let i = 0; i < nx; i++) {
    for (let j = 0; j < ny; j++) tmp[j] = f[j * nx + i]
    dt1(ny)
    for (let j = 0; j < ny; j++) f[j * nx + i] = d[j]
  }
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) tmp[i] = f[j * nx + i]
    dt1(nx)
    for (let i = 0; i < nx; i++) f[j * nx + i] = d[i]
  }
  const out = new Float32Array(nx * ny)
  for (let k = 0; k < nx * ny; k++) out[k] = Math.sqrt(f[k])
  return out
}
