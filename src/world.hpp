#pragma once

#include "json.hpp"
#include "math3d.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <limits>
#include <queue>
#include <string>
#include <vector>

namespace mf {

struct PolyLoop {
    std::vector<Vec2> pts;
};

struct Prism {
    int id = -1;
    std::string kind;
    int block = -1;
    double base = 0.0;
    double top = 0.0;
    double min_x = 0.0, max_x = 0.0;
    double min_y = 0.0, max_y = 0.0;
    PolyLoop outer;
    std::vector<PolyLoop> holes;
    Vec2 centroid;
    double area = 0.0;
};

struct Tree {
    double x = 0.0, y = 0.0, z = 0.0;
    double height = 0.0;
    double crown_r = 0.0;
    double crown_base = 0.0;
    double trunk_r = 0.0;
    double crown_x = 0.0, crown_y = 0.0;
};

struct RoofSpot {
    Vec3 roof_pos;
    Vec3 approach_pos;
    int prism_id = -1;
    double climb_dz = 0.0;
    double max_edge_dist = 0.0;
};

class World {
public:
    bool loaded = false;
    double min_x = -512.38, max_x = 555.08;
    double min_y = -333.09, max_y = 388.64;

    double max_step = 1.5;
    double max_slope_deg = 50.0;
    double canopy_density = 0.35;
    double canopy_block_t = 0.25;

    // Terrain grid
    double terr_min_x = -513.0, terr_min_y = -334.0;
    double terr_step = 1.0;
    double terr_scale = 0.01;
    int terr_nx = 0, terr_ny = 0;
    std::vector<int16_t> terr_raw;

    std::vector<Prism> prisms;
    std::vector<Tree> trees;
    std::vector<RoofSpot> roof_spots;

    // 16m spatial hash grid for prisms and trees
    double grid_cell = 16.0;
    double grid_ox = -520.0, grid_oy = -340.0;
    int grid_nx = 0, grid_ny = 0;
    std::vector<std::vector<int>> prism_grid;
    std::vector<std::vector<int>> tree_grid;

    // 4m navigation grid
    double nav_step = 4.0;
    double nav_ox = -512.0, nav_oy = -332.0;
    int nav_nx = 0, nav_ny = 0;
    std::vector<uint8_t> nav_walkable;
    std::vector<float> nav_ground_z;
    std::vector<float> nav_wall_dist;
    std::vector<float> nav_ceiling_z;
    std::vector<float> nav_roof_z;
    std::vector<int> nav_roof_prism;
    std::vector<float> nav_roof_edge_dist;

    static std::string join_path(const std::string& a, const std::string& b) {
        if (a.empty()) return b;
        char back = a.back();
        if (back == '/' || back == '\\') return a + b;
        return a + "/" + b;
    }

    static bool read_file_str(const std::string& path, std::string& out) {
        std::ifstream f(path, std::ios::binary | std::ios::ate);
        if (!f) return false;
        std::streamsize sz = f.tellg();
        if (sz < 0) return false;
        f.seekg(0, std::ios::beg);
        out.resize(static_cast<size_t>(sz));
        return sz == 0 || static_cast<bool>(f.read(&out[0], sz));
    }

    static bool point_in_loop(const PolyLoop& loop, double x, double y) {
        const auto& pts = loop.pts;
        size_t n = pts.size();
        if (n < 3) return false;
        bool inside = false;
        for (size_t i = 0, j = n - 1; i < n; j = i++) {
            double xi = pts[i].x, yi = pts[i].y;
            double xj = pts[j].x, yj = pts[j].y;
            if (((yi > y) != (yj > y)) &&
                (x < (xj - xi) * (y - yi) / ((yj - yi) + 1e-18) + xi)) {
                inside = !inside;
            }
        }
        return inside;
    }

    static bool point_in_prism_2d(const Prism& p, double x, double y) {
        if (x < p.min_x || x > p.max_x || y < p.min_y || y > p.max_y) return false;
        if (!point_in_loop(p.outer, x, y)) return false;
        for (const auto& h : p.holes) {
            if (point_in_loop(h, x, y)) return false;
        }
        return true;
    }

    static double min_dist_to_prism_edges(const Prism& p, double x, double y) {
        double best = 1e9;
        Vec2 pt(x, y);
        auto check_loop = [&](const PolyLoop& loop) {
            size_t n = loop.pts.size();
            for (size_t i = 0, j = n - 1; i < n; j = i++) {
                double d = dist_point_seg_2d(pt, loop.pts[j], loop.pts[i]);
                if (d < best) best = d;
            }
        };
        check_loop(p.outer);
        for (const auto& h : p.holes) check_loop(h);
        return best;
    }

    bool load(const std::string& map_dir) {
        loaded = false;
        prisms.clear();
        trees.clear();
        roof_spots.clear();

        if (map_dir.empty()) {
            init_fallback();
            return false;
        }

        std::string wpath = join_path(map_dir, "v2/world.json");
        std::string wtext;
        if (!read_file_str(wpath, wtext)) {
            init_fallback();
            return false;
        }

        Json wj;
        if (!Json::try_parse(wtext, wj) || !wj.is_object()) {
            init_fallback();
            return false;
        }

        const auto& b = wj["bounds"];
        min_x = b["minX"].as_double(min_x);
        max_x = b["maxX"].as_double(max_x);
        min_y = b["minY"].as_double(min_y);
        max_y = b["maxY"].as_double(max_y);

        const auto& r = wj["rules"];
        max_step = r["maxStep"].as_double(max_step);
        max_slope_deg = r["maxSlopeDeg"].as_double(max_slope_deg);
        canopy_density = r["canopyDensity"].as_double(canopy_density);
        canopy_block_t = r["canopyBlockT"].as_double(canopy_block_t);

        const auto& tr = wj["terrain"];
        terr_min_x = tr["minX"].as_double(terr_min_x);
        terr_min_y = tr["minY"].as_double(terr_min_y);
        terr_step = tr["step"].as_double(terr_step);
        terr_scale = tr["scale"].as_double(terr_scale);
        terr_nx = tr["nx"].as_int(0);
        terr_ny = tr["ny"].as_int(0);
        std::string terr_file = tr["file"].as_str("terrain.i16");
        std::string tpath = join_path(map_dir, "v2/" + terr_file);
        std::string tbytes;
        if (terr_nx > 0 && terr_ny > 0 && read_file_str(tpath, tbytes) &&
            tbytes.size() == static_cast<size_t>(terr_nx) * static_cast<size_t>(terr_ny) * 2) {
            terr_raw.resize(static_cast<size_t>(terr_nx) * static_cast<size_t>(terr_ny));
            const uint8_t* ptr = reinterpret_cast<const uint8_t*>(tbytes.data());
            for (size_t i = 0; i < terr_raw.size(); ++i) {
                uint16_t u = static_cast<uint16_t>(ptr[2 * i]) |
                             (static_cast<uint16_t>(ptr[2 * i + 1]) << 8);
                terr_raw[i] = static_cast<int16_t>(u);
            }
        } else {
            terr_nx = 0;
            terr_ny = 0;
            terr_raw.clear();
        }

        // Prisms
        const auto& parr = wj["prisms"].arr_val;
        prisms.reserve(parr.size());
        for (size_t idx = 0; idx < parr.size(); ++idx) {
            const auto& pj = parr[idx];
            Prism p;
            p.id = static_cast<int>(idx);
            p.kind = pj["kind"].as_str();
            p.block = pj["block"].as_int(-1);
            p.base = pj["base"].as_double(0.0);
            p.top = pj["top"].as_double(0.0);
            const auto& ring = pj["ring"].arr_val;
            p.outer.pts.reserve(ring.size() / 2);
            p.min_x = 1e9; p.max_x = -1e9;
            p.min_y = 1e9; p.max_y = -1e9;
            double sx = 0.0, sy = 0.0;
            for (size_t k = 0; k + 1 < ring.size(); k += 2) {
                double vx = ring[k].as_double();
                double vy = ring[k + 1].as_double();
                p.outer.pts.emplace_back(vx, vy);
                p.min_x = std::min(p.min_x, vx);
                p.max_x = std::max(p.max_x, vx);
                p.min_y = std::min(p.min_y, vy);
                p.max_y = std::max(p.max_y, vy);
                sx += vx;
                sy += vy;
            }
            if (!p.outer.pts.empty()) {
                p.centroid = Vec2(sx / p.outer.pts.size(), sy / p.outer.pts.size());
                double a2 = 0.0;
                for (size_t i = 0, j = p.outer.pts.size() - 1; i < p.outer.pts.size(); j = i++) {
                    a2 += p.outer.pts[j].cross(p.outer.pts[i]);
                }
                p.area = 0.5 * std::abs(a2);
            }
            for (const auto& hj : pj["holes"].arr_val) {
                PolyLoop hole;
                const auto& ha = hj.arr_val;
                hole.pts.reserve(ha.size() / 2);
                for (size_t k = 0; k + 1 < ha.size(); k += 2) {
                    hole.pts.emplace_back(ha[k].as_double(), ha[k + 1].as_double());
                }
                if (hole.pts.size() >= 3) p.holes.push_back(std::move(hole));
            }
            if (p.outer.pts.size() >= 3) prisms.push_back(std::move(p));
        }
        // Re-sync prism IDs cleanly
        for (size_t i = 0; i < prisms.size(); ++i) prisms[i].id = static_cast<int>(i);

        // Trees
        const auto& tf = wj["trees"]["fields"].arr_val;
        const auto& td = wj["trees"]["data"].arr_val;
        if (!tf.empty()) {
            int ix = -1, iy = -1, iz = -1, ih = -1, icr = -1, icb = -1, itr = -1, icx = -1, icy = -1;
            for (size_t i = 0; i < tf.size(); ++i) {
                const std::string& fn = tf[i].as_str();
                if (fn == "x") ix = static_cast<int>(i);
                else if (fn == "y") iy = static_cast<int>(i);
                else if (fn == "z") iz = static_cast<int>(i);
                else if (fn == "height") ih = static_cast<int>(i);
                else if (fn == "crownR") icr = static_cast<int>(i);
                else if (fn == "crownBase") icb = static_cast<int>(i);
                else if (fn == "trunkR") itr = static_cast<int>(i);
                else if (fn == "crownX") icx = static_cast<int>(i);
                else if (fn == "crownY") icy = static_cast<int>(i);
            }
            size_t stride = tf.size();
            trees.reserve(td.size() / stride);
            for (size_t off = 0; off + stride <= td.size(); off += stride) {
                Tree t;
                if (ix >= 0) t.x = td[off + ix].as_double();
                if (iy >= 0) t.y = td[off + iy].as_double();
                if (iz >= 0) t.z = td[off + iz].as_double();
                if (ih >= 0) t.height = td[off + ih].as_double();
                if (icr >= 0) t.crown_r = td[off + icr].as_double();
                if (icb >= 0) t.crown_base = td[off + icb].as_double();
                if (itr >= 0) t.trunk_r = td[off + itr].as_double();
                t.crown_x = (icx >= 0) ? td[off + icx].as_double() : t.x;
                t.crown_y = (icy >= 0) ? td[off + icy].as_double() : t.y;
                trees.push_back(t);
            }
        }

        build_spatial_grids();
        build_nav_grid();
        loaded = true;
        return true;
    }

