#pragma once

#include "config.hpp"
#include "json.hpp"
#include "math3d.hpp"
#include "world.hpp"
#include <algorithm>
#include <cmath>
#include <string>
#include <unordered_map>
#include <vector>

namespace mf {

struct WeaponState {
    bool present = false;
    std::string kind;
    double cooldown = 0.0;
    double ammo = 0.0;
    double reload = 0.0;
    double charge = 0.0;
    WeaponConfig stats;
};

struct SelfState {
    int id = 0;
    Vec3 pos;
    Vec3 vel;
    double aim_yaw = 0.0;
    double aim_pitch = 0.0;
    double hp = 1400.0;
    double max_hp = 1400.0;
    double energy = 100.0;
    double max_energy = 100.0;
    bool grounded = true;
    int cubes = 0;
    bool in_zone = true;
    std::vector<std::string> upgrades;
    WeaponState weapons[2];

    // Live mech stats from self.stats
    double radius = 2.5;
    double height = 9.0;
    double eye_height = 8.0;
    double muzzle_height = 7.0;
    double walk_speed = 11.7;
    double boost_speed = 19.5;
    double ground_accel = 58.5;
    double air_accel = 12.0;
    double gravity = 22.0;
    double jump_speed = 11.0;
    double jet_accel = 34.0;
    double max_rise_speed = 10.0;
    double step_up = 1.2;
    double max_slope_deg = 50.0;
    double energy_regen = 18.0;
    double boost_drain = 17.0;
    double jet_drain = 15.0;
    double turn_rate = 4.0;
    double pitch_rate = 3.0;
    double min_pitch = -0.7;
    double max_pitch = 1.3;
    double regen_delay = 5.0;
    double regen_per_s = 45.0;
    double charge_move_mult = 0.5;
    double armor = 0.0;
    double rear_mult = 1.5;
    double front_arc_deg = 180.0;
    double near_range_bonus = 0.0;
    double vision_bonus = 0.0;
    double hearing = 1.0;

    Vec3 eye_pos() const { return {pos.x, pos.y, pos.z + eye_height}; }
    Vec3 center_pos() const { return {pos.x, pos.y, pos.z + 0.5 * height}; }
    Vec3 muzzle_pivot() const { return {pos.x, pos.y, pos.z + muzzle_height}; }
    Vec3 mortar_pivot() const { return {pos.x, pos.y, pos.z + height + 0.5}; }
    double damage_mult(const GameConfig& cfg) const {
        return 1.0 + cfg.damage_per_cube * std::min(cubes, cfg.stat_cap);
    }

    int find_weapon(const std::string& kind) const {
        for (int i = 0; i < 2; ++i) {
            if (weapons[i].present && weapons[i].kind == kind) return i;
        }
        return -1;
    }

    int empty_slot() const {
        if (!weapons[0].present) return 0;
        if (!weapons[1].present) return 1;
        return -1;
    }
};

struct TrackedActor {
    int id = -1;
    bool is_mech = true;
    Vec3 pos;
    Vec3 vel;
    Vec3 prev_vel;
    Vec3 accel;
    double aim_yaw = 0.0;
    double aim_pitch = 0.0;
    double hp = 1400.0;
    double max_hp = 1400.0;
    int cubes = 0;
    std::vector<std::string> weapons;
    bool charging = false;
    double charge_start_t = -1.0;

    bool in_obs_now = false;
    bool actually_seen = false;
    bool in_solid_los = false;
    double best_aim_z_frac = 0.50;
    double last_seen_t = -999.0;
    double last_obs_t = -999.0;
    double last_laser_fire_t = -999.0;

    double damaged_us_t = -999.0;
    double damage_to_us = 0.0;
    double we_hit_t = -999.0;
    double prev_hp = -1.0;

    bool has_weapon(const std::string& k) const {
        for (const auto& w : weapons) {
            if (w == k) return true;
        }
        return false;
    }

    double radius(const GameConfig& cfg) const {
        if (!is_mech) return cfg.npc_radius;
        return cfg.mech_radius * (1.0 + cfg.size_per_cube * cubes);
    }

