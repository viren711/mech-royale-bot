#pragma once

#include "combat.hpp"
#include "config.hpp"
#include "math3d.hpp"
#include "tracker.hpp"
#include "world.hpp"
#include <algorithm>
#include <cmath>
#include <unordered_map>
#include <vector>

namespace mf {

enum class StrategicMode {
    ZoneRotate,
    RegenCover,
    SupplyDrop,
    LootWeapon,
    FarmCubes,
    RoofControl,
    CombatEngage
};

struct MoveDecision {
    Vec2 move = {0.0, 0.0};
    bool boost = false;
    bool jump = false;
    StrategicMode mode = StrategicMode::CombatEngage;
    Vec2 goal = {0.0, 0.0};
};

class MovementPlanner {
public:
    // Cached A* path & cover
    std::vector<Vec2> cached_path;
    Vec2 cached_goal = {1e9, 1e9};
    double last_path_t = -999.0;

    Vec2 cached_cover = {0, 0};
    bool has_cached_cover = false;
    double last_cover_t = -999.0;

    // Rooftop climb target
    bool climbing_roof = false;
    RoofSpot climb_target;
    double climb_start_t = -999.0;

    // Mode memory, persistent explorer & unreachable roof blacklist
    StrategicMode last_mode = StrategicMode::CombatEngage;
    std::unordered_map<int, double> blacklisted_roofs;
    bool in_regen_hyst = false;

    Vec2 explore_goal = {0.0, 0.0};
    bool has_explore_goal = false;
    double explore_set_t = -999.0;
    int explore_idx = 0;

    // Stateful strafe & anti-stuck tracker
    double strafe_sign = 1.0;
    double next_strafe_flip_t = 1.3;
    Vec3 stuck_ref_pos;
    double stuck_ref_t = -999.0;
    double stuck_escape_until = -999.0;
    double stuck_escape_yaw = 0.0;
    int stuck_count = 0;

    bool suppress_blind_precharge() const {
        return climbing_roof ||
               last_mode == StrategicMode::ZoneRotate ||
               last_mode == StrategicMode::RegenCover ||
               last_mode == StrategicMode::SupplyDrop ||
               last_mode == StrategicMode::LootWeapon;
    }

    void reset() {
        cached_path.clear();
        cached_goal = {1e9, 1e9};
        last_path_t = -999.0;
        has_cached_cover = false;
        last_cover_t = -999.0;
        climbing_roof = false;
        last_mode = StrategicMode::CombatEngage;
        blacklisted_roofs.clear();
        in_regen_hyst = false;
        has_explore_goal = false;
        explore_set_t = -999.0;
        explore_idx = 0;
        strafe_sign = 1.0;
        next_strafe_flip_t = 1.3;
        stuck_ref_t = -999.0;
        stuck_escape_until = -999.0;
        stuck_count = 0;
    }