    void init_fallback() {
        loaded = false;
        build_spatial_grids();
        build_nav_grid();
    }

    double terrain_height(double x, double y) const {
        if (terr_nx <= 1 || terr_ny <= 1 || terr_raw.empty()) return 0.0;
        double fx = clamp_val((x - terr_min_x) / terr_step, 0.0, static_cast<double>(terr_nx - 1));
        double fy = clamp_val((y - terr_min_y) / terr_step, 0.0, static_cast<double>(terr_ny - 1));
        int i0 = static_cast<int>(std::floor(fx));
        int j0 = static_cast<int>(std::floor(fy));
        int i1 = std::min(i0 + 1, terr_nx - 1);
        int j1 = std::min(j0 + 1, terr_ny - 1);
        double tx = fx - i0;
        double ty = fy - j0;
        double h00 = terr_raw[static_cast<size_t>(j0) * terr_nx + i0];
        double h10 = terr_raw[static_cast<size_t>(j0) * terr_nx + i1];
        double h01 = terr_raw[static_cast<size_t>(j1) * terr_nx + i0];
        double h11 = terr_raw[static_cast<size_t>(j1) * terr_nx + i1];
        double h0 = h00 + (h10 - h00) * tx;
        double h1 = h01 + (h11 - h01) * tx;
        return (h0 + (h1 - h0) * ty) * terr_scale;
    }

    double terrain_slope_deg(double x, double y) const {
        double h = 0.6;
        double gx = (terrain_height(x + h, y) - terrain_height(x - h, y)) / (2.0 * h);
        double gy = (terrain_height(x, y + h) - terrain_height(x, y - h)) / (2.0 * h);
        return std::atan(std::hypot(gx, gy)) * (180.0 / kPi);
    }

    // Returns ground/roof support height under (x, y) reachable at feet_z (<= feet_z + step_up + margin).
    double support_height(double x, double y, double feet_z, double step_up = 1.2) const {
        double best = terrain_height(x, y);
        int gx = clamp_val_int(static_cast<int>(std::floor((x - grid_ox) / grid_cell)), 0, grid_nx - 1);
        int gy = clamp_val_int(static_cast<int>(std::floor((y - grid_oy) / grid_cell)), 0, grid_ny - 1);
        if (grid_nx > 0 && grid_ny > 0) {
            const auto& cell = prism_grid[static_cast<size_t>(gy) * grid_nx + gx];
            for (int pid : cell) {
                const Prism& p = prisms[pid];
                if (p.top <= feet_z + step_up + 0.05 && p.top > best) {
                    if (point_in_prism_2d(p, x, y)) {
                        best = p.top;
                    }
                }
            }
        }
        return best;
    }