    double height(const GameConfig& cfg) const {
        if (!is_mech) return cfg.npc_height;
        return cfg.mech_height * (1.0 + cfg.size_per_cube * cubes);
    }

    Vec3 center_pos(const GameConfig& cfg) const {
        return {pos.x, pos.y, pos.z + 0.5 * height(cfg)};
    }

    Vec3 aim_pos(const GameConfig& cfg) const {
        return {pos.x, pos.y, pos.z + best_aim_z_frac * height(cfg)};
    }

    Vec3 top_pos(const GameConfig& cfg) const {
        return {pos.x, pos.y, pos.z + height(cfg)};
    }
};

struct RememberedItem {
    int id = -1;
    std::string kind; // for pickups
    Vec3 pos;
    double hp = 300.0;
    double last_seen_t = -999.0;
    bool visible_now = false;
    bool on_roof = false;
};

struct ProjectileThreat {
    int id = -1;
    std::string kind; // gun, mortar, npc
    Vec3 pos;
    Vec3 vel;
    Vec3 impact_pos;
    double impact_t = 0.0;
    bool has_impact = false;
};

struct SoundContact {
    std::string kind;
    double bearing = 0.0;
    double est_dist = 100.0;
    double time = 0.0;
    Vec2 est_pos;
};

struct DropInfo {
    int id = -1;
    Vec3 pos;
    double radius = 8.0;
    double lands_in = 0.0;
    double capture_s = 4.0;
    double progress = 0.0;
    int holder = -1;
};

struct ZoneInfo {
    Vec2 center;
    double radius = 560.0;
    Vec2 next_center;
    double next_radius = 380.0;
    double shrink_start = 60.0;
    double shrink_end = 110.0;
    double dps = 20.0;
};

class Tracker {
public:
    double t = 0.0;
    int tick = 0;
    int alive = 16;

    double last_combat_t = -999.0;
    double shorted_until_t = -999.0;
    double last_damaged_t = -999.0;
    double last_npc_damaged_t = -999.0;
    double last_damaged_bearing = 0.0;
    int last_attacker_id = -1;
    bool last_damaged_rear = false;
    int my_kills = 0;

    // 0.0 = 1v15 Practice Squad, 1.0 = 16-way FFA
    double ffa_confidence = 0.5;
    bool saw_external_combat = false;
    double squad_coop_score = 0.0;

    std::unordered_map<int, TrackedActor> actors;
    std::unordered_map<int, RememberedItem> crates;
    std::unordered_map<int, RememberedItem> cubes;
    std::unordered_map<int, RememberedItem> pickups;
    std::vector<ProjectileThreat> projectiles;
    std::vector<SoundContact> sounds;
    std::vector<DropInfo> drops;
    ZoneInfo zone;