    MoveDecision decide(
        const SelfState& self,
        const Tracker& tracker,
        const CombatDecision& combat,
        const GameConfig& cfg,
        const World& world
    ) {
        MoveDecision out;
        double t = tracker.t;
        Vec2 my_xy = self.pos.xy();

        // Stateful strafe flip (1.15 - 1.50s so we actually accelerate to full 11.7 m/s lateral speed!)
        if (t >= next_strafe_flip_t) {
            strafe_sign = -strafe_sign;
            next_strafe_flip_t = t + 1.15 + 0.12 * ((self.id + static_cast<int>(t)) % 4);
        }

        // Anti-stuck tracking
        if (stuck_ref_t < 0.0) {
            stuck_ref_pos = self.pos;
            stuck_ref_t = t;
        } else if ((t - stuck_ref_t) >= 1.0) {
            double moved = (self.pos.xy() - stuck_ref_pos.xy()).len();
            if (moved < 1.3 && self.vel.xy().len() < 3.0) {
                ++stuck_count;
                stuck_escape_until = t + 0.85;
                stuck_escape_yaw = wrap_angle(self.aim_yaw + (stuck_count % 2 == 0 ? 1.7 : -1.7));
                cached_path.clear();
                if (climbing_roof) {
                    blacklisted_roofs[climb_target.prism_id] = t + 35.0;
                }
                climbing_roof = false;
            }
            stuck_ref_pos = self.pos;
            stuck_ref_t = t;
        }

        // Current zone target & urgency
        double dist_to_next = (my_xy - tracker.zone.next_center).len();
        double safe_next_r = std::max(5.0, tracker.zone.next_radius - 14.0);
        double time_to_shrink_end = std::max(1.0, tracker.zone.shrink_end - t);
        double req_speed = std::max(0.0, dist_to_next - safe_next_r) / time_to_shrink_end;
        bool zone_urgent = !self.in_zone ||
                           ((my_xy - tracker.zone.center).len() > std::max(4.0, tracker.zone.radius - 14.0)) ||
                           (dist_to_next > safe_next_r &&
                            (t >= tracker.zone.shrink_start - 10.0 || req_speed > 0.55 * self.walk_speed));

        // 1. Check active rooftop climb completion / abort
        if (climbing_roof) {
            double r_dist = (my_xy - climb_target.roof_pos.xy()).len();
            bool climb_timeout = ((t - climb_start_t) > 7.5);
            if (self.grounded && self.pos.z >= climb_target.roof_pos.z - 0.6 && r_dist < 14.0) {
                climbing_roof = false;
            } else if (climb_timeout || self.energy < 6.0 || zone_urgent) {
                if (climb_timeout || self.energy < 6.0) {
                    blacklisted_roofs[climb_target.prism_id] = t + 35.0;
                }
                climbing_roof = false;
            }
        }

        // Gather visible/recent enemy threats
        std::vector<const TrackedActor*> active_mechs;
        std::vector<Vec3> threat_positions;
        const TrackedActor* primary = nullptr;
        for (const auto& kv : tracker.actors) {
            const TrackedActor& a = kv.second;
            if (!a.is_mech) continue;
            if (a.in_obs_now || (t - a.last_obs_t) < 4.0) {
                active_mechs.push_back(&a);
                threat_positions.push_back(a.pos);
                if (a.id == combat.primary_target_id) primary = &a;
            }
        }

        int los_enemies = tracker.count_enemies_with_los(self, cfg, world);
        double regen_enter_hp = (tracker.ffa_confidence > 0.5 || active_mechs.size() >= 2)
                                    ? 0.65 * self.max_hp
                                    : 0.52 * self.max_hp;
        bool base_need_regen = (self.hp < regen_enter_hp) &&
                               (!active_mechs.empty() || (t - tracker.last_combat_t) < self.regen_delay + 2.5);
        if (tracker.ffa_confidence < 0.55) {
            if (base_need_regen && los_enemies == 0 && (t - tracker.last_combat_t) >= 2.2) {
                in_regen_hyst = true;
            }
            if (self.hp >= 0.84 * self.max_hp || los_enemies > 0 || active_mechs.empty() ||
                (t - tracker.last_combat_t) < 1.5) {
                in_regen_hyst = false;
            }
        } else {
            in_regen_hyst = false;
        }
        bool need_regen = base_need_regen || in_regen_hyst;

        bool on_roof = false;
        double cur_roof_z = 0.0;
        int cur_roof_pid = -1;
        on_roof = world.get_roof_at(self.pos.x, self.pos.y, cur_roof_z, cur_roof_pid) &&
                  (self.pos.z >= cur_roof_z - 1.5);

        // Pre-scan Supply Drops, Desired Weapon Pickups, and Nearby Cubes
        const DropInfo* best_drop = nullptr;
        double best_drop_sc = -1e9;
        for (const auto& d : tracker.drops) {
            double dist = (d.pos.xy() - my_xy).len();
            double eta = dist / std::max(1.0, self.walk_speed);
            if (d.lands_in > eta + 14.0) continue;
            if (dist > 230.0 && d.lands_in <= 0.0) continue;
            if ((d.pos.xy() - tracker.zone.next_center).len() > tracker.zone.next_radius + 10.0) continue;
            if (los_enemies >= 2 && (d.holder != self.id || d.progress < 0.65)) continue;
            double sc = 200.0 - dist - d.lands_in * 4.0;
            if (d.holder == self.id) sc += 300.0;
            if (sc > best_drop_sc) {
                best_drop_sc = sc;
                best_drop = &d;
            }
        }

        const RememberedItem* best_pickup = nullptr;
        double best_pick_sc = -1e9;
        bool need_laser = (self.find_weapon("laser") < 0);
        bool need_sec = (self.find_weapon(combat.preferred_secondary) < 0);
        if (need_laser || need_sec) {
            for (const auto& kv : tracker.pickups) {
                const RememberedItem& pk = kv.second;
                if (self.find_weapon(pk.kind) >= 0) continue;
                if (pk.kind == "mortar") continue;
                if (pk.kind != "laser" && pk.kind != combat.preferred_secondary && !need_sec) continue;
                if (std::abs(pk.pos.z - self.pos.z) > 4.5 && !on_roof) continue;
                double d = (pk.pos.xy() - my_xy).len();
                if (d > 160.0) continue;
                if ((pk.pos.xy() - tracker.zone.next_center).len() > tracker.zone.next_radius + 5.0) continue;
                double sc = (pk.kind == "laser" ? 260.0 : 180.0) - d;
                if (sc > best_pick_sc) {
                    best_pick_sc = sc;
                    best_pickup = &pk;
                }
            }
        }

        const RememberedItem* best_cube = nullptr;
        double best_cube_d = 1e9;
        double max_cube_seek = (self.cubes >= 21) ? 14.0 : 95.0;
        for (const auto& kv : tracker.cubes) {
            if (std::abs(kv.second.pos.z - self.pos.z) > 4.5 && !on_roof) continue;
            double d = (kv.second.pos.xy() - my_xy).len();
            if (d < max_cube_seek && d < best_cube_d) {
                best_cube_d = d;
                best_cube = &kv.second;
            }
        }
        bool safe_cube_grab = best_cube &&
            (best_cube_d < 22.0 || (!tracker.enemy_within(best_cube->pos, 32.0) && best_cube_d < (active_mechs.empty() ? max_cube_seek : 48.0)));

        // Persistent golden-angle explorer helper (replaces 61 m/s spinning orbit!)
        auto get_explore_goal = [&]() -> Vec2 {
            double safe_r = std::max(10.0, tracker.zone.next_radius - 18.0);
            if (!has_explore_goal ||
                (my_xy - explore_goal).len() < 24.0 ||
                (t - explore_set_t) > 13.0 ||
                (explore_goal - tracker.zone.next_center).len() > safe_r) {
                for (int tries = 0; tries < 6; ++tries) {
                    ++explore_idx;
                    double ang = self.id * 1.13 + explore_idx * 2.39996323;
                    double frac = (explore_idx % 2 == 0) ? 0.68 : 0.34;
                    double r = std::min(safe_r, std::min(tracker.zone.next_radius * frac, 195.0));
                    Vec2 cand = tracker.zone.next_center + Vec2(std::cos(ang), std::sin(ang)) * r;
                    int nidx = world.find_nearest_walkable_cell(cand.x, cand.y, self.radius, self.height);
                    if (nidx >= 0) {
                        Vec2 nw = world.nav_to_world(nidx % world.nav_nx, nidx / world.nav_nx);
                        if ((nw - my_xy).len() > 40.0 || tries == 5) {
                            explore_goal = nw;
                            has_explore_goal = true;
                            explore_set_t = t;
                            break;
                        }
                    }
                }
                if (!has_explore_goal) {
                    explore_goal = tracker.zone.next_center;
                    has_explore_goal = true;
                    explore_set_t = t;
                }
            }
            return explore_goal;
        };

        // Select strategic goal
        Vec2 goal = tracker.zone.next_center;
        StrategicMode mode = StrategicMode::CombatEngage;
        bool want_boost = false;
        bool want_jump = false;
        bool standing_capture = false;

        if (zone_urgent) {
            mode = StrategicMode::ZoneRotate;
            goal = clamp_to_zone(my_xy, tracker.zone.next_center, std::max(4.0, tracker.zone.next_radius * 0.72));
            want_boost = (!self.in_zone || req_speed > 0.75 * self.walk_speed) && (self.energy > 15.0);
        } else if (need_regen && !threat_positions.empty()) {
            mode = StrategicMode::RegenCover;
            if (!has_cached_cover || (t - last_cover_t) > 0.65 || (cached_cover - tracker.zone.next_center).len() > tracker.zone.next_radius - 6.0) {
                Vec2 cover_pt;
                if (world.find_cover_pos(self.pos, threat_positions, tracker.zone.next_center, tracker.zone.next_radius, 52.0, cover_pt)) {
                    cached_cover = cover_pt;
                    has_cached_cover = true;
                    last_cover_t = t;
                } else {
                    has_cached_cover = false;
                }
            }
            if (has_cached_cover) {
                goal = cached_cover;
            } else {
                Vec2 away = compute_away_vec(my_xy, threat_positions);
                goal = clamp_to_zone(my_xy + away * 35.0, tracker.zone.next_center, std::max(5.0, tracker.zone.next_radius - 10.0));
            }
            want_boost = (los_enemies > 0 && self.energy > 28.0);
        } else {
            if (best_drop && (best_drop->holder == self.id || best_drop_sc > 80.0)) {
                mode = StrategicMode::SupplyDrop;
                goal = best_drop->pos.xy();
                double d_drop = (goal - my_xy).len();
                bool safe_stand = (los_enemies == 0) ||
                                  (los_enemies == 1 && self.hp >= 0.60 * self.max_hp && best_drop->progress > 0.30);
                if (best_drop->lands_in <= 0.1 && d_drop <= best_drop->radius - 1.6 && safe_stand) {
                    standing_capture = true;
                } else if (best_drop->lands_in < 5.0 && d_drop > best_drop->radius &&
                           self.energy > 35.0 && los_enemies == 0) {
                    want_boost = true;
                }
            } else if (best_pickup && (need_laser || best_pick_sc > 60.0)) {
                mode = StrategicMode::LootWeapon;
                goal = best_pickup->pos.xy();
                if (need_laser && (goal - my_xy).len() > 16.0 && self.energy > 38.0 && los_enemies == 0) {
                    want_boost = true;
                }
            } else if (safe_cube_grab) {
                mode = StrategicMode::FarmCubes;
                goal = best_cube->pos.xy();
            } else if (primary != nullptr) {
                mode = StrategicMode::CombatEngage;
                double dist_p = (primary->pos.xy() - my_xy).len();
                bool has_laser = (self.find_weapon("laser") >= 0);
                bool has_light = (self.find_weapon("lightning") >= 0);
                bool charging_laser = (has_laser && self.weapons[self.find_weapon("laser")].charge > 0.0);

                if (!has_laser && (los_enemies >= 2 || primary->has_weapon("laser") || self.hp < 0.78 * self.max_hp)) {
                    if (los_enemies == 0 && !tracker.enemy_within(self.pos, 48.0)) {
                        // Already broke LOS without a laser: actively roam to find a laser instead of freezing!
                        mode = StrategicMode::LootWeapon;
                        goal = get_explore_goal();
                        if (self.energy > 45.0) want_boost = true;
                    } else {
                        if (!has_cached_cover || (t - last_cover_t) > 0.75) {
                            Vec2 cover_pt;
                            if (world.find_cover_pos(self.pos, threat_positions, tracker.zone.next_center, tracker.zone.next_radius, 42.0, cover_pt)) {
                                cached_cover = cover_pt;
                                has_cached_cover = true;
                                last_cover_t = t;
                            } else {
                                has_cached_cover = false;
                            }
                        }
                        if (has_cached_cover) {
                            goal = cached_cover;
                        } else {
                            Vec2 away = (my_xy - primary->pos.xy()).normalized();
                            goal = clamp_to_zone(my_xy + away * 28.0, tracker.zone.next_center, std::max(5.0, tracker.zone.next_radius - 10.0));
                        }
                    }
                } else if (combat.laser_cooling && !charging_laser && los_enemies > 0) {
                    if (!has_cached_cover || (t - last_cover_t) > 0.7) {
                        Vec2 cover_pt;
                        if (world.find_cover_pos(self.pos, threat_positions, tracker.zone.next_center, tracker.zone.next_radius, 34.0, cover_pt)) {
                            cached_cover = cover_pt;
                            has_cached_cover = true;
                            last_cover_t = t;
                        } else {
                            has_cached_cover = false;
                        }
                    }
                    if (has_cached_cover) {
                        goal = cached_cover;
                    } else {
                        Vec2 away = (my_xy - primary->pos.xy()).normalized();
                        goal = clamp_to_zone(my_xy + away * 25.0, tracker.zone.next_center, std::max(5.0, tracker.zone.next_radius - 10.0));
                    }
                } else if (combat.want_peek_for_laser) {
                    Vec2 to_t = (primary->pos.xy() - my_xy).normalized();
                    Vec2 side(-to_t.y, to_t.x);
                    side = side * strafe_sign;
                    goal = clamp_to_zone(my_xy + to_t * 12.0 + side * 14.0, tracker.zone.next_center, std::max(5.0, tracker.zone.next_radius - 10.0));
                } else {
                    double ideal_dist = 75.0;
                    if (has_light && !has_laser) ideal_dist = 32.0;
                    else if (has_light && primary->hp < 320.0) ideal_dist = 34.0;
                    else if (has_laser && !combat.laser_cooling) ideal_dist = 105.0;
                    else if (combat.laser_cooling) ideal_dist = 135.0;

                    Vec2 to_t = (primary->pos.xy() - my_xy).normalized();
                    Vec2 tangent(-to_t.y, to_t.x);
                    Vec2 test_st = my_xy + tangent * (strafe_sign * 8.0);
                    if (self.grounded && world.is_wall_blocked(test_st.x, test_st.y, self.pos.z, self.radius + 0.3, self.height, self.step_up)) {
                        strafe_sign = -strafe_sign;
                        next_strafe_flip_t = t + 1.15;
                    }
                    tangent = tangent * strafe_sign;
                    double rad_err = dist_p - ideal_dist;
                    Vec2 radial = to_t * clamp_val(rad_err * 0.5, -16.0, 16.0);
                    goal = clamp_to_zone(my_xy + radial + tangent * 20.0, tracker.zone.next_center, std::max(5.0, tracker.zone.next_radius - 12.0));
                }

                if (los_enemies >= 2 && self.energy > 35.0) want_boost = true;
            } else {
                // No active enemy right now: farm crates/NPCs early, take a roof inside next_zone, or explore!
                bool farm_wanted = (self.cubes < 21 || need_laser || need_sec);
                const RememberedItem* farm_crate = nullptr;
                double farm_crate_d = 1e9;
                if (farm_wanted) {
                    for (const auto& kv : tracker.crates) {
                        if (std::abs(kv.second.pos.z - self.pos.z) > 4.5 && !on_roof) continue;
                        if ((kv.second.pos.xy() - tracker.zone.next_center).len() >= tracker.zone.next_radius) continue;
                        double d = (kv.second.pos.xy() - my_xy).len();
                        if (d < 150.0 && d < farm_crate_d) {
                            farm_crate_d = d;
                            farm_crate = &kv.second;
                        }
                    }
                }

                if (climbing_roof) {
                    mode = StrategicMode::RoofControl;
                    goal = execute_roof_climb(self, want_boost, want_jump);
                } else if (farm_crate && farm_crate_d < 110.0 && self.hp >= 0.65 * self.max_hp) {
                    mode = StrategicMode::FarmCubes;
                    goal = farm_crate->pos.xy();
                } else if (!need_laser && !on_roof && self.energy >= 78.0 && self.grounded && find_good_roof(self, tracker, world, climb_target)) {
                    climbing_roof = true;
                    climb_start_t = t;
                    mode = StrategicMode::RoofControl;
                    goal = execute_roof_climb(self, want_boost, want_jump);
                } else if (need_laser || tracker.ffa_confidence < 0.45) {
                    // Explore actively for weapons or move toward loudest recent sound
                    mode = need_laser ? StrategicMode::LootWeapon : StrategicMode::CombatEngage;
                    double best_snd_sc = -1e9;
                    bool has_snd = false;
                    Vec2 snd_pt = tracker.zone.next_center;
                    if (!need_laser) {
                        for (const auto& sc : tracker.sounds) {
                            double age = t - sc.time;
                            if (age > 3.5) continue;
                            double w = 100.0 - age * 25.0 - sc.est_dist * 0.25;
                            if (w > best_snd_sc) {
                                best_snd_sc = w;
                                snd_pt = sc.est_pos;
                                has_snd = true;
                            }
                        }
                    }
                    if (has_snd) {
                        goal = clamp_to_zone(snd_pt, tracker.zone.next_center, std::max(8.0, tracker.zone.next_radius - 12.0));
                    } else {
                        goal = get_explore_goal();
                        if (need_laser && self.energy > 45.0 && los_enemies == 0) want_boost = true;
                    }
                } else {
                    mode = on_roof ? StrategicMode::RoofControl : StrategicMode::CombatEngage;
                    double hold_r = std::min(tracker.zone.next_radius * 0.55, 110.0);
                    double ang = t * 0.08 + self.id * 0.7;
                    goal = tracker.zone.next_center + Vec2(std::cos(ang), std::sin(ang)) * hold_r;
                    if (on_roof && (my_xy - goal).len() < 40.0) {
                        goal = my_xy;
                    }
                }
            }
        }

        out.mode = mode;
        out.goal = goal;
        last_mode = mode;

        if (on_roof && !climbing_roof && (goal - my_xy).len() < 3.0) {
            goal = my_xy;
        }

        // Compute A* path to goal
        Vec2 steer_target = goal;
        bool use_astar = !climbing_roof && !on_roof;
        if (use_astar && (goal - my_xy).len() > 8.0 &&
            !world.is_nav_line_walkable(my_xy, goal, self.radius, self.height)) {
            if (cached_path.empty() || ((goal - cached_goal).len() > 24.0 && (t - last_path_t) > 0.45) || (t - last_path_t) > 1.4) {
                int max_exp = (mode == StrategicMode::ZoneRotate) ? 9000 : 4500;
                cached_path = world.find_path(my_xy, goal, max_exp, self.radius, self.height);
                cached_goal = goal;
                last_path_t = t;
            }
            while (cached_path.size() > 1 && (cached_path[0] - my_xy).len() < 6.5) {
                cached_path.erase(cached_path.begin());
            }
            if (!cached_path.empty()) steer_target = cached_path[0];
        }

        // Supply drop ring standstill (still dodge bullets/mortars!)
        if (standing_capture) {
            steer_target = my_xy;
        }

        // Timed laser dodge trigger (when enemy laser is about to fire & sees us)
        // Stay grounded during laser dodge to preserve 58.5 m/s^2 ground acceleration & level aim pitch!
        bool urgent_laser_dodge = false;
        for (const auto* m : active_mechs) {
            if (!m->charging) continue;
            double ch_elapsed = (m->charge_start_t > 0.0) ? (t - m->charge_start_t) : 0.35;
            if (ch_elapsed >= 0.48 && (m->pos - self.pos).len() < cfg.laser.range) {
                Vec3 m_orig(m->pos.x, m->pos.y, m->pos.z + cfg.muzzle_height);
                if (world.has_solid_los(m_orig, self.center_pos())) {
                    urgent_laser_dodge = true;
                    break;
                }
            }
        }
        if (urgent_laser_dodge && !standing_capture && self.energy > 28.0) {
            want_boost = true;
        }

        // 24-direction tactical candidate evaluator
        Vec2 best_dir = evaluate_24_directions(
            self, tracker, combat, cfg, world,
            steer_target, active_mechs, on_roof, climbing_roof,
            standing_capture ? 4.0 : 1e9, goal, want_boost
        );

        if (t < stuck_escape_until && !standing_capture) {
            best_dir = {std::cos(stuck_escape_yaw), std::sin(stuck_escape_yaw)};
            if (self.grounded && (stuck_count % 2 == 1)) want_jump = true;
        }

        // Jump slightly when stepping up terrain or dodging mortar
        if (self.grounded && !standing_capture && best_dir.len() > 0.3) {
            Vec2 ahead = my_xy + best_dir * 3.0;
            double dz = world.support_height(ahead.x, ahead.y, self.pos.z, self.step_up) - self.pos.z;
            if (dz > self.step_up * 0.85 && dz <= 4.5 && self.energy > 30.0) {
                want_jump = true;
            }
        }

        // Prevent accidental midair jetpack launches when not climbing a roof or escaping outside the zone
        if (!self.grounded && !climbing_roof && self.in_zone && mode != StrategicMode::ZoneRotate) {
            want_boost = false;
        }

        out.move = best_dir;
        out.boost = want_boost;
        out.jump = want_jump;
        return out;
    }

private:
    static Vec2 clamp_to_zone(const Vec2& pt, const Vec2& center, double radius) {
        Vec2 d = pt - center;
        double l = d.len();
        if (l <= radius || l < 1e-6) return pt;
        return center + d * (radius / l);
    }