    // Exact 3D raycast against prisms and terrain. Returns true if hit in (0, max_dist].
    bool raycast_solid(
        const Vec3& orig,
        const Vec3& dir,
        double max_dist,
        double* out_t = nullptr,
        int* out_prism = nullptr
    ) const {
        if (max_dist <= 0.0) return false;
        double best_t = max_dist;
        int best_prism = -1;
        bool hit = false;

        if (!prisms.empty() && grid_nx > 0 && grid_ny > 0) {
            thread_local std::vector<uint32_t> stamp;
            thread_local uint32_t gen = 1;
            if (stamp.size() < prisms.size()) stamp.assign(prisms.size(), 0);
            ++gen;
            if (gen == 0) {
                std::fill(stamp.begin(), stamp.end(), 0);
                gen = 1;
            }

            // 2D DDA traversal across 16m grid
            double x0 = orig.x, y0 = orig.y;
            double dx = dir.x * max_dist, dy = dir.y * max_dist;
            int cx = clamp_val_int(static_cast<int>(std::floor((x0 - grid_ox) / grid_cell)), 0, grid_nx - 1);
            int cy = clamp_val_int(static_cast<int>(std::floor((y0 - grid_oy) / grid_cell)), 0, grid_ny - 1);
            int cx_end = clamp_val_int(static_cast<int>(std::floor((x0 + dx - grid_ox) / grid_cell)), 0, grid_nx - 1);
            int cy_end = clamp_val_int(static_cast<int>(std::floor((y0 + dy - grid_oy) / grid_cell)), 0, grid_ny - 1);

            int step_x = (dir.x > 0.0) ? 1 : (dir.x < 0.0 ? -1 : 0);
            int step_y = (dir.y > 0.0) ? 1 : (dir.y < 0.0 ? -1 : 0);

            double t_max_x = 1e30, t_delta_x = 1e30;
            if (step_x != 0) {
                double next_x = grid_ox + (cx + (step_x > 0 ? 1 : 0)) * grid_cell;
                t_max_x = (next_x - x0) / dir.x;
                t_delta_x = grid_cell / std::abs(dir.x);
            }
            double t_max_y = 1e30, t_delta_y = 1e30;
            if (step_y != 0) {
                double next_y = grid_oy + (cy + (step_y > 0 ? 1 : 0)) * grid_cell;
                t_max_y = (next_y - y0) / dir.y;
                t_delta_y = grid_cell / std::abs(dir.y);
            }

            auto test_cell = [&](int ix, int iy) {
                const auto& cell = prism_grid[static_cast<size_t>(iy) * grid_nx + ix];
                for (int pid : cell) {
                    if (stamp[pid] == gen) continue;
                    stamp[pid] = gen;
                    const Prism& p = prisms[pid];

                    // Quick Z interval overlap test against current [0, best_t]
                    double z0 = orig.z;
                    double z1 = orig.z + dir.z * best_t;
                    double rz_min = std::min(z0, z1);
                    double rz_max = std::max(z0, z1);
                    if (rz_max < p.base || rz_min > p.top) continue;

                    // Quick 2D AABB ray slab test
                    if (!ray_aabb_2d(orig.x, orig.y, dir.x, dir.y, p.min_x, p.max_x, p.min_y, p.max_y, best_t)) {
                        continue;
                    }

                    // Test wall segments of outer loop and holes
                    auto test_loop_walls = [&](const PolyLoop& loop) {
                        size_t n = loop.pts.size();
                        for (size_t i = 0, j = n - 1; i < n; j = i++) {
                            const Vec2& a = loop.pts[j];
                            const Vec2& b = loop.pts[i];
                            double sx = b.x - a.x;
                            double sy = b.y - a.y;
                            double denom = dir.x * sy - dir.y * sx;
                            if (std::abs(denom) < 1e-11) continue;
                            double qx = a.x - orig.x;
                            double qy = a.y - orig.y;
                            double t = (qx * sy - qy * sx) / denom;
                            if (t <= 1e-5 || t >= best_t) continue;
                            double s = (qx * dir.y - qy * dir.x) / denom;
                            if (s < -1e-6 || s > 1.0 + 1e-6) continue;
                            double z = orig.z + t * dir.z;
                            if (z >= p.base - 1e-4 && z <= p.top + 1e-4) {
                                best_t = t;
                                best_prism = pid;
                                hit = true;
                            }
                        }
                    };
                    test_loop_walls(p.outer);
                    for (const auto& h : p.holes) test_loop_walls(h);

                    // Test horizontal caps (top and bottom)
                    if (std::abs(dir.z) > 1e-8) {
                        for (double z_cap : {p.top, p.base}) {
                            double t = (z_cap - orig.z) / dir.z;
                            if (t > 1e-5 && t < best_t) {
                                double hx = orig.x + t * dir.x;
                                double hy = orig.y + t * dir.y;
                                if (point_in_prism_2d(p, hx, hy)) {
                                    best_t = t;
                                    best_prism = pid;
                                    hit = true;
                                }
                            }
                        }
                    }
                }
            };

            int max_steps = grid_nx + grid_ny + 4;
            for (int step = 0; step < max_steps; ++step) {
                test_cell(cx, cy);
                if (cx == cx_end && cy == cy_end) break;
                double next_t = std::min(t_max_x, t_max_y);
                if (next_t > best_t) break;
                if (t_max_x < t_max_y) {
                    t_max_x += t_delta_x;
                    cx += step_x;
                } else {
                    t_max_y += t_delta_y;
                    cy += step_y;
                }
                if (cx < 0 || cx >= grid_nx || cy < 0 || cy >= grid_ny) break;
            }
        }

        // Terrain ray march over [0, best_t]
        if (terr_nx > 1 && terr_ny > 1 && best_t > 0.05) {
            double prev_t = 0.0;
            double prev_diff = orig.z - terrain_height(orig.x, orig.y);
            if (prev_diff < -0.05) {
                if (out_t) *out_t = 0.0;
                if (out_prism) *out_prism = -1;
                return true;
            }
            double t = 0.0;
            while (t < best_t) {
                double step_t = (prev_diff < 5.0 || dir.z < -0.25) ? 1.0 : 2.5;
                double tc = std::min(t + step_t, best_t);
                double px = orig.x + tc * dir.x;
                double py = orig.y + tc * dir.y;
                double pz = orig.z + tc * dir.z;
                double diff = pz - terrain_height(px, py);
                if (diff <= 0.0) {
                    double lo = prev_t, hi = tc;
                    for (int k = 0; k < 6; ++k) {
                        double mid = 0.5 * (lo + hi);
                        double mx = orig.x + mid * dir.x;
                        double my = orig.y + mid * dir.y;
                        double mz = orig.z + mid * dir.z;
                        if (mz <= terrain_height(mx, my)) hi = mid;
                        else lo = mid;
                    }
                    best_t = hi;
                    best_prism = -1;
                    hit = true;
                    break;
                }
                if (tc >= best_t) break;
                prev_t = tc;
                prev_diff = diff;
                t = tc;
            }
        }

        if (hit) {
            if (out_t) *out_t = best_t;
            if (out_prism) *out_prism = best_prism;
        }
        return hit;
    }

    bool has_solid_los(const Vec3& a, const Vec3& b) const {
        Vec3 d = b - a;
        double len = d.len();
        if (len < 1e-4) return true;
        return !raycast_solid(a, d / len, len - 0.05);
    }

    bool has_tree_los(const Vec3& a, const Vec3& b, bool check_canopy) const {
        if (trees.empty() || grid_nx <= 0 || grid_ny <= 0) return true;
        Vec3 d = b - a;
        double len = d.len();
        if (len < 1e-4) return true;
        Vec3 dir = d / len;

        thread_local std::vector<uint32_t> tstamp;
        thread_local uint32_t tgen = 1;
        if (tstamp.size() < trees.size()) tstamp.assign(trees.size(), 0);
        ++tgen;
        if (tgen == 0) {
            std::fill(tstamp.begin(), tstamp.end(), 0);
            tgen = 1;
        }

        double accum_crown_dist = 0.0;
        double max_crown_dist = (canopy_density > 1e-6 && canopy_block_t > 1e-6)
                                    ? (-std::log(canopy_block_t) / canopy_density)
                                    : 1e9;

        int cx = clamp_val_int(static_cast<int>(std::floor((a.x - grid_ox) / grid_cell)), 0, grid_nx - 1);
        int cy = clamp_val_int(static_cast<int>(std::floor((a.y - grid_oy) / grid_cell)), 0, grid_ny - 1);
        int cx_end = clamp_val_int(static_cast<int>(std::floor((b.x - grid_ox) / grid_cell)), 0, grid_nx - 1);
        int cy_end = clamp_val_int(static_cast<int>(std::floor((b.y - grid_oy) / grid_cell)), 0, grid_ny - 1);

        int step_x = (dir.x > 0.0) ? 1 : (dir.x < 0.0 ? -1 : 0);
        int step_y = (dir.y > 0.0) ? 1 : (dir.y < 0.0 ? -1 : 0);
        double t_max_x = 1e30, t_delta_x = 1e30;
        if (step_x != 0) {
            double next_x = grid_ox + (cx + (step_x > 0 ? 1 : 0)) * grid_cell;
            t_max_x = (next_x - a.x) / dir.x;
            t_delta_x = grid_cell / std::abs(dir.x);
        }
        double t_max_y = 1e30, t_delta_y = 1e30;
        if (step_y != 0) {
            double next_y = grid_oy + (cy + (step_y > 0 ? 1 : 0)) * grid_cell;
            t_max_y = (next_y - a.y) / dir.y;
            t_delta_y = grid_cell / std::abs(dir.y);
        }

        int max_steps = grid_nx + grid_ny + 4;
        for (int step = 0; step < max_steps; ++step) {
            const auto& cell = tree_grid[static_cast<size_t>(cy) * grid_nx + cx];
            for (int tid : cell) {
                if (tstamp[tid] == tgen) continue;
                tstamp[tid] = tgen;
                const Tree& tr = trees[tid];

                // Trunk always blocks sight (not shots)
                if (tr.trunk_r > 0.01 &&
                    ray_cylinder_hit(a, dir, len, tr.x, tr.y, tr.z, tr.z + tr.crown_base + 1.0, tr.trunk_r)) {
                    return false;
                }

                // Crown ellipsoid / cylinder soft occlusion
                if (check_canopy && tr.crown_r > 0.01) {
                    double chord = ray_crown_chord(a, dir, len, tr);
                    if (chord > 0.0) {
                        accum_crown_dist += chord;
                        if (accum_crown_dist > max_crown_dist) return false;
                    }
                }
            }
            if (cx == cx_end && cy == cy_end) break;
            if (t_max_x < t_max_y) {
                t_max_x += t_delta_x;
                cx += step_x;
            } else {
                t_max_y += t_delta_y;
                cy += step_y;
            }
            if (cx < 0 || cx >= grid_nx || cy < 0 || cy >= grid_ny) break;
        }
        return true;
    }

