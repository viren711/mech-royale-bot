// Static exposure grid (tools/exposure.ts): how much open ground within 200 m sees a mech standing at a point.
import { existsSync, readFileSync } from "node:fs"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"
import { World } from "./world.ts"
import { Nav, NS } from "./nav.ts"

export class Exposure {
  nx: number
  ny: number
  step: number
  v: Float32Array // normalized 0..1 (1 = most exposed), -1 = not standable
  w: World
  constructor(w: World, buf: Buffer) {
    this.w = w
    const hdr = new Int32Array(buf.buffer, buf.byteOffset, 3)
    this.nx = hdr[0]; this.ny = hdr[1]; this.step = hdr[2]
    const raw = new Uint16Array(buf.buffer.slice(buf.byteOffset + 12, buf.byteOffset + 12 + this.nx * this.ny * 2))
    let mx = 1
    for (const x of raw) if (x !== 0xffff && x > mx) mx = x
    this.v = new Float32Array(raw.length)
    for (let k = 0; k < raw.length; k++) this.v[k] = raw[k] === 0xffff ? -1 : Math.sqrt(raw[k] / mx)
  }
  static load(w: World): Exposure | null {
    const here = dirname(fileURLToPath(import.meta.url))
    for (const p of [join(here, "../data/exposure.bin"), join(here, "data/exposure.bin"), "/bot/data/exposure.bin", "data/exposure.bin"]) {
      if (existsSync(p)) return new Exposure(w, readFileSync(p))
    }
    return null
  }
  at(x: number, y: number): number {
    const i = Math.round((x - this.w.minX) / this.step), j = Math.round((y - this.w.minY) / this.step)
    if (i < 0 || j < 0 || i >= this.nx || j >= this.ny) return 1
    const v = this.v[j * this.nx + i]
    return v < 0 ? 1 : v
  }
  applyNavCost(nav: Nav) {
    for (let j = 0; j < nav.ny; j++)
      for (let i = 0; i < nav.nx; i++) nav.cost[j * nav.nx + i] = 1 + 1.5 * this.at(this.w.minX + i * NS, this.w.minY + j * NS)
  }
}