    static Vec2 compute_away_vec(const Vec2& my_xy, const std::vector<Vec3>& threats) {
        Vec2 sum(0.0, 0.0);
        for (const Vec3& th : threats) {
            Vec2 d = my_xy - th.xy();
            double l = std::max(5.0, d.len());
            sum += d * (1.0 / (l * l));
        }
        return sum.len() > 1e-9 ? sum.normalized() : Vec2(1.0, 0.0);
    }

    bool find_good_roof(
        const SelfState& self,
        const Tracker& tracker,
        const World& world,
        RoofSpot& out_spot
    ) const {
        double best_sc = -1e9;
        bool found = false;
        for (const RoofSpot& rs : world.roof_spots) {
            auto bit = blacklisted_roofs.find(rs.prism_id);
            if (bit != blacklisted_roofs.end() && tracker.t < bit->second) continue;
            if (rs.climb_dz > 40.0 || rs.climb_dz < 6.0) continue;
            double d = (rs.approach_pos.xy() - self.pos.xy()).len();
            if (d > 80.0) continue;
            double dz_center = (rs.roof_pos.xy() - tracker.zone.next_center).len();
            if (dz_center > std::max(6.0, tracker.zone.next_radius - 16.0)) continue;
            // Energy budget check: ~dz/10s * jet_drain + margin
            double req_energy = (rs.climb_dz / 9.0) * self.jet_drain + 18.0;
            if (req_energy > self.energy) continue;
            double sc = 100.0 - d - std::abs(rs.climb_dz - 14.0) * 1.5;
            if (sc > best_sc) {
                best_sc = sc;
                out_spot = rs;
                found = true;
            }
        }
        return found;
    }