    // Checks whether `eye` sees `target_pos` (center or top) given vision parameters
    bool can_see_point(
        const Vec3& eye,
        const Vec3& target_center,
        const Vec3& target_top,
        double near_range,
        double fov_range,
        double aim_yaw,
        double fov_deg,
        bool check_canopy
    ) const {
        double d_3d = (target_center - eye).len();
        bool in_near = (d_3d <= near_range);
        bool in_cone = false;
        if (d_3d <= fov_range) {
            double bearing = std::atan2(target_center.y - eye.y, target_center.x - eye.x);
            if (std::abs(angle_diff(bearing, aim_yaw)) <= deg_to_rad(fov_deg * 0.5)) {
                in_cone = true;
            }
        }
        if (!in_near && !in_cone) return false;
        // Near range ignores canopy per protocol.md §8
        bool canopy = check_canopy && !in_near;
        auto pt_vis = [&](const Vec3& pt) {
            if (!has_solid_los(eye, pt)) return false;
            if (!has_tree_los(eye, pt, canopy)) return false;
            return true;
        };
        return pt_vis(target_center) || pt_vis(target_top);
    }

    bool is_wall_blocked(
        double x,
        double y,
        double feet_z,
        double radius,
        double height,
        double step_up = 1.2
    ) const {
        if (x < min_x + radius || x > max_x - radius || y < min_y + radius || y > max_y - radius) {
            return true;
        }
        int ix0 = clamp_val_int(static_cast<int>(std::floor((x - radius - grid_ox) / grid_cell)), 0, grid_nx - 1);
        int ix1 = clamp_val_int(static_cast<int>(std::floor((x + radius - grid_ox) / grid_cell)), 0, grid_nx - 1);
        int iy0 = clamp_val_int(static_cast<int>(std::floor((y - radius - grid_oy) / grid_cell)), 0, grid_ny - 1);
        int iy1 = clamp_val_int(static_cast<int>(std::floor((y + radius - grid_oy) / grid_cell)), 0, grid_ny - 1);
        if (grid_nx <= 0 || grid_ny <= 0) return false;

        double z_lo = feet_z + step_up;
        double z_hi = feet_z + height - 0.05;

        thread_local std::vector<uint32_t> wstamp;
        thread_local uint32_t wgen = 1;
        if (wstamp.size() < prisms.size()) wstamp.assign(prisms.size(), 0);
        ++wgen;
        if (wgen == 0) {
            std::fill(wstamp.begin(), wstamp.end(), 0);
            wgen = 1;
        }

        for (int iy = iy0; iy <= iy1; ++iy) {
            for (int ix = ix0; ix <= ix1; ++ix) {
                const auto& cell = prism_grid[static_cast<size_t>(iy) * grid_nx + ix];
                for (int pid : cell) {
                    if (wstamp[pid] == wgen) continue;
                    wstamp[pid] = wgen;
                    const Prism& p = prisms[pid];
                    if (p.top <= z_lo || p.base >= z_hi) continue;
                    if (x + radius < p.min_x || x - radius > p.max_x ||
                        y + radius < p.min_y || y - radius > p.max_y) {
                        continue;
                    }
                    if (point_in_prism_2d(p, x, y)) return true;
                    if (min_dist_to_prism_edges(p, x, y) < radius - 0.05) return true;
                }
            }
        }
        return false;
    }

    // Navigation grid queries
    bool nav_in_bounds(int ix, int iy) const {
        return ix >= 0 && ix < nav_nx && iy >= 0 && iy < nav_ny;
    }

    void world_to_nav(double x, double y, int& ix, int& iy) const {
        ix = clamp_val_int(static_cast<int>(std::llround((x - nav_ox) / nav_step)), 0, nav_nx - 1);
        iy = clamp_val_int(static_cast<int>(std::llround((y - nav_oy) / nav_step)), 0, nav_ny - 1);
    }

    Vec2 nav_to_world(int ix, int iy) const {
        return {nav_ox + ix * nav_step, nav_oy + iy * nav_step};
    }

    bool is_nav_cell_clear(int idx, double mech_radius, double mech_height) const {
        if (!nav_walkable[idx]) return false;
        if (mech_radius > 2.55 && nav_wall_dist[idx] < static_cast<float>(mech_radius + 0.45)) return false;
        if (mech_height > 9.1 && (nav_ceiling_z[idx] - nav_ground_z[idx]) < static_cast<float>(mech_height + 0.35)) {
            return false;
        }
        return true;
    }

    bool is_nav_line_walkable(
        const Vec2& a,
        const Vec2& b,
        double mech_radius = 2.5,
        double mech_height = 9.0
    ) const {
        double dist = (b - a).len();
        int steps = std::max(2, static_cast<int>(std::ceil(dist / 2.0)));
        for (int i = 0; i <= steps; ++i) {
            double t = static_cast<double>(i) / steps;
            Vec2 p = a + (b - a) * t;
            int ix, iy;
            world_to_nav(p.x, p.y, ix, iy);
            int idx = iy * nav_nx + ix;
            if (!is_nav_cell_clear(idx, mech_radius, mech_height)) return false;
        }
        return true;
    }

    int find_nearest_walkable_cell(
        double x,
        double y,
        double mech_radius = 2.5,
        double mech_height = 9.0
    ) const {
        if (nav_nx <= 0 || nav_ny <= 0) return -1;
        int sx, sy;
        world_to_nav(x, y, sx, sy);
        int sidx = sy * nav_nx + sx;
        if (is_nav_cell_clear(sidx, mech_radius, mech_height)) return sidx;
        int best_idx = -1;
        double best_d2 = 1e18;
        for (int r = 1; r <= 12; ++r) {
            for (int dy = -r; dy <= r; ++dy) {
                for (int dx = -r; dx <= r; ++dx) {
                    if (std::abs(dx) != r && std::abs(dy) != r) continue;
                    int nx = sx + dx, ny = sy + dy;
                    if (!nav_in_bounds(nx, ny)) continue;
                    int idx = ny * nav_nx + nx;
                    if (is_nav_cell_clear(idx, mech_radius, mech_height)) {
                        Vec2 w = nav_to_world(nx, ny);
                        double d2 = (w.x - x) * (w.x - x) + (w.y - y) * (w.y - y);
                        if (d2 < best_d2) {
                            best_d2 = d2;
                            best_idx = idx;
                        }
                    }
                }
            }
            if (best_idx >= 0) return best_idx;
        }
        // Fallback to any basic walkable cell if mech is very large
        if (mech_radius > 2.55 || mech_height > 9.1) {
            return find_nearest_walkable_cell(x, y, 2.5, 9.0);
        }
        return -1;
    }