    static SelfState parse_self(const Json& js, const GameConfig& cfg) {
        SelfState s;
        s.id = js["id"].as_int(0);
        const auto& p = js["pos"].arr_val;
        if (p.size() >= 3) s.pos = {p[0].as_double(), p[1].as_double(), p[2].as_double()};
        const auto& v = js["vel"].arr_val;
        if (v.size() >= 3) s.vel = {v[0].as_double(), v[1].as_double(), v[2].as_double()};
        const auto& a = js["aim"].arr_val;
        if (a.size() >= 2) {
            s.aim_yaw = a[0].as_double();
            s.aim_pitch = a[1].as_double();
        }
        s.hp = js["hp"].as_double(cfg.mech_hp);
        s.max_hp = js["max_hp"].as_double(cfg.mech_hp);
        s.energy = js["energy"].as_double(cfg.energy);
        s.max_energy = js["max_energy"].as_double(cfg.energy);
        s.grounded = js["grounded"].as_bool(true);
        s.cubes = js["cubes"].as_int(0);
        s.in_zone = js["in_zone"].as_bool(true);

        for (const auto& u : js["upgrades"].arr_val) {
            s.upgrades.push_back(u.as_str());
        }

        const auto& ws = js["weapons"].arr_val;
        for (size_t i = 0; i < 2 && i < ws.size(); ++i) {
            if (ws[i].is_null() || !ws[i].is_object()) continue;
            WeaponState w;
            w.present = true;
            w.kind = ws[i]["kind"].as_str();
            w.cooldown = ws[i]["cooldown"].as_double(0.0);
            w.ammo = ws[i]["ammo"].as_double(0.0);
            w.reload = ws[i]["reload"].as_double(0.0);
            w.charge = ws[i]["charge"].as_double(0.0);
            w.stats = GameConfig::parse_weapon(ws[i]["stats"]);
            s.weapons[i] = std::move(w);
        }

        const auto& st = js["stats"];
        s.radius = st["radius"].as_double(cfg.mech_radius);
        s.height = st["height"].as_double(cfg.mech_height);
        s.eye_height = st["eye_height"].as_double(cfg.eye_height);
        s.muzzle_height = st["muzzle_height"].as_double(cfg.muzzle_height);
        s.walk_speed = st["walk_speed"].as_double(cfg.walk_speed);
        s.boost_speed = st["boost_speed"].as_double(cfg.boost_speed);
        s.ground_accel = st["ground_accel"].as_double(cfg.ground_accel);
        s.air_accel = st["air_accel"].as_double(cfg.air_accel);
        s.gravity = st["gravity"].as_double(cfg.gravity);
        s.jump_speed = st["jump_speed"].as_double(cfg.jump_speed);
        s.jet_accel = st["jet_accel"].as_double(cfg.jet_accel);
        s.max_rise_speed = st["max_rise_speed"].as_double(cfg.max_rise_speed);
        s.step_up = st["step_up"].as_double(cfg.step_up);
        s.max_slope_deg = st["max_slope_deg"].as_double(cfg.max_slope_deg);
        s.energy_regen = st["energy_regen"].as_double(cfg.energy_regen);
        s.boost_drain = st["boost_drain"].as_double(cfg.boost_drain);
        s.jet_drain = st["jet_drain"].as_double(cfg.jet_drain);
        s.turn_rate = st["turn_rate"].as_double(cfg.turn_rate);
        s.pitch_rate = st["pitch_rate"].as_double(cfg.pitch_rate);
        s.min_pitch = st["min_pitch"].as_double(cfg.min_pitch);
        s.max_pitch = st["max_pitch"].as_double(cfg.max_pitch);
        s.regen_delay = st["regen_delay"].as_double(cfg.regen_delay);
        s.regen_per_s = st["regen_per_s"].as_double(cfg.regen_per_s);
        s.charge_move_mult = st["charge_move_mult"].as_double(cfg.charge_move_mult);
        s.armor = st["armor"].as_double(0.0);
        s.rear_mult = st["rear_mult"].as_double(cfg.rear_mult);
        s.front_arc_deg = st["front_arc_deg"].as_double(cfg.front_arc_deg);
        s.near_range_bonus = st["near_range_bonus"].as_double(0.0);
        s.vision_bonus = st["vision_bonus"].as_double(0.0);
        s.hearing = st["hearing"].as_double(1.0);
        return s;
    }