    Vec2 execute_roof_climb(const SelfState& self, bool& out_boost, bool& out_jump) const {
        double d_app = (self.pos.xy() - climb_target.approach_pos.xy()).len();
        double d_roof = (self.pos.xy() - climb_target.roof_pos.xy()).len();
        if (self.pos.z < climb_target.roof_pos.z + 0.4) {
            if (d_app > 7.0 && self.grounded) {
                return climb_target.approach_pos.xy();
            }
            if (self.grounded) out_jump = true;
            if (self.energy > 8.0) out_boost = true;
            if (self.pos.z >= climb_target.roof_pos.z - 0.8 || d_roof < 18.0) {
                return climb_target.roof_pos.xy();
            }
            return climb_target.approach_pos.xy();
        }
        return climb_target.roof_pos.xy();
    }

    Vec2 evaluate_24_directions(
        const SelfState& self,
        const Tracker& tracker,
        const CombatDecision& combat,
        const GameConfig& cfg,
        const World& world,
        const Vec2& steer_target,
        const std::vector<const TrackedActor*>& active_mechs,
        bool on_roof,
        bool climbing_roof,
        double max_anchor_dist,
        const Vec2& anchor_center,
        bool boosting
    ) const {
        Vec2 my_xy = self.pos.xy();
        Vec2 to_steer = steer_target - my_xy;
        double steer_dist = to_steer.len();
        Vec2 steer_dir = (steer_dist > 1e-4) ? (to_steer / steer_dist) : Vec2(0.0, 0.0);

        // If very close to goal and no incoming mortar/projectile/laser threat, can stand still
        bool incoming_threat = false;
        for (const auto& pr : tracker.projectiles) {
            if ((pr.pos.xy() - my_xy).len() < 45.0) {
                incoming_threat = true;
                break;
            }
        }
        for (const auto* m : active_mechs) {
            if (m->charging) {
                incoming_threat = true;
                break;
            }
        }
        if (!incoming_threat) {
            for (const auto& kv : tracker.actors) {
                if (!kv.second.is_mech && kv.second.in_obs_now && (kv.second.pos - self.pos).len() < 48.0) {
                    incoming_threat = true;
                    break;
                }
            }
        }
        if (steer_dist < 1.8 && !incoming_threat && !climbing_roof) {
            return {0.0, 0.0};
        }

        double speed = boosting ? self.boost_speed : self.walk_speed;
        double look_dt = 0.30;

        Vec2 best_dir(0.0, 0.0);
        double best_score = -1e18;

        // Test 24 directions + [0,0]
        for (int k = 0; k <= 24; ++k) {
            Vec2 dir(0.0, 0.0);
            if (k < 24) {
                double ang = (kPi * 2.0 * k) / 24.0;
                dir = {std::cos(ang), std::sin(ang)};
            }
            Vec2 cand = my_xy + dir * (speed * look_dt);

            if ((cand - anchor_center).len() > max_anchor_dist) continue;

            // Keep on roof if on_roof and not rotating out urgently
            if (on_roof && !climbing_roof) {
                double rz = 0.0;
                int rpid = -1;
                if (!world.get_roof_at(cand.x, cand.y, rz, rpid)) {
                    // Don't accidentally slide off roof edge unless zone forces us
                    if (self.in_zone && (my_xy - tracker.zone.next_center).len() < tracker.zone.next_radius - 10.0) {
                        continue;
                    }
                }
            }

            // Wall/slope collision check (skip when climbing in midair above walls)
            if (self.grounded && !climbing_roof) {
                if (world.is_wall_blocked(cand.x, cand.y, self.pos.z, self.radius + 0.15, self.height, self.step_up)) {
                    continue;
                }
                if (world.terr_nx > 1 && world.terrain_slope_deg(cand.x, cand.y) > self.max_slope_deg - 1.5) {
                    continue;
                }
            }

            double sc = 0.0;

            // 1. Progress toward A* waypoint
            if (steer_dist > 1.0) {
                sc += dir.dot(steer_dir) * 28.0;
            }

            // 2. Mortar splash evasion (highest survival priority!)
            for (const auto& pr : tracker.projectiles) {
                if (pr.kind == "mortar" && pr.has_impact) {
                    double d_imp = (cand - pr.impact_pos.xy()).len();
                    double danger_r = cfg.mortar.splash_radius + 6.0;
                    if (d_imp < danger_r) {
                        sc -= (danger_r - d_imp) * 35.0;
                    }
                } else {
                    // Bullet CPA over next 0.45s
                    Vec2 p0 = pr.pos.xy();
                    Vec2 v = pr.vel.xy();
                    double v2 = v.len_sq();
                    if (v2 > 1.0) {
                        double t_cpa = clamp_val((cand - p0).dot(v) / v2, 0.0, 0.45);
                        Vec2 closest = p0 + v * t_cpa;
                        double d_cpa = (cand - closest).len();
                        if (d_cpa < self.radius + 2.5) {
                            sc -= (self.radius + 2.5 - d_cpa) * 22.0;
                        }
                    }
                }
            }

            // 3. Charging laser beam ray perpendicular dodge + timed break LOS!
            for (const auto* m : active_mechs) {
                if (!m->charging) continue;
                Vec3 m_orig(m->pos.x, m->pos.y, m->pos.z + cfg.muzzle_height);
                Vec3 m_dir = vec_from_yaw_pitch(m->aim_yaw, m->aim_pitch);
                Vec3 cand_c(cand.x, cand.y, self.pos.z + 0.5 * self.height);
                Vec3 rel = cand_c - m_orig;
                double proj = rel.dot(m_dir);
                double ch_elapsed = (m->charge_start_t > 0.0) ? (tracker.t - m->charge_start_t) : 0.35;
                if (proj > 0.0 && proj < cfg.laser.range) {
                    double perp = (rel - m_dir * proj).len();
                    bool l_los = world.has_solid_los(m_orig, cand_c);
                    if (l_los && ch_elapsed >= 0.30) {
                        sc -= 58.0; // Huge bonus to any direction that breaks laser LOS!
                    }
                    if (perp < self.radius + 5.0 && l_los) {
                        sc -= (self.radius + 5.0 - perp) * (ch_elapsed >= 0.42 ? 42.0 : 28.0);
                    }
                }
            }

            // 4. Zone boundary safety
            double dz_cur = (cand - tracker.zone.center).len();
            if (dz_cur > tracker.zone.radius - 3.0) {
                sc -= (dz_cur - (tracker.zone.radius - 3.0)) * 25.0;
            }

            // 5. Multi-enemy LOS exposure, anti-pincer angular span & cover awareness (all 24 dirs!)
            if (!active_mechs.empty()) {
                Vec3 cand_c(cand.x, cand.y, self.pos.z + 0.5 * self.height);
                int vis_count = 0;
                bool sees_primary = false;
                double vis_bearings[16];
                for (const auto* m : active_mechs) {
                    if ((m->pos - self.pos).len() > 240.0) continue;
                    Vec3 m_eye(m->pos.x, m->pos.y, m->pos.z + cfg.eye_height);
                    if (world.has_solid_los(m_eye, cand_c)) {
                        if (vis_count < 16) {
                            vis_bearings[vis_count] = std::atan2(m->pos.y - cand.y, m->pos.x - cand.x);
                        }
                        ++vis_count;
                        if (m->id == combat.primary_target_id) sees_primary = true;
                    }
                }
                // Anti-pincer angular span penalty: never stand between enemies (>155 deg apart = rear armor guaranteed!)
                if (vis_count >= 2) {
                    double max_sep = 0.0;
                    int lim = std::min(vis_count, 16);
                    for (int i = 0; i < lim; ++i) {
                        for (int j = i + 1; j < lim; ++j) {
                            double sep = std::abs(angle_diff(vis_bearings[i], vis_bearings[j]));
                            if (sep > max_sep) max_sep = sep;
                        }
                    }
                    if (max_sep > deg_to_rad(155.0)) {
                        sc -= 46.0 * (max_sep - deg_to_rad(150.0));
                    }
                    // True 92-degree rear-arc exposure penalty relative to our current turret/aim yaw!
                    int rear_vis = 0;
                    for (int i = 0; i < lim; ++i) {
                        if (std::abs(angle_diff(vis_bearings[i], combat.aim_yaw)) > deg_to_rad(92.0)) {
                            ++rear_vis;
                        }
                    }
                    sc -= rear_vis * 24.0;
                }
                if (combat.laser_cooling || self.hp < 0.55 * self.max_hp) {
                    sc -= vis_count * 22.0;
                } else {
                    if (vis_count >= 2) sc -= (vis_count - 1) * 20.0;
                    if (combat.want_peek_for_laser && sees_primary) sc += 22.0;
                }
            }

            if (sc > best_score) {
                best_score = sc;
                best_dir = dir;
            }
        }

        // If all moving candidates blocked, try nudging toward nearest walkable cell
        if (best_score < -1e17 && world.nav_nx > 0) {
            int nidx = world.find_nearest_walkable_cell(self.pos.x, self.pos.y, self.radius, self.height);
            if (nidx >= 0) {
                Vec2 nw = world.nav_to_world(nidx % world.nav_nx, nidx / world.nav_nx);
                Vec2 d = nw - my_xy;
                if (d.len() > 0.1) return d.normalized();
            }
        }
        return best_dir;
    }
};

} // namespace mf