    // Fast A* on 4m navgrid with string-pulling smoothing. Returns world waypoints (start excluded, goal included).
    std::vector<Vec2> find_path(
        const Vec2& start,
        const Vec2& goal,
        int max_expansions = 10000,
        double mech_radius = 2.5,
        double mech_height = 9.0
    ) const {
        if (nav_nx <= 0 || nav_ny <= 0) return {goal};
        if (is_nav_line_walkable(start, goal, mech_radius, mech_height)) return {goal};

        int sidx = find_nearest_walkable_cell(start.x, start.y, mech_radius, mech_height);
        int gidx = find_nearest_walkable_cell(goal.x, goal.y, mech_radius, mech_height);
        if (sidx < 0 || gidx < 0) return {goal};
        if (sidx == gidx) return {goal};

        const int total = nav_nx * nav_ny;
        thread_local std::vector<float> g_score;
        thread_local std::vector<int> parent;
        thread_local std::vector<uint32_t> seen;
        thread_local std::vector<uint32_t> closed;
        thread_local uint32_t gen = 1;

        if (static_cast<int>(g_score.size()) != total) {
            g_score.assign(total, 0.0f);
            parent.assign(total, -1);
            seen.assign(total, 0);
            closed.assign(total, 0);
        }
        ++gen;
        if (gen == 0) {
            std::fill(seen.begin(), seen.end(), 0);
            std::fill(closed.begin(), closed.end(), 0);
            gen = 1;
        }

        int gx = gidx % nav_nx, gy = gidx / nav_nx;
        auto heur = [&](int ix, int iy) -> float {
            int dx = std::abs(ix - gx);
            int dy = std::abs(iy - gy);
            int dmin = std::min(dx, dy);
            int dmax = std::max(dx, dy);
            return static_cast<float>(dmax - dmin + 1.41421356 * dmin);
        };

        struct Node {
            float f;
            int idx;
            bool operator>(const Node& o) const { return f > o.f; }
        };
        std::priority_queue<Node, std::vector<Node>, std::greater<Node>> pq;
        seen[sidx] = gen;
        g_score[sidx] = 0.0f;
        parent[sidx] = -1;
        pq.push({heur(sidx % nav_nx, sidx / nav_nx), sidx});

        static const int kDx[8] = {1, -1, 0, 0, 1, 1, -1, -1};
        static const int kDy[8] = {0, 0, 1, -1, 1, -1, 1, -1};
        static const float kCost[8] = {1.0f, 1.0f, 1.0f, 1.0f, 1.41421356f, 1.41421356f, 1.41421356f, 1.41421356f};

        int best_node = sidx;
        float best_h = heur(sidx % nav_nx, sidx / nav_nx);
        int exp = 0;
        bool reached = false;

        while (!pq.empty() && exp < max_expansions) {
            Node cur = pq.top();
            pq.pop();
            int u = cur.idx;
            if (closed[u] == gen) continue;
            closed[u] = gen;
            ++exp;

            if (u == gidx) {
                reached = true;
                best_node = u;
                break;
            }

            int ux = u % nav_nx, uy = u / nav_nx;
            float uh = heur(ux, uy);
            if (uh < best_h) {
                best_h = uh;
                best_node = u;
            }

            for (int d = 0; d < 8; ++d) {
                int vx = ux + kDx[d];
                int vy = uy + kDy[d];
                if (!nav_in_bounds(vx, vy)) continue;
                int v = vy * nav_nx + vx;
                if (closed[v] == gen) continue;
                if (!is_nav_cell_clear(v, mech_radius, mech_height) && v != gidx) continue;
                // Avoid corner clipping on diagonals
                if (d >= 4) {
                    if (!nav_walkable[uy * nav_nx + vx] || !nav_walkable[vy * nav_nx + ux]) continue;
                }
                // Slight penalty for scraping right next to walls
                float wall_pen = (nav_wall_dist[v] < static_cast<float>(mech_radius + 2.0)) ? 0.14f : 0.0f;
                float ng = g_score[u] + kCost[d] + wall_pen;
                if (seen[v] != gen || ng < g_score[v]) {
                    seen[v] = gen;
                    g_score[v] = ng;
                    parent[v] = u;
                    pq.push({ng + heur(vx, vy), v});
                }
            }
        }

        std::vector<Vec2> raw;
        int cur = best_node;
        while (cur >= 0) {
            raw.push_back(nav_to_world(cur % nav_nx, cur / nav_nx));
            cur = parent[cur];
        }
        std::reverse(raw.begin(), raw.end());
        if (reached) {
            Vec2 gw = nav_to_world(gx, gy);
            if (raw.empty() || (goal - gw).len() < 8.0) raw.push_back(goal);
        }
        if (raw.empty()) return {goal};

        // String-pulling smoothing
        std::vector<Vec2> smooth;
        Vec2 anchor = start;
        size_t i = 0;
        while (i < raw.size()) {
            size_t farthest = i;
            for (size_t j = raw.size(); j > i + 1; --j) {
                if (is_nav_line_walkable(anchor, raw[j - 1], mech_radius, mech_height)) {
                    farthest = j - 1;
                    break;
                }
            }
            smooth.push_back(raw[farthest]);
            anchor = raw[farthest];
            i = farthest + 1;
        }
        if (smooth.empty()) smooth.push_back(goal);
        return smooth;
    }

    // Finds a fast ground cover position near `pos` inside `zone` that blocks LOS from `threats`.
    bool find_cover_pos(
        const Vec3& pos,
        const std::vector<Vec3>& threats,
        const Vec2& zone_center,
        double zone_radius,
        double max_search_r,
        Vec2& out_cover
    ) const {
        if (threats.empty() || nav_nx <= 0) return false;
        int cx, cy;
        world_to_nav(pos.x, pos.y, cx, cy);
        int rad_cells = static_cast<int>(std::ceil(max_search_r / nav_step));

        struct Cand {
            double d_self;
            double wall_d;
            int idx;
            Vec2 w;
        };
        std::vector<Cand> cands;
        cands.reserve(128);

        for (int dy = -rad_cells; dy <= rad_cells; ++dy) {
            for (int dx = -rad_cells; dx <= rad_cells; ++dx) {
                int nx = cx + dx, ny = cy + dy;
                if (!nav_in_bounds(nx, ny)) continue;
                int idx = ny * nav_nx + nx;
                if (!nav_walkable[idx]) continue;
                if (nav_wall_dist[idx] > 10.0f) continue;

                Vec2 w = nav_to_world(nx, ny);
                double d_self = std::hypot(w.x - pos.x, w.y - pos.y);
                if (d_self > max_search_r) continue;
                double d_zone = std::hypot(w.x - zone_center.x, w.y - zone_center.y);
                if (d_zone > std::max(5.0, zone_radius - 6.0)) continue;
                cands.push_back({d_self, nav_wall_dist[idx], idx, w});
            }
        }
        if (cands.empty()) return false;

        std::sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) {
            return (a.d_self + a.wall_d * 0.5) < (b.d_self + b.wall_d * 0.5);
        });
        if (cands.size() > 64) cands.resize(64);

        double best_score = 1e18;
        bool found_zero = false;
        Vec2 best_pt;
        size_t threat_lim = std::min<size_t>(threats.size(), 4);