    void update(const Json& obs, const SelfState& self, const GameConfig& cfg, const World& world) {
        double prev_t = t;
        t = obs["t"].as_double(t);
        double dt = std::max(0.05, t - prev_t);
        tick = obs["tick"].as_int(tick);
        alive = obs["alive"].as_int(alive);

        if (!self.in_zone) {
            last_combat_t = t;
        }

        // Zone
        const auto& zj = obs["zone"];
        if (zj["center"].arr_val.size() >= 2) {
            zone.center = {zj["center"][0].as_double(), zj["center"][1].as_double()};
        }
        zone.radius = zj["radius"].as_double(zone.radius);
        if (zj["next_center"].arr_val.size() >= 2) {
            zone.next_center = {zj["next_center"][0].as_double(), zj["next_center"][1].as_double()};
        }
        zone.next_radius = zj["next_radius"].as_double(zone.next_radius);
        zone.shrink_start = zj["shrink_start"].as_double(zone.shrink_start);
        zone.shrink_end = zj["shrink_end"].as_double(zone.shrink_end);
        zone.dps = zj["dps"].as_double(zone.dps);

        // Drops
        drops.clear();
        for (const auto& dj : obs["drops"].arr_val) {
            DropInfo d;
            d.id = dj["id"].as_int(-1);
            const auto& p = dj["pos"].arr_val;
            if (p.size() >= 3) d.pos = {p[0].as_double(), p[1].as_double(), p[2].as_double()};
            d.radius = dj["radius"].as_double(cfg.drop_radius);
            d.lands_in = dj["lands_in"].as_double(0.0);
            d.capture_s = dj["capture_s"].as_double(cfg.drop_capture_s);
            d.progress = dj["progress"].as_double(0.0);
            d.holder = dj["holder"].is_null() ? -1 : dj["holder"].as_int(-1);
            drops.push_back(d);
        }

        // Events
        bool we_hit_actor_this_tick = false;
        for (const auto& ev : obs["events"].arr_val) {
            const std::string& et = ev["type"].as_str();
            if (et == "damaged") {
                last_combat_t = t;
                last_damaged_t = t;
                double amt = ev["amount"].as_double(0.0);
                if (!ev["bearing"].is_null()) {
                    last_damaged_bearing = ev["bearing"].as_double(0.0);
                }
                last_damaged_rear = ev["rear"].as_bool(false);
                if (ev["weapon"].as_str() == "npc") {
                    last_npc_damaged_t = t;
                }
                if (!ev["by"].is_null()) {
                    int by = ev["by"].as_int(-1);
                    last_attacker_id = by;
                    if (by >= 0 && by < 100) {
                        auto& a = actors[by];
                        a.id = by;
                        a.is_mech = true;
                        a.damaged_us_t = t;
                        a.damage_to_us += amt;
                        if (ev["weapon"].as_str() == "laser") {
                            a.last_laser_fire_t = t;
                        }
                    }
                }
            } else if (et == "hit") {
                last_combat_t = t;
                int target = ev["target"].as_int(-1);
                if (target >= 0 && target < 1000) {
                    we_hit_actor_this_tick = true;
                    auto it = actors.find(target);
                    if (it != actors.end()) {
                        it->second.we_hit_t = t;
                    }
                }
            } else if (et == "effect") {
                if (ev["effect"].as_str() == "short") {
                    shorted_until_t = std::max(shorted_until_t, t + cfg.lightning.short_s);
                }
            } else if (et == "kill") {
                ++my_kills;
                int target = ev["target"].as_int(-1);
                actors.erase(target);
            }
        }

        // Mark existing actors stale first
        for (auto& kv : actors) {
            kv.second.in_obs_now = false;
            kv.second.actually_seen = false;
            kv.second.in_solid_los = false;
        }

        double near_r = cfg.vision_near_range + self.near_range_bonus;
        double fov_r = cfg.vision_range + self.vision_bonus;
        Vec3 my_eye = self.eye_pos();
        Vec3 my_muzzle = self.muzzle_pivot();

        // Update mechs/NPCs from obs.mechs
        for (const auto& mj : obs["mechs"].arr_val) {
            int id = mj["id"].as_int(-1);
            if (id < 0 || id == self.id) continue;
            TrackedActor& a = actors[id];
            a.id = id;
            a.is_mech = (mj["kind"].as_str("mech") == "mech");

            Vec3 new_pos;
            const auto& p = mj["pos"].arr_val;
            if (p.size() >= 3) new_pos = {p[0].as_double(), p[1].as_double(), p[2].as_double()};
            Vec3 new_vel;
            const auto& v = mj["vel"].arr_val;
            if (v.size() >= 3) new_vel = {v[0].as_double(), v[1].as_double(), v[2].as_double()};

            if (a.last_obs_t > 0.0 && (t - a.last_obs_t) < 0.5) {
                Vec3 raw_acc = (new_vel - a.vel) / dt;
                a.accel = a.accel * 0.6 + raw_acc * 0.4;
            } else {
                a.accel = {0, 0, 0};
            }
            a.prev_vel = a.vel;
            a.pos = new_pos;
            a.vel = new_vel;

            const auto& am = mj["aim"].arr_val;
            if (am.size() >= 2) {
                a.aim_yaw = am[0].as_double();
                a.aim_pitch = am[1].as_double();
            }

            double new_hp = mj["hp"].as_double(a.hp);
            if (a.prev_hp > 0.0 && new_hp < a.prev_hp - 1.0 && (t - a.we_hit_t) > 0.3 && !we_hit_actor_this_tick) {
                if (a.is_mech) saw_external_combat = true;
            }
            a.hp = new_hp;
            a.prev_hp = new_hp;
            a.max_hp = mj["max_hp"].as_double(a.is_mech ? cfg.mech_hp : cfg.npc_hp);
            a.cubes = mj["cubes"].as_int(0);

            a.weapons.clear();
            for (const auto& wj : mj["weapons"].arr_val) {
                a.weapons.push_back(wj.as_str());
            }

            bool prev_ch = a.charging;
            bool ch = mj["charging"].as_bool(false);
            if (ch && !prev_ch) {
                a.charge_start_t = t;
            } else if (!ch) {
                if (prev_ch && a.charge_start_t > 0.0 && (t - a.charge_start_t) >= cfg.laser.min_charge) {
                    a.last_laser_fire_t = std::max(a.last_laser_fire_t, t);
                }
                a.charge_start_t = -1.0;
            }
            a.charging = ch;
            a.in_obs_now = true;
            a.last_obs_t = t;

            // Compute exact solid LOS strictly from muzzle_pivot across 3 vertical slices
            double th = a.height(cfg);
            a.in_solid_los = false;
            a.best_aim_z_frac = 0.50;
            for (double zf : {0.50, 0.78, 0.25}) {
                Vec3 tp(a.pos.x, a.pos.y, a.pos.z + zf * th);
                if (world.has_solid_los(my_muzzle, tp)) {
                    a.in_solid_los = true;
                    a.best_aim_z_frac = zf;
                    break;
                }
            }
            Vec3 tc = a.center_pos(cfg);
            Vec3 tt = a.top_pos(cfg);
            a.actually_seen = world.can_see_point(my_eye, tc, tt, near_r, fov_r, self.aim_yaw, cfg.vision_fov_deg, cfg.canopy_blocks);
            if (a.actually_seen) {
                a.last_seen_t = t;
            }
        }

        // Prune very stale actors
        for (auto it = actors.begin(); it != actors.end();) {
            if (!it->second.in_obs_now && (t - it->second.last_obs_t) > 12.0) {
                it = actors.erase(it);
            } else {
                ++it;
            }
        }

        // Beams: detect external combat + track shooter location & laser cooldown
        for (const auto& bj : obs["beams"].arr_val) {
            int by = bj["by"].as_int(-1);
            if (by < 0 || by == self.id) continue;
            double age = bj["age"].as_double(0.0);
            const std::string& bkind = bj["kind"].as_str();
            const auto& path = bj["path"].arr_val;
            if (!path.empty() && path[0].arr_val.size() >= 3) {
                Vec3 orig(path[0][0].as_double(), path[0][1].as_double(), path[0][2].as_double());
                auto it = actors.find(by);
                if (it == actors.end() || !it->second.in_obs_now) {
                    TrackedActor& a = actors[by];
                    a.id = by;
                    a.is_mech = true;
                    a.pos = {orig.x, orig.y, orig.z - cfg.muzzle_height};
                    a.last_obs_t = t;
                    a.last_seen_t = t;
                }
                if (bkind == "laser") {
                    actors[by].last_laser_fire_t = std::max(actors[by].last_laser_fire_t, t - age);
                }
                if (path.size() >= 2 && path.back().arr_val.size() >= 3) {
                    Vec3 endp(path.back()[0].as_double(), path.back()[1].as_double(), path.back()[2].as_double());
                    double d_to_us = (endp - self.center_pos()).len();
                    if (d_to_us > 14.0) {
                        saw_external_combat = true;
                    }
                }
            }
        }

        // Detect squad cooperation (2+ visible mechs near each other not fighting)
        if (!saw_external_combat) {
            std::vector<const TrackedActor*> near_mechs;
            for (const auto& kv : actors) {
                if (kv.second.is_mech && kv.second.in_obs_now && (kv.second.pos - self.pos).len() < 165.0) {
                    near_mechs.push_back(&kv.second);
                }
            }
            bool coop_pair = false;
            for (size_t i = 0; i < near_mechs.size() && !coop_pair; ++i) {
                for (size_t j = i + 1; j < near_mechs.size(); ++j) {
                    if ((near_mechs[i]->pos - near_mechs[j]->pos).len() < 65.0 &&
                        world.has_solid_los(near_mechs[i]->center_pos(cfg), near_mechs[j]->center_pos(cfg))) {
                        coop_pair = true;
                        break;
                    }
                }
            }
            if (coop_pair) squad_coop_score += dt;
        }

        // FFA vs Practice 1v15 confidence estimate
        int non_me_dead = std::max(0, (cfg.mechs - alive) - my_kills);
        if (saw_external_combat || (non_me_dead >= 1 && t < 110.0)) {
            ffa_confidence = 1.0;
        } else if (squad_coop_score >= 1.5 && non_me_dead == 0) {
            ffa_confidence = 0.0;
        } else if (t > 40.0) {
            ffa_confidence = 0.0;
        } else if (t > 20.0) {
            ffa_confidence = clamp_val(1.0 - (t - 20.0) / 20.0, 0.0, 0.6);
        } else {
            ffa_confidence = 0.5;
        }

        // Update remembered crates, cubes, pickups
        update_items(crates, obs["crates"], self, cfg, world, true);
        update_items(cubes, obs["cubes"], self, cfg, world, false);
        update_items(pickups, obs["pickups"], self, cfg, world, false);

        // Projectiles & predicted mortar impacts
        projectiles.clear();
        for (const auto& pj : obs["projectiles"].arr_val) {
            ProjectileThreat pr;
            pr.id = pj["id"].as_int(-1);
            pr.kind = pj["kind"].as_str("gun");
            const auto& p = pj["pos"].arr_val;
            const auto& v = pj["vel"].arr_val;
            if (p.size() >= 3) pr.pos = {p[0].as_double(), p[1].as_double(), p[2].as_double()};
            if (v.size() >= 3) pr.vel = {v[0].as_double(), v[1].as_double(), v[2].as_double()};
            if (pr.kind == "mortar") {
                predict_mortar_impact(pr, cfg.mortar.gravity, world);
            }
            projectiles.push_back(pr);
        }

        // Sounds
        sounds.erase(std::remove_if(sounds.begin(), sounds.end(),
                                    [&](const SoundContact& s) { return (t - s.time) > 4.0; }),
                     sounds.end());
        for (const auto& sj : obs["sounds"].arr_val) {
            SoundContact sc;
            sc.kind = sj["kind"].as_str();
            sc.bearing = sj["bearing"].as_double(0.0);
            const std::string& dist_s = sj["dist"].as_str("mid");
            if (dist_s == "near") sc.est_dist = 0.58 * cfg.sound_near;
            else if (dist_s == "mid") sc.est_dist = 0.5 * (cfg.sound_near + cfg.sound_mid);
            else sc.est_dist = cfg.sound_mid + 55.0;
            sc.time = t - sj["age"].as_double(0.0);
            sc.est_pos = {self.pos.x + std::cos(sc.bearing) * sc.est_dist,
                          self.pos.y + std::sin(sc.bearing) * sc.est_dist};
            sounds.push_back(sc);
        }
    }