        for (const Cand& c : cands) {
            double gz = nav_ground_z[c.idx];
            Vec3 eye(c.w.x, c.w.y, gz + 6.5);
            int visible_threats = 0;
            for (size_t ti = 0; ti < threat_lim; ++ti) {
                const Vec3& th = threats[ti];
                if ((th.xy() - c.w).len() > 230.0) continue;
                Vec3 th_eye(th.x, th.y, th.z + 7.5);
                if (has_solid_los(th_eye, eye)) {
                    ++visible_threats;
                }
            }
            double score = visible_threats * 100.0 + c.d_self + c.wall_d * 0.4;
            if (score < best_score) {
                best_score = score;
                best_pt = c.w;
                if (visible_threats == 0) {
                    found_zero = true;
                    break; // sorted closest-first, so first 0-threat cover is optimal!
                }
            }
        }
        if (found_zero || best_score < 95.0) {
            out_cover = best_pt;
            return true;
        }
        return false;
    }

    // Finds a tactical cover cell (0 LOS from threats) paired with an adjacent corner/roof-edge
    // peek cell (direct muzzle LOS to primary, minimal LOS to other threats) for peek-shooting & 1v1 slicing.
    bool find_tactical_cover(
        const Vec3& self_pos,
        const Vec3& primary_aim_pt,
        int primary_id,
        const std::vector<Vec3>& threat_eyes,
        const std::vector<int>& threat_ids,
        const Vec2& zone_center,
        double zone_radius,
        double search_r,
        double mech_radius,
        double mech_height,
        bool on_roof,
        Vec2& out_cover,
        Vec2& out_peek,
        bool& out_has_peek
    ) const {
        out_has_peek = false;
        if (threat_eyes.empty() || nav_nx <= 0) return false;

        int cx, cy;
        world_to_nav(self_pos.x, self_pos.y, cx, cy);
        int rad_cells = static_cast<int>(std::ceil(search_r / nav_step));
        double safe_z_r = std::max(6.0, zone_radius - 6.0);

        struct Cand {
            double sort_key;
            double d_self;
            double z;
            int idx;
            Vec2 w;
        };
        std::vector<Cand> cands;
        cands.reserve(160);

        for (int dy = -rad_cells; dy <= rad_cells; ++dy) {
            for (int dx = -rad_cells; dx <= rad_cells; ++dx) {
                int nx = cx + dx, ny = cy + dy;
                if (!nav_in_bounds(nx, ny)) continue;
                int idx = ny * nav_nx + nx;

                double cz = 0.0;
                if (on_roof) {
                    if (nav_roof_prism[idx] < 0) continue;
                    if (std::abs(nav_roof_z[idx] - self_pos.z) > 2.5) continue;
                    cz = nav_roof_z[idx];
                } else {
                    if (!is_nav_cell_clear(idx, mech_radius, mech_height)) continue;
                    if (nav_wall_dist[idx] > 12.0f) continue;
                    cz = nav_ground_z[idx];
                }

                Vec2 w = nav_to_world(nx, ny);
                double d_self = std::hypot(w.x - self_pos.x, w.y - self_pos.y);
                if (d_self > search_r) continue;
                if (std::hypot(w.x - zone_center.x, w.y - zone_center.y) > safe_z_r) continue;

                double sk = on_roof
                                ? (d_self + std::abs(nav_roof_edge_dist[idx] - 6.0f) * 0.4)
                                : (d_self + nav_wall_dist[idx] * 0.35);
                cands.push_back({sk, d_self, cz, idx, w});
            }
        }
        if (cands.empty()) return false;

        std::sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) {
            return a.sort_key < b.sort_key;
        });
        if (cands.size() > 48) cands.resize(48);

        size_t tlim = std::min<size_t>(threat_eyes.size(), 6);
        double best_cov_sc = 1e18;
        int best_cov_ci = -1;
        double cover_z = self_pos.z;

        for (int ci = 0; ci < static_cast<int>(cands.size()); ++ci) {
            const Cand& c = cands[ci];
            Vec3 c_cen(c.w.x, c.w.y, c.z + 0.50 * mech_height);
            Vec3 c_hi(c.w.x, c.w.y, c.z + 0.80 * mech_height);
            int vis = 0;
            for (size_t ti = 0; ti < tlim; ++ti) {
                if ((threat_eyes[ti].xy() - c.w).len() > 250.0) continue;
                if (has_solid_los(threat_eyes[ti], c_cen) || has_solid_los(threat_eyes[ti], c_hi)) {
                    ++vis;
                }
            }
            double sc = vis * 120.0 + c.d_self + (on_roof ? 0.0 : c.d_self * 0.05);
            if (vis == 0 && !on_roof) {
                // Slight preference for tight corner cells so peek distance is short
                sc += nav_wall_dist[c.idx] * 0.3;
            }
            if (sc < best_cov_sc) {
                best_cov_sc = sc;
                best_cov_ci = ci;
            }
            if (vis == 0 && c.d_self <= 8.0) {
                // Fast early accept when we're already right behind 0-LOS cover!
                break;
            }
        }
        if (best_cov_ci < 0 || best_cov_sc >= std::max(120.0, tlim * 115.0)) return false;

        out_cover = cands[best_cov_ci].w;
        cover_z = cands[best_cov_ci].z;

        // Now find a peek cell near out_cover (within 14m of out_cover) that sees primary_aim_pt
        // while keeping other threats blocked (1v1 isolation)!
        int cx_cov, cy_cov;
        world_to_nav(out_cover.x, out_cover.y, cx_cov, cy_cov);
        double best_pk_sc = 1e18;
        Vec2 best_pk = out_cover;
        bool found_pk = false;

        for (int dy = -3; dy <= 3; ++dy) {
            for (int dx = -3; dx <= 3; ++dx) {
                int nx = cx_cov + dx, ny = cy_cov + dy;
                if (!nav_in_bounds(nx, ny)) continue;
                int idx = ny * nav_nx + nx;
                double pz = 0.0;
                if (on_roof) {
                    if (nav_roof_prism[idx] < 0 || std::abs(nav_roof_z[idx] - cover_z) > 2.0) continue;
                    pz = nav_roof_z[idx];
                } else {
                    if (!is_nav_cell_clear(idx, mech_radius, mech_height)) continue;
                    pz = nav_ground_z[idx];
                }
                Vec2 pw = nav_to_world(nx, ny);
                double d_cov = (pw - out_cover).len();
                if (d_cov < 2.5 || d_cov > 13.5) continue;
                if (std::hypot(pw.x - zone_center.x, pw.y - zone_center.y) > safe_z_r) continue;
                if (!on_roof && !is_nav_line_walkable(out_cover, pw, mech_radius, mech_height)) continue;

                Vec3 p_muz(pw.x, pw.y, pz + 0.78 * mech_height);
                if (!has_solid_los(p_muz, primary_aim_pt)) continue;

                // Count OTHER threats that also see this peek cell
                int other_vis = 0;
                for (size_t ti = 0; ti < tlim; ++ti) {
                    if (threat_ids[ti] == primary_id) continue;
                    if ((threat_eyes[ti].xy() - pw).len() > 250.0) continue;
                    if (has_solid_los(threat_eyes[ti], p_muz)) ++other_vis;
                }
                double pk_sc = other_vis * 100.0 + d_cov * 1.4 + (pw - self_pos.xy()).len() * 0.25;
                if (pk_sc < best_pk_sc) {
                    best_pk_sc = pk_sc;
                    best_pk = pw;
                    found_pk = true;
                }
            }
        }
        if (found_pk) {
            out_peek = best_pk;
            out_has_peek = true;
        }
        return true;
    }

    // Check if (x, y) is safely on top of a climbable roof and return roof_z.
    bool get_roof_at(double x, double y, double& out_roof_z, int& out_prism) const {
        if (nav_nx <= 0 || nav_ny <= 0) return false;
        int ix, iy;
        world_to_nav(x, y, ix, iy);
        int idx = iy * nav_nx + ix;
        if (nav_roof_prism[idx] >= 0) {
            out_roof_z = nav_roof_z[idx];
            out_prism = nav_roof_prism[idx];
            return true;
        }
        return false;
    }

    // Find a clear walkable ground launch spot without overhangs to jet onto `roof_pt`.
    bool find_roof_launch_for_point(
        const Vec3& roof_pt,
        const Vec3& self_pos,
        double mech_r,
        double mech_h,
        double max_dz,
        RoofSpot& out_spot
    ) const {
        if (nav_nx <= 0 || nav_ny <= 0) return false;
        int rx = -1, ry = -1;
        world_to_nav(roof_pt.x, roof_pt.y, rx, ry);
        int ridx = ry * nav_nx + rx;
        int rpid = nav_roof_prism[ridx];
        double rz = nav_roof_z[ridx];
        if (rpid < 0 || std::abs(rz - roof_pt.z) > 3.5) {
            // Search 5x5 neighborhood for matching roof cell
            double best_rd = 1e9;
            for (int dy = -2; dy <= 2; ++dy) {
                for (int dx = -2; dx <= 2; ++dx) {
                    int nx = rx + dx, ny = ry + dy;
                    if (!nav_in_bounds(nx, ny)) continue;
                    int idx = ny * nav_nx + nx;
                    if (nav_roof_prism[idx] >= 0 && std::abs(nav_roof_z[idx] - roof_pt.z) <= 3.5) {
                        Vec2 w = nav_to_world(nx, ny);
                        double d = (w - roof_pt.xy()).len();
                        if (d < best_rd) {
                            best_rd = d;
                            rpid = nav_roof_prism[idx];
                            rz = nav_roof_z[idx];
                            rx = nx; ry = ny;
                        }
                    }
                }
            }
        }
        if (rpid < 0) return false;

        int best_g = -1;
        double best_sc = 1e18;
        for (int dy = -9; dy <= 9; ++dy) {
            for (int dx = -9; dx <= 9; ++dx) {
                int nx = rx + dx, ny = ry + dy;
                if (!nav_in_bounds(nx, ny)) continue;
                int gidx = ny * nav_nx + nx;
                if (nav_roof_prism[gidx] >= 0) continue;
                if (!is_nav_cell_clear(gidx, mech_r, mech_h)) continue;
                if (nav_ceiling_z[gidx] < rz + mech_h + 1.5) continue; // avoid overhangs!

                double dz = rz - nav_ground_z[gidx];
                if (dz < 3.0 || dz > max_dz) continue;

                Vec2 gw = nav_to_world(nx, ny);
                double d_roof = (gw - roof_pt.xy()).len();
                if (d_roof > 34.0) continue;

                // Ensure no taller building wall sits above roof height between launch and roof_pt
                Vec2 mid = gw * 0.5 + roof_pt.xy() * 0.5;
                if (is_wall_blocked(mid.x, mid.y, rz + 0.5, mech_r * 0.85, mech_h, 1.2)) continue;

                double d_self = (gw - self_pos.xy()).len();
                double sc = d_self + d_roof * 1.45;
                if (sc < best_sc) {
                    best_sc = sc;
                    best_g = gidx;
                }
            }
        }
        if (best_g < 0) return false;

        Vec2 gw = nav_to_world(best_g % nav_nx, best_g / nav_nx);
        out_spot.approach_pos = Vec3(gw.x, gw.y, nav_ground_z[best_g]);
        out_spot.roof_pos = roof_pt;
        out_spot.prism_id = rpid;
        out_spot.climb_dz = rz - nav_ground_z[best_g];
        out_spot.max_edge_dist = 4.0;
        return true;
    }

    // Choose a high-value combat rooftop inside next_zone with interior cover & clear launch.
    bool find_best_combat_roof(
        const Vec3& self_pos,
        const Vec2& zone_next_c,
        double zone_next_r,
        double max_search_d,
        double max_dz,
        double energy,
        double jet_drain,
        RoofSpot& out_spot
    ) const {
        double best_sc = -1e9;
        bool found = false;
        double safe_r = std::max(8.0, zone_next_r - 16.0);
        for (const RoofSpot& rs : roof_spots) {
            if (rs.climb_dz < 7.0 || rs.climb_dz > max_dz) continue;
            if (rs.max_edge_dist < 4.5) continue; // require enough roof width to break ground LOS
            double d = (rs.approach_pos.xy() - self_pos.xy()).len();
            if (d > max_search_d) continue;
            double dz_center = (rs.roof_pos.xy() - zone_next_c).len();
            if (dz_center > safe_r) continue;
            double req_e = (rs.climb_dz / 9.2) * jet_drain + 18.0;
            if (req_e > energy) continue;

            double sc = 120.0 - d * 1.2 + std::min(rs.max_edge_dist, 14.0) * 3.0 - std::abs(rs.climb_dz - 15.0) * 1.3;
            sc += std::max(0.0, 1.0 - dz_center / safe_r) * 25.0;
            if (sc > best_sc) {
                best_sc = sc;
                out_spot = rs;
                found = true;
            }
        }
        return found;
    }