    int count_enemies_with_los(const SelfState& self, const GameConfig& cfg, const World& world) const {
        Vec3 my_c = self.center_pos();
        Vec3 my_top(self.pos.x, self.pos.y, self.pos.z + 0.80 * self.height);
        int cnt = 0;
        for (const auto& kv : actors) {
            const TrackedActor& a = kv.second;
            if (!a.is_mech || !a.in_obs_now) continue;
            Vec3 e_muz(a.pos.x, a.pos.y, a.pos.z + cfg.muzzle_height * (1.0 + cfg.size_per_cube * a.cubes));
            if ((a.pos - self.pos).len() <= 245.0 &&
                (world.has_solid_los(e_muz, my_c) || world.has_solid_los(e_muz, my_top))) {
                ++cnt;
            }
        }
        return cnt;
    }

    bool enemy_within(const Vec3& p, double dist_limit) const {
        for (const auto& kv : actors) {
            const TrackedActor& a = kv.second;
            if (!a.is_mech) continue;
            if ((t - a.last_obs_t) <= 3.0 && (a.pos - p).len() <= dist_limit) return true;
        }
        return false;
    }

private:
    void update_items(
        std::unordered_map<int, RememberedItem>& store,
        const Json& arr,
        const SelfState& self,
        const GameConfig& cfg,
        const World& world,
        bool has_hp
    ) {
        for (auto& kv : store) kv.second.visible_now = false;
        for (const auto& it : arr.arr_val) {
            int id = it["id"].as_int(-1);
            if (id < 0) continue;
            RememberedItem& r = store[id];
            r.id = id;
            if (it.has("kind")) r.kind = it["kind"].as_str();
            const auto& p = it["pos"].arr_val;
            if (p.size() >= 3) {
                r.pos = {p[0].as_double(), p[1].as_double(), p[2].as_double()};
                r.on_roof = (r.pos.z > world.terrain_height(r.pos.x, r.pos.y) + 2.2);
            }
            if (has_hp) r.hp = it["hp"].as_double(cfg.crate_hp);
            r.last_seen_t = t;
            r.visible_now = true;
        }

        double near_r = cfg.vision_near_range + self.near_range_bonus;
        double fov_r = cfg.vision_range + self.vision_bonus;
        Vec3 eye = self.eye_pos();

        for (auto it = store.begin(); it != store.end();) {
            RememberedItem& r = it->second;
            if (r.visible_now) {
                ++it;
                continue;
            }
            if ((t - r.last_seen_t) > 25.0) {
                it = store.erase(it);
                continue;
            }
            // If we should be able to see where it was, and it's not in obs, it was taken/destroyed
            Vec3 top = {r.pos.x, r.pos.y, r.pos.z + (has_hp ? cfg.crate_height : 1.0)};
            if ((r.pos - self.pos).len() < fov_r * 0.75 &&
                world.can_see_point(eye, r.pos, top, near_r * 0.9, fov_r * 0.75, self.aim_yaw, cfg.vision_fov_deg * 0.85, false)) {
                it = store.erase(it);
                continue;
            }
            ++it;
        }
    }

    static void predict_mortar_impact(ProjectileThreat& pr, double g, const World& world) {
        Vec3 p = pr.pos;
        Vec3 v = pr.vel;
        const double step_dt = 0.05;
        for (int k = 0; k < 100; ++k) {
            Vec3 next_v = {v.x, v.y, v.z - g * step_dt};
            Vec3 next_p = p + (v + next_v) * (0.5 * step_dt);
            Vec3 seg = next_p - p;
            double slen = seg.len();
            if (slen > 1e-4) {
                double ht = 0.0;
                if (world.raycast_solid(p, seg / slen, slen, &ht)) {
                    pr.impact_pos = p + (seg / slen) * ht;
                    pr.impact_t = k * step_dt + (ht / slen) * step_dt;
                    pr.has_impact = true;
                    return;
                }
            }
            if (next_p.z <= world.terrain_height(next_p.x, next_p.y)) {
                pr.impact_pos = next_p;
                pr.impact_t = (k + 1) * step_dt;
                pr.has_impact = true;
                return;
            }
            p = next_p;
            v = next_v;
        }
    }
};

} // namespace mf