private:
    static int clamp_val_int(int v, int lo, int hi) {
        return std::max(lo, std::min(hi, v));
    }

    static bool ray_aabb_2d(
        double ox, double oy, double dx, double dy,
        double minx, double maxx, double miny, double maxy,
        double max_t
    ) {
        double t0 = 0.0, t1 = max_t;
        if (std::abs(dx) < 1e-12) {
            if (ox < minx || ox > maxx) return false;
        } else {
            double inv = 1.0 / dx;
            double a = (minx - ox) * inv;
            double b = (maxx - ox) * inv;
            if (a > b) std::swap(a, b);
            t0 = std::max(t0, a);
            t1 = std::min(t1, b);
            if (t0 > t1) return false;
        }
        if (std::abs(dy) < 1e-12) {
            if (oy < miny || oy > maxy) return false;
        } else {
            double inv = 1.0 / dy;
            double a = (miny - oy) * inv;
            double b = (maxy - oy) * inv;
            if (a > b) std::swap(a, b);
            t0 = std::max(t0, a);
            t1 = std::min(t1, b);
            if (t0 > t1) return false;
        }
        return true;
    }

    static double ray_crown_chord(const Vec3& orig, const Vec3& dir, double max_t, const Tree& tr) {
        double cz = tr.z + 0.5 * (tr.crown_base + tr.height);
        double half_h = 0.5 * std::max(1.0, tr.height - tr.crown_base);
        double r = tr.crown_r;
        // Ray vs ellipsoid centered at (crown_x, crown_y, cz) with radii (r, r, half_h)
        double ox = (orig.x - tr.crown_x) / r;
        double oy = (orig.y - tr.crown_y) / r;
        double oz = (orig.z - cz) / half_h;
        double dx = dir.x / r;
        double dy = dir.y / r;
        double dz = dir.z / half_h;
        double a = dx * dx + dy * dy + dz * dz;
        if (a < 1e-12) return 0.0;
        double b = 2.0 * (ox * dx + oy * dy + oz * dz);
        double c = ox * ox + oy * oy + oz * oz - 1.0;
        double disc = b * b - 4.0 * a * c;
        if (disc <= 0.0) return 0.0;
        double sq = std::sqrt(disc);
        double t0 = std::max(0.0, (-b - sq) / (2.0 * a));
        double t1 = std::min(max_t, (-b + sq) / (2.0 * a));
        return (t1 > t0) ? (t1 - t0) : 0.0;
    }

    void build_spatial_grids() {
        grid_ox = std::floor(min_x / grid_cell) * grid_cell - grid_cell;
        grid_oy = std::floor(min_y / grid_cell) * grid_cell - grid_cell;
        double end_x = std::ceil(max_x / grid_cell) * grid_cell + grid_cell;
        double end_y = std::ceil(max_y / grid_cell) * grid_cell + grid_cell;
        grid_nx = std::max(1, static_cast<int>(std::ceil((end_x - grid_ox) / grid_cell)));
        grid_ny = std::max(1, static_cast<int>(std::ceil((end_y - grid_oy) / grid_cell)));

        prism_grid.assign(static_cast<size_t>(grid_nx) * grid_ny, {});
        for (const Prism& p : prisms) {
            int ix0 = clamp_val_int(static_cast<int>(std::floor((p.min_x - grid_ox) / grid_cell)), 0, grid_nx - 1);
            int ix1 = clamp_val_int(static_cast<int>(std::floor((p.max_x - grid_ox) / grid_cell)), 0, grid_nx - 1);
            int iy0 = clamp_val_int(static_cast<int>(std::floor((p.min_y - grid_oy) / grid_cell)), 0, grid_ny - 1);
            int iy1 = clamp_val_int(static_cast<int>(std::floor((p.max_y - grid_oy) / grid_cell)), 0, grid_ny - 1);
            for (int iy = iy0; iy <= iy1; ++iy) {
                for (int ix = ix0; ix <= ix1; ++ix) {
                    prism_grid[static_cast<size_t>(iy) * grid_nx + ix].push_back(p.id);
                }
            }
        }

        tree_grid.assign(static_cast<size_t>(grid_nx) * grid_ny, {});
        for (int tid = 0; tid < static_cast<int>(trees.size()); ++tid) {
            const Tree& tr = trees[tid];
            double rx = std::max(tr.crown_r, tr.trunk_r) + 1.5;
            double cx = tr.crown_x;
            double cy = tr.crown_y;
            int ix0 = clamp_val_int(static_cast<int>(std::floor((std::min(cx, tr.x) - rx - grid_ox) / grid_cell)), 0, grid_nx - 1);
            int ix1 = clamp_val_int(static_cast<int>(std::floor((std::max(cx, tr.x) + rx - grid_ox) / grid_cell)), 0, grid_nx - 1);
            int iy0 = clamp_val_int(static_cast<int>(std::floor((std::min(cy, tr.y) - rx - grid_oy) / grid_cell)), 0, grid_ny - 1);
            int iy1 = clamp_val_int(static_cast<int>(std::floor((std::max(cy, tr.y) + rx - grid_oy) / grid_cell)), 0, grid_ny - 1);
            for (int iy = iy0; iy <= iy1; ++iy) {
                for (int ix = ix0; ix <= ix1; ++ix) {
                    tree_grid[static_cast<size_t>(iy) * grid_nx + ix].push_back(tid);
                }
            }
        }
    }

    void build_nav_grid() {
        nav_ox = std::ceil(min_x / nav_step) * nav_step;
        nav_oy = std::ceil(min_y / nav_step) * nav_step;
        nav_nx = std::max(1, static_cast<int>(std::floor((max_x - nav_ox) / nav_step)) + 1);
        nav_ny = std::max(1, static_cast<int>(std::floor((max_y - nav_oy) / nav_step)) + 1);

        size_t total = static_cast<size_t>(nav_nx) * nav_ny;
        nav_walkable.assign(total, 1);
        nav_ground_z.assign(total, 0.0f);
        nav_wall_dist.assign(total, 999.0f);
        nav_ceiling_z.assign(total, 1e9f);
        nav_roof_z.assign(total, -1e9f);
        nav_roof_prism.assign(total, -1);
        nav_roof_edge_dist.assign(total, 0.0f);

        std::queue<int> bfs;
        const double clear_r = 2.9;

        for (int iy = 0; iy < nav_ny; ++iy) {
            double wy = nav_oy + iy * nav_step;
            for (int ix = 0; ix < nav_nx; ++ix) {
                double wx = nav_ox + ix * nav_step;
                size_t idx = static_cast<size_t>(iy) * nav_nx + ix;
                double tz = terrain_height(wx, wy);
                nav_ground_z[idx] = static_cast<float>(tz);

                bool blocked = false;
                if (wx < min_x + 3.2 || wx > max_x - 3.2 || wy < min_y + 3.2 || wy > max_y - 3.2) {
                    blocked = true;
                } else if (terr_nx > 1) {
                    for (double oy : {-1.5, 0.0, 1.5}) {
                        for (double ox : {-1.5, 0.0, 1.5}) {
                            if (terrain_slope_deg(wx + ox, wy + oy) > max_slope_deg - 3.0) {
                                blocked = true;
                                break;
                            }
                        }
                        if (blocked) break;
                    }
                }

                // Check prism overlap at ground level & check roof eligibility
                int gx = clamp_val_int(static_cast<int>(std::floor((wx - grid_ox) / grid_cell)), 0, grid_nx - 1);
                int gy = clamp_val_int(static_cast<int>(std::floor((wy - grid_oy) / grid_cell)), 0, grid_ny - 1);
                double best_roof = -1e9;
                int best_rpid = -1;
                double low_top = tz;
                double low_ceil = 1e9;

                if (grid_nx > 0 && grid_ny > 0) {
                    const auto& cell = prism_grid[static_cast<size_t>(gy) * grid_nx + gx];
                    for (int pid : cell) {
                        const Prism& p = prisms[pid];
                        if (wx + clear_r < p.min_x || wx - clear_r > p.max_x ||
                            wy + clear_r < p.min_y || wy - clear_r > p.max_y) {
                            continue;
                        }
                        bool inside = point_in_prism_2d(p, wx, wy);
                        double ed = min_dist_to_prism_edges(p, wx, wy);
                        if (inside || ed < clear_r) {
                            // Blocks ground walkability if prism overlaps [tz + 1.2, tz + 8.8]
                            if (p.top > tz + 1.2 && p.base < tz + 8.95) {
                                blocked = true;
                            }
                            if (inside && p.top <= tz + 1.2 && p.top > low_top) {
                                low_top = p.top;
                            }
                            if (p.base > tz + 1.2 && p.base < low_ceil) {
                                low_ceil = p.base;
                            }
                        }
                        if (inside && ed >= 2.6 && p.top > tz + 4.0 && p.top < tz + 54.0) {
                            if (p.top > best_roof) {
                                best_roof = p.top;
                                best_rpid = pid;
                            }
                        }
                    }
                }
                nav_ground_z[idx] = static_cast<float>(low_top);
                nav_ceiling_z[idx] = static_cast<float>(low_ceil);
                if (best_rpid >= 0) {
                    // Make sure no higher prism blocks standing headroom on this roof cell
                    bool head_blocked = false;
                    const auto& cell = prism_grid[static_cast<size_t>(gy) * grid_nx + gx];
                    for (int pid : cell) {
                        if (pid == best_rpid) continue;
                        const Prism& p = prisms[pid];
                        if (p.base < best_roof + 9.2 && p.top > best_roof + 0.5) {
                            if (point_in_prism_2d(p, wx, wy) || min_dist_to_prism_edges(p, wx, wy) < 2.8) {
                                head_blocked = true;
                                break;
                            }
                        }
                    }
                    if (!head_blocked) {
                        nav_roof_z[idx] = static_cast<float>(best_roof);
                        nav_roof_prism[idx] = best_rpid;
                    }
                }

                if (blocked) {
                    nav_walkable[idx] = 0;
                    nav_wall_dist[idx] = 0.0f;
                    bfs.push(static_cast<int>(idx));
                }
            }
        }

        static const int kDx[4] = {1, -1, 0, 0};
        static const int kDy[4] = {0, 0, 1, -1};
        while (!bfs.empty()) {
            int u = bfs.front();
            bfs.pop();
            int ux = u % nav_nx, uy = u / nav_nx;
            float nd = nav_wall_dist[u] + static_cast<float>(nav_step);
            for (int d = 0; d < 4; ++d) {
                int vx = ux + kDx[d], vy = uy + kDy[d];
                if (!nav_in_bounds(vx, vy)) continue;
                int v = vy * nav_nx + vx;
                if (nd < nav_wall_dist[v]) {
                    nav_wall_dist[v] = nd;
                    bfs.push(v);
                }
            }
        }

        // Compute distance inside roof from roof edge (used for roof-edge peek cover)
        std::queue<int> rbfs;
        for (size_t i = 0; i < total; ++i) {
            if (nav_roof_prism[i] < 0) {
                nav_roof_edge_dist[i] = 0.0f;
                rbfs.push(static_cast<int>(i));
            } else {
                nav_roof_edge_dist[i] = 999.0f;
            }
        }
        while (!rbfs.empty()) {
            int u = rbfs.front();
            rbfs.pop();
            int ux = u % nav_nx, uy = u / nav_nx;
            float nd = nav_roof_edge_dist[u] + static_cast<float>(nav_step);
            for (int d = 0; d < 4; ++d) {
                int vx = ux + kDx[d], vy = uy + kDy[d];
                if (!nav_in_bounds(vx, vy)) continue;
                int v = vy * nav_nx + vx;
                if (nav_roof_prism[v] >= 0 && nd < nav_roof_edge_dist[v]) {
                    nav_roof_edge_dist[v] = nd;
                    rbfs.push(v);
                }
            }
        }

        // Build representative climbable RoofSpot registry (up to 1 spot per roof prism)
        std::vector<int> best_cell_for_prism(prisms.size(), -1);
        std::vector<double> best_score_for_prism(prisms.size(), -1e9);
        std::vector<float> max_edge_for_prism(prisms.size(), 0.0f);
        for (int iy = 0; iy < nav_ny; ++iy) {
            for (int ix = 0; ix < nav_nx; ++ix) {
                int idx = iy * nav_nx + ix;
                int pid = nav_roof_prism[idx];
                if (pid < 0) continue;
                max_edge_for_prism[pid] = std::max(max_edge_for_prism[pid], nav_roof_edge_dist[idx]);
                double dz = nav_roof_z[idx] - nav_ground_z[idx];
                if (dz < 5.0 || dz > 48.0) continue;
                double ed = nav_roof_edge_dist[idx];
                double score = 100.0 - std::abs(dz - 16.0) + std::min(ed, 8.0) * 3.0;
                if (score > best_score_for_prism[pid]) {
                    best_score_for_prism[pid] = score;
                    best_cell_for_prism[pid] = idx;
                }
            }
        }

        for (size_t pid = 0; pid < prisms.size(); ++pid) {
            int ridx = best_cell_for_prism[pid];
            if (ridx < 0) continue;
            int rx = ridx % nav_nx, ry = ridx / nav_nx;
            Vec2 rw = nav_to_world(rx, ry);
            int best_g = -1;
            double best_gd2 = 1e18;
            double rz = nav_roof_z[ridx];
            for (int dy = -9; dy <= 9; ++dy) {
                for (int dx = -9; dx <= 9; ++dx) {
                    int nx = rx + dx, ny = ry + dy;
                    if (!nav_in_bounds(nx, ny)) continue;
                    int gidx = ny * nav_nx + nx;
                    if (!nav_walkable[gidx] || nav_roof_prism[gidx] >= 0) continue;
                    if (nav_ceiling_z[gidx] < rz + 10.5) continue;
                    Vec2 gw = nav_to_world(nx, ny);
                    double d2 = (gw - rw).len_sq();
                    if (d2 < best_gd2) {
                        best_gd2 = d2;
                        best_g = gidx;
                    }
                }
            }
            if (best_g >= 0 && best_gd2 <= 36.0 * 36.0) {
                Vec2 gw = nav_to_world(best_g % nav_nx, best_g / nav_nx);
                RoofSpot rs;
                rs.roof_pos = Vec3(rw.x, rw.y, rz);
                rs.approach_pos = Vec3(gw.x, gw.y, nav_ground_z[best_g]);
                rs.prism_id = static_cast<int>(pid);
                rs.climb_dz = rs.roof_pos.z - rs.approach_pos.z;
                rs.max_edge_dist = max_edge_for_prism[pid];
                roof_spots.push_back(rs);
            }
        }
    }
};

} // namespace mf
