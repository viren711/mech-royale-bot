#pragma once

#include "config.hpp"
#include "math3d.hpp"
#include "tracker.hpp"
#include "world.hpp"
#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

namespace mf {

struct CombatDecision {
    double aim_yaw = 0.0;
    double aim_pitch = 0.0;
    bool fire[2] = {false, false};
    bool reload = false;
    int pick_upgrade = -1;
    int take_pickup_id = -1;
    int drop_slot = -1;

    int primary_target_id = -1;
    bool engaging_mech = false;
    bool want_peek_for_laser = false;
    bool laser_cooling = false;
    std::string preferred_secondary = "lightning";
};

class CombatPlanner {
public:
    bool prefer_lightning_secondary = false;

    int choose_upgrade(
        const Json& offer,
        const SelfState& self,
        const Tracker& tracker,
        const GameConfig& /*cfg*/
    ) const {
        const auto& choices = offer["choices"].arr_val;
        if (choices.empty()) return -1;

        bool has_laser = (self.find_weapon("laser") >= 0);
        bool has_light = (self.find_weapon("lightning") >= 0);
        bool has_gun = (self.find_weapon("gun") >= 0);
        bool has_mortar = (self.find_weapon("mortar") >= 0);
        bool has_nanites = false;
        for (const auto& u : self.upgrades) {
            if (u == "nanites") { has_nanites = true; break; }
        }
        bool is_confirmed_ffa = (tracker.ffa_confidence > 0.55);

        int best_idx = 0;
        double best_score = -1e9;
        for (size_t i = 0; i < choices.size(); ++i) {
            const std::string& id = choices[i]["id"].as_str();
            double sc = 10.0;
            if (!is_confirmed_ffa) {
                // Practice 1v15 curve (Step 11 Test 5: armor & servos above gun upgrades!)
                if (id == "laser_damage") sc = has_laser ? 120.0 : 40.0;
                else if (id == "laser_charge") sc = has_laser ? 118.0 : 40.0;
                else if (id == "nanites") sc = 116.0;
                else if (id == "plating") sc = 112.0 + (self.hp < 0.7 * self.max_hp ? 10.0 : 0.0);
                else if (id == "armor") sc = 108.0;
                else if (id == "servos") sc = 104.0;
                else if (id == "gun_damage") sc = has_gun ? 96.0 : 15.0;
                else if (id == "gun_rate") sc = has_gun ? 94.0 : 15.0;
                else if (id == "gun_mag") sc = has_gun ? 86.0 : 15.0;
                else if (id == "gun_velocity") sc = has_gun ? 84.0 : 15.0;
                else if (id == "laser_pierce") sc = has_laser ? 82.0 : 20.0;
                else if (id == "sensors") sc = 72.0;
                else if (id == "reactor") sc = 64.0;
                else if (id == "jets") sc = 60.0;
                else if (id == "gyros") sc = 56.0;
                else if (id == "capacitor") sc = 48.0;
                else if (id.rfind("lightning_", 0) == 0) sc = has_light ? 75.0 : 20.0;
                else if (id.rfind("mortar_", 0) == 0) sc = has_mortar ? 12.0 : 5.0;
            } else {
                // Confirmed FFA / League curve (nanites first stack -> armor + laser burst)
                if (id == "nanites") sc = (!has_nanites) ? 126.0 : 115.0;
                else if (id == "laser_damage") sc = has_laser ? (has_nanites ? 120.0 : 106.0) : 40.0;
                else if (id == "laser_charge") sc = has_laser ? (has_nanites ? 118.0 : 103.0) : 40.0;
                else if (id == "armor") sc = 110.0;
                else if (id == "plating") sc = 98.0 + (self.hp < 0.7 * self.max_hp ? 12.0 : 0.0);
                else if (id == "servos") sc = 90.0;
                else if (id == "gun_damage") sc = has_gun ? 88.0 : 15.0;
                else if (id == "gun_rate") sc = has_gun ? 86.0 : 15.0;
                else if (id == "gun_mag") sc = has_gun ? 82.0 : 15.0;
                else if (id == "gun_velocity") sc = has_gun ? 80.0 : 15.0;
                else if (id == "reactor") sc = 72.0;
                else if (id == "jets") sc = 66.0;
                else if (id == "gyros") sc = 62.0;
                else if (id == "laser_pierce") sc = has_laser ? 62.0 : 20.0;
                else if (id == "sensors") sc = 58.0;
                else if (id == "capacitor") sc = 50.0;
                else if (id.rfind("lightning_", 0) == 0) sc = has_light ? 80.0 : 25.0;
                else if (id.rfind("mortar_", 0) == 0) sc = has_mortar ? 12.0 : 5.0;
            }
            if (sc > best_score) {
                best_score = sc;
                best_idx = static_cast<int>(i);
            }
        }
        return best_idx;
    }

    int weapon_desirability(const std::string& kind) const {
        if (kind == "laser") return 100;
        if (prefer_lightning_secondary) {
            if (kind == "lightning") return 80;
            if (kind == "gun") return 60;
            if (kind == "mortar") return 10;
        } else {
            if (kind == "gun") return 80;
            if (kind == "lightning") return 60;
            if (kind == "mortar") return 10;
        }
        return 0;
    }

    CombatDecision decide(
        const Json& obs,
        const SelfState& self,
        const Tracker& tracker,
        const GameConfig& cfg,
        const World& world,
        double scan_fallback_yaw,
        bool suppress_blind_precharge = false
    ) const {
        CombatDecision out;
        out.preferred_secondary = prefer_lightning_secondary ? "lightning" : "gun";
        out.aim_yaw = self.aim_yaw;
        out.aim_pitch = self.aim_pitch;

        if (!obs["offer"].is_null() && obs["offer"].is_object()) {
            out.pick_upgrade = choose_upgrade(obs["offer"], self, tracker, cfg);
        }

        int laser_slot = self.find_weapon("laser");
        int light_slot = self.find_weapon("lightning");
        int gun_slot = self.find_weapon("gun");
        int mortar_slot = self.find_weapon("mortar");

        // Weapon loot take/swap (strictly enforce protocol constraints)
        handle_weapon_loot(obs, self, cfg, out);

        // Drop mortar proactively if we have another weapon and an enemy with laser is visible
        if (mortar_slot >= 0 && (laser_slot >= 0 || gun_slot >= 0 || light_slot >= 0) &&
            out.take_pickup_id < 0 && !(self.weapons[mortar_slot].charge > 0.0)) {
            for (const auto& kv : tracker.actors) {
                if (kv.second.is_mech && kv.second.in_obs_now && kv.second.has_weapon("laser")) {
                    out.drop_slot = mortar_slot;
                    break;
                }
            }
        }

        double dmg_mult = self.damage_mult(cfg);
        double muzzle_offset = self.radius + 0.5;
        bool shorted = (tracker.t < tracker.shorted_until_t);

        if (laser_slot >= 0 && self.weapons[laser_slot].cooldown > 0.35) {
            out.laser_cooling = true;
        }

        // Check Regen Hold: avoid resetting our 5s regen timer with non-urgent crate/NPC shots when wounded
        int los_enemies = tracker.count_enemies_with_los(self, cfg, world);
        bool regen_hold_farm = (self.cubes >= 21) ||
                               (self.hp < 0.80 * self.max_hp) ||
                               (los_enemies > 0) ||
                               tracker.enemy_within(self.pos, 95.0);
        // Also avoid resetting regen timer with low-value chip shots when fleeing behind cover at low HP
        bool use_hyst_stealth = (tracker.ffa_confidence < 0.55);
        bool in_low_hp_regen = (los_enemies == 0) &&
                               !tracker.enemy_within(self.pos, 42.0) &&
                               (((self.hp < 0.46 * self.max_hp) && ((tracker.t - tracker.last_combat_t) >= 0.8)) ||
                                (use_hyst_stealth && (self.hp < 0.78 * self.max_hp) && ((tracker.t - tracker.last_combat_t) >= 2.2)));

        // Select best shootable / trackable enemy mech
        int best_mech_id = -1;
        double best_mech_score = -1e9;
        const TrackedActor* best_mech = nullptr;

        for (const auto& kv : tracker.actors) {
            const TrackedActor& a = kv.second;
            if (!a.is_mech || !a.in_obs_now) continue;
            Vec3 tc = a.aim_pos(cfg);
            double dist = (tc - self.muzzle_pivot()).len();
            if (dist > 310.0) continue;

            bool los = a.in_solid_los;
            double sc = 100.0 - dist * 0.42;
            if (los) sc += 560.0; // Prioritize enemies with direct solid muzzle LOS!

            // Killable in one laser or quick burst -> finish the kill!
            double laser_dmg = (laser_slot >= 0) ? self.weapons[laser_slot].stats.damage * dmg_mult : 0.0;
            if (a.has_weapon("mortar") && laser_slot >= 0) {
                laser_dmg *= (1.0 + self.weapons[laser_slot].stats.cookoff);
                sc += 55.0; // Cookoff advantage!
            }
            if (a.hp <= std::max(140.0, laser_dmg * 0.95)) sc += 360.0;
            else sc += clamp_val((1.0 - a.hp / std::max(1.0, a.max_hp)) * 220.0, 0.0, 220.0);

            if ((tracker.t - a.damaged_us_t) < 2.5) sc += 85.0;
            if (a.id == tracker.last_attacker_id) sc += 30.0;
            if (a.charging && light_slot >= 0 && dist <= self.weapons[light_slot].stats.range + 10.0) {
                sc += 110.0; // Short their laser!
            }

            // Rear-armor bonus check: angle from target to us vs target aim
            double bearing_to_us = std::atan2(self.pos.y - a.pos.y, self.pos.x - a.pos.x);
            if (std::abs(angle_diff(bearing_to_us, a.aim_yaw)) > deg_to_rad(95.0)) {
                sc += 45.0;
            }

            if (sc > best_mech_score) {
                best_mech_score = sc;
                best_mech_id = a.id;
                best_mech = &a;
            }
        }

        // Defend against an aggroed NPC shooting us if no mech has LOS & no mech is close
        if (los_enemies == 0 && !tracker.enemy_within(self.pos, 80.0)) {
            const TrackedActor* danger_npc = nullptr;
            double best_nd = ((tracker.t - tracker.last_npc_damaged_t) < 2.0) ? 65.0 : 46.0;
            for (const auto& kv : tracker.actors) {
                const TrackedActor& a = kv.second;
                if (a.is_mech || !a.in_obs_now || !a.in_solid_los) continue;
                double d = (a.pos - self.pos).len();
                if (d < best_nd && (self.hp >= 0.35 * self.max_hp || (tracker.t - tracker.last_npc_damaged_t) < 2.0)) {
                    best_nd = d;
                    danger_npc = &a;
                }
            }
            if (danger_npc != nullptr && (laser_slot < 0 || self.weapons[laser_slot].charge <= 0.0)) {
                bool suppress_laser = (self.hp < 0.85 * self.max_hp) && (gun_slot >= 0 || light_slot >= 0);
                aim_and_fire_target(
                    danger_npc->pos, danger_npc->vel,
                    cfg.npc_radius, cfg.npc_height,
                    danger_npc->hp, false, false, true, 0.50, {0, 0, 0},
                    self, tracker, world, muzzle_offset, dmg_mult, shorted || suppress_laser, false, out
                );
                return out;
            }
        }

        if (best_mech != nullptr) {
            out.primary_target_id = best_mech_id;
            out.engaging_mech = true;
            if (in_low_hp_regen && !best_mech->in_solid_los &&
                (laser_slot < 0 || self.weapons[laser_slot].charge <= 0.0)) {
                // Hold fire while healing behind cover, just face recent attacker / primary for rear armor!
                if ((tracker.t - tracker.last_damaged_t) < 1.5) {
                    out.aim_yaw = tracker.last_damaged_bearing;
                } else {
                    out.aim_yaw = std::atan2(best_mech->pos.y - self.pos.y, best_mech->pos.x - self.pos.x);
                }
                out.aim_pitch = 0.0;
                return out;
            }
            aim_and_fire_target(
                best_mech->pos, best_mech->vel,
                best_mech->radius(cfg), best_mech->height(cfg),
                best_mech->hp, best_mech->is_mech,
                best_mech->has_weapon("mortar"),
                best_mech->in_solid_los, best_mech->best_aim_z_frac, best_mech->accel,
                self, tracker, world, muzzle_offset, dmg_mult, shorted, suppress_blind_precharge, out
            );
            // Rear armor protection: if primary has NO LOS right now and we're not holding laser charge,
            // make sure we face any recent rear attacker!
            if (!best_mech->in_solid_los &&
                (laser_slot < 0 || self.weapons[laser_slot].charge <= 0.0) &&
                (tracker.t - tracker.last_damaged_t) < 1.2 &&
                tracker.last_damaged_rear) {
                out.aim_yaw = tracker.last_damaged_bearing;
                out.aim_pitch = 0.0;
            }
            return out;
        }

        // No mech currently visible/in-memory: consider NPC or Crate farming if NOT in regen_hold
        if (!regen_hold_farm) {
            // Check visible NPCs (only fight NPCs when healthy!)
            const TrackedActor* best_npc = nullptr;
            double best_npc_d = 1e9;
            if (self.hp >= 0.80 * self.max_hp) {
                for (const auto& kv : tracker.actors) {
                    const TrackedActor& a = kv.second;
                    if (a.is_mech || !a.in_obs_now || !a.in_solid_los) continue;
                    double d = (a.pos - self.pos).len();
                    if (d < 150.0 && d < best_npc_d) {
                        best_npc_d = d;
                        best_npc = &a;
                    }
                }
            }

            // Check visible crates
            const RememberedItem* best_crate = nullptr;
            double best_crate_d = 1e9;
            for (const auto& kv : tracker.crates) {
                const RememberedItem& c = kv.second;
                if (!c.visible_now) continue;
                double d = (c.pos - self.pos).len();
                Vec3 cc = {c.pos.x, c.pos.y, c.pos.z + 0.5 * cfg.crate_height};
                if (d < 120.0 && world.has_solid_los(self.muzzle_pivot(), cc) && d < best_crate_d) {
                    best_crate_d = d;
                    best_crate = &c;
                }
            }

            bool farm_priority = (self.cubes < 21 || best_crate_d < 45.0 || best_npc_d < 55.0);
            if (farm_priority && (best_crate || best_npc)) {
                if (best_crate && (!best_npc || best_crate_d < best_npc_d + 20.0)) {
                    aim_and_fire_target(
                        best_crate->pos, {0, 0, 0},
                        cfg.crate_radius, cfg.crate_height,
                        best_crate->hp, false, false, true, 0.50, {0, 0, 0},
                        self, tracker, world, muzzle_offset, dmg_mult, shorted, false, out
                    );
                    return out;
                } else if (best_npc) {
                    aim_and_fire_target(
                        best_npc->pos, best_npc->vel,
                        cfg.npc_radius, cfg.npc_height,
                        best_npc->hp, false, false, true, 0.50, {0, 0, 0},
                        self, tracker, world, muzzle_offset, dmg_mult, shorted, false, out
                    );
                    return out;
                }
            }
        }

        // Release any lingering laser charge safely if target disappeared and we hold near timeout
        if (laser_slot >= 0 && self.weapons[laser_slot].charge > 0.0) {
            if (self.weapons[laser_slot].charge >= self.weapons[laser_slot].stats.hold_s - 0.25) {
                out.fire[laser_slot] = false;
            } else {
                out.fire[laser_slot] = true; // hold briefly in case target peeks back
            }
        }

        // Smart early gun reload when safe
        if (gun_slot >= 0) {
            const auto& g = self.weapons[gun_slot];
            if (g.reload <= 0.0 && g.ammo > 0 && g.ammo <= 5.0 && g.ammo < g.stats.mag) {
                out.reload = true;
            }
        }

        // Rear-armor orientation: face recent damaged bearing or loudest nearby sound, else sweep
        if ((tracker.t - tracker.last_damaged_t) < 2.5) {
            out.aim_yaw = tracker.last_damaged_bearing;
            out.aim_pitch = 0.0;
        } else {
            double best_sound_sc = -1e9;
            bool has_sound = false;
            double sb = 0.0;
            for (const auto& sc : tracker.sounds) {
                double age = tracker.t - sc.time;
                if (age > 2.0) continue;
                double w = 100.0 - age * 30.0 - sc.est_dist * 0.2;
                if (sc.kind == "laser_charge" || sc.kind == "lightning" || sc.kind == "boost") w += 40.0;
                if (w > best_sound_sc) {
                    best_sound_sc = w;
                    sb = sc.bearing;
                    has_sound = true;
                }
            }
            if (has_sound) {
                out.aim_yaw = sb;
                out.aim_pitch = 0.0;
            } else {
                out.aim_yaw = scan_fallback_yaw;
                out.aim_pitch = 0.0;
            }
        }
        return out;
    }

private:
    void handle_weapon_loot(
        const Json& obs,
        const SelfState& self,
        const GameConfig& cfg,
        CombatDecision& out
    ) const {
        double max_reach = cfg.loot_pickup_radius - 0.12;
        int best_id = -1;
        int best_score = 0;
        int best_drop = -1;

        for (const auto& pj : obs["pickups"].arr_val) {
            int id = pj["id"].as_int(-1);
            const std::string& kind = pj["kind"].as_str();
            const auto& pos = pj["pos"].arr_val;
            if (id < 0 || pos.size() < 3) continue;
            double px = pos[0].as_double(), py = pos[1].as_double(), pz = pos[2].as_double();
            double dxy = std::hypot(px - self.pos.x, py - self.pos.y);
            double dz = std::abs(pz - self.pos.z);
            if (dxy >= max_reach || dz >= 3.85) continue;

            // Cannot hold two weapons of the same kind
            if (self.find_weapon(kind) >= 0) continue;

            int des = weapon_desirability(kind);
            if (des <= 20) continue; // Skip unwanted mortar!

            int empty = self.empty_slot();
            if (empty >= 0) {
                if (des > best_score) {
                    best_score = des;
                    best_id = id;
                    best_drop = -1;
                }
            } else {
                // Swap out the weaker slot if not charging laser
                int worst_slot = -1;
                int worst_des = 999;
                for (int s = 0; s < 2; ++s) {
                    if (self.weapons[s].charge > 0.0) continue; // Busy!
                    int sd = weapon_desirability(self.weapons[s].kind);
                    if (sd < worst_des) {
                        worst_des = sd;
                        worst_slot = s;
                    }
                }
                if (worst_slot >= 0 && des > worst_des && des > best_score) {
                    best_score = des;
                    best_id = id;
                    best_drop = worst_slot;
                }
            }
        }

        if (best_id >= 0) {
            out.take_pickup_id = best_id;
            out.drop_slot = best_drop;
        }
    }

    void aim_and_fire_target(
        const Vec3& target_pos,
        const Vec3& target_vel,
        double target_r,
        double target_h,
        double target_hp,
        bool is_mech,
        bool target_has_mortar,
        bool has_los,
        double aim_z_frac,
        const Vec3& target_accel,
        const SelfState& self,
        const Tracker& tracker,
        const World& world,
        double muzzle_offset,
        double dmg_mult,
        bool shorted,
        bool suppress_blind_precharge,
        CombatDecision& out
    ) const {
        Vec3 pivot = self.muzzle_pivot();
        Vec3 target_com = {target_pos.x, target_pos.y, target_pos.z + aim_z_frac * target_h};
        double dist = (target_com - pivot).len();

        int laser_slot = self.find_weapon("laser");
        int light_slot = self.find_weapon("lightning");
        int gun_slot = self.find_weapon("gun");
        int mortar_slot = self.find_weapon("mortar");

        // Actual slewed aim direction right now
        Vec3 actual_dir = vec_from_yaw_pitch(self.aim_yaw, self.aim_pitch);
        Vec3 actual_origin = pivot + actual_dir * std::min(muzzle_offset, std::max(0.0, dist - 0.5));

        // 1. LASER LOGIC with exact 1-tick (0.05s) forward slew & motion release predictor
        bool laser_aim_priority = false;
        if (laser_slot >= 0 && !shorted) {
            const auto& lw = self.weapons[laser_slot];
            double max_r = lw.stats.range;
            double full_charge_s = lw.stats.charge;
            double min_charge_s = lw.stats.min_charge;
            double full_dmg = lw.stats.damage * dmg_mult * (target_has_mortar ? (1.0 + lw.stats.cookoff) : 1.0);
            double charge_frac = (full_charge_s > 1e-4) ? clamp_val(lw.charge / full_charge_s, 0.0, 1.0) : 1.0;
            double cur_dmg = full_dmg * (lw.stats.min_frac + (1.0 - lw.stats.min_frac) * charge_frac);

            if (lw.charge > 0.0) {
                // Already charging laser!
                laser_aim_priority = true;
                Vec3 aim_tgt = target_com + target_vel * 0.05;
                yaw_pitch_from_vec(aim_tgt - pivot, out.aim_yaw, out.aim_pitch);

                // Predict exact state at t + 0.05s (when fire=false fires)
                const double dt1 = 0.05;
                double dy = angle_diff(out.aim_yaw, self.aim_yaw);
                double max_dy = self.turn_rate * dt1;
                double pred_yaw = wrap_angle(self.aim_yaw + clamp_val(dy, -max_dy, max_dy));
                double dp = clamp_val(out.aim_pitch, self.min_pitch, self.max_pitch) - self.aim_pitch;
                double max_dp = self.pitch_rate * dt1;
                double pred_pitch = clamp_val(self.aim_pitch + clamp_val(dp, -max_dp, max_dp), self.min_pitch, self.max_pitch);

                Vec3 pred_self = self.pos + self.vel * dt1;
                if (self.grounded) pred_self.z = self.pos.z;
                Vec3 pred_pivot(pred_self.x, pred_self.y, pred_self.z + self.muzzle_height);
                Vec3 pred_dir = vec_from_yaw_pitch(pred_yaw, pred_pitch);
                double wt_off = muzzle_offset;
                if (world.raycast_solid(pred_pivot, pred_dir, muzzle_offset, &wt_off)) {
                    wt_off = std::max(0.1, wt_off - 0.05);
                }
                Vec3 pred_orig = pred_pivot + pred_dir * wt_off;
                double pred_wall_t = 1e9;
                bool pred_wall_hit = world.raycast_solid(pred_orig, pred_dir, dist + target_r + 2.0, &pred_wall_t);

                Vec3 pred_tgt = target_pos + target_vel * dt1;
                double pred_cyl_t = 1e9;
                bool pred_hits_cyl = ray_cylinder_hit(
                    pred_orig, pred_dir, dist + target_r + 2.0,
                    pred_tgt.x, pred_tgt.y, pred_tgt.z, pred_tgt.z + target_h,
                    target_r * 0.94, &pred_cyl_t
                );
                bool next_laser_clear = pred_hits_cyl && (!pred_wall_hit || pred_cyl_t < pred_wall_t);

                Vec3 future_tgt_aim(pred_tgt.x + target_vel.x * 0.12, pred_tgt.y + target_vel.y * 0.12, pred_tgt.z + aim_z_frac * target_h);
                Vec3 future_self_orig(pred_orig.x + self.vel.x * 0.12, pred_orig.y + self.vel.y * 0.12, pred_orig.z);
                bool about_to_lose_los = is_mech && lw.charge >= 0.45 && !world.has_solid_los(future_self_orig, future_tgt_aim);

                bool kill_now = (lw.charge >= min_charge_s && target_hp <= cur_dmg * 0.80);
                bool full_now = (lw.charge >= full_charge_s - 0.015);
                bool timeout_soon = (lw.charge >= full_charge_s + lw.stats.hold_s - 0.25);

                if (timeout_soon) {
                    out.fire[laser_slot] = false; // release before auto-fire
                } else if ((full_now || kill_now || about_to_lose_los) && next_laser_clear) {
                    out.fire[laser_slot] = false; // release for hitscan hit!
                } else {
                    out.fire[laser_slot] = true; // keep charging / holding until aligned!
                    if (is_mech && !has_los) out.want_peek_for_laser = true;
                }
            } else if (lw.cooldown <= 0.14 && dist <= max_r - 2.0) {
                // Decide whether to start charging laser
                bool avoid_slow = (is_mech && dist < 44.0 && tracker.enemy_within(self.pos, 44.0) &&
                                   (light_slot >= 0 || self.hp < 0.35 * self.max_hp));
                bool worth_laser = is_mech || (target_hp >= 180.0 && self.hp >= 0.88 * self.max_hp && !tracker.enemy_within(self.pos, 110.0));
                if (worth_laser && !avoid_slow) {
                    if (has_los) {
                        out.fire[laser_slot] = true;
                        laser_aim_priority = true;
                        yaw_pitch_from_vec((target_com + target_vel * 0.1) - pivot, out.aim_yaw, out.aim_pitch);
                    } else if (is_mech && dist < 165.0) {
                        out.want_peek_for_laser = true;
                        laser_aim_priority = true;
                        yaw_pitch_from_vec((target_com + target_vel * 0.15) - pivot, out.aim_yaw, out.aim_pitch);
                        if (dist < 130.0 && !suppress_blind_precharge) {
                            out.fire[laser_slot] = true;
                        }
                    }
                }
            }
        }

        // 2. LIGHTNING LOGIC (close range <= range, 30 deg yaw cone, costs energy)
        if (light_slot >= 0) {
            const auto& li = self.weapons[light_slot];
            double cost = li.stats.energy;
            double lrange = li.stats.range;
            double half_cone = deg_to_rad(li.stats.cone_deg * 0.90);
            double desired_yaw = std::atan2(target_com.y - self.pos.y, target_com.x - self.pos.x);
            double yaw_err = std::abs(angle_diff(desired_yaw, self.aim_yaw));

            if (!laser_aim_priority && dist <= lrange + 15.0) {
                out.aim_yaw = desired_yaw;
                out.aim_pitch = 0.0;
            }

            bool energy_ok = (self.energy >= cost + (is_mech ? 4.0 : 25.0)) ||
                             (is_mech && target_hp <= li.stats.damage * dmg_mult * 2.0 && self.energy >= cost);
            if (li.cooldown <= 0.10 && energy_ok && dist <= lrange - 0.6 &&
                yaw_err <= half_cone && has_los) {
                out.fire[light_slot] = true;
            }
        }

        // 3. GUN LOGIC (adaptive lead prediction + LOS check)
        if (gun_slot >= 0) {
            const auto& gw = self.weapons[gun_slot];
            double lead_damp = (target_accel.xy().len() > 26.0) ? 0.68 : 0.95;
            Vec3 lead_vel = target_vel * lead_damp;
            double g_yaw = out.aim_yaw, g_pitch = out.aim_pitch, g_ft = 0.0;
            solve_gun_lead(pivot, target_com, lead_vel, gw.stats.speed, muzzle_offset, g_yaw, g_pitch, g_ft);
            if (!laser_aim_priority && (light_slot < 0 || dist > self.weapons[light_slot].stats.range - 2.0)) {
                out.aim_yaw = g_yaw;
                out.aim_pitch = g_pitch;
            }
            if (gw.cooldown <= 0.12 && gw.ammo > 0.0 && gw.reload <= 0.0 && dist <= gw.stats.range - 2.0) {
                Vec3 pred_pos = target_com + lead_vel * g_ft;
                double ang_tol = std::max(0.035, std::atan2(target_r * 1.15, std::max(5.0, dist)));
                double y_err = std::abs(angle_diff(g_yaw, self.aim_yaw));
                double p_err = std::abs(g_pitch - self.aim_pitch);
                if (y_err <= ang_tol && p_err <= ang_tol * 1.5 &&
                    world.has_solid_los(actual_origin, pred_pos)) {
                    out.fire[gun_slot] = true;
                }
            } else if (gw.ammo <= 0.0 && gw.reload <= 0.0) {
                out.reload = true;
            }
        }

        // 4. MORTAR LOGIC (if carried: solve 3D arc and verify parabola doesn't hit near wall or self)
        if (mortar_slot >= 0) {
            const auto& mw = self.weapons[mortar_slot];
            if (mw.cooldown <= 0.15) {
                Vec3 mpivot = self.mortar_pivot();
                auto sols = solve_mortar_ballistic(
                    mpivot, target_com, target_vel,
                    mw.stats.speed, mw.stats.gravity, muzzle_offset,
                    self.min_pitch, self.max_pitch
                );
                for (const auto& s : sols) {
                    if (is_mortar_arc_clear(mpivot, s, mw.stats, muzzle_offset, self.pos, world)) {
                        if (!laser_aim_priority && gun_slot < 0) {
                            out.aim_yaw = s.yaw;
                            out.aim_pitch = s.pitch;
                        }
                        if (std::abs(angle_diff(s.yaw, self.aim_yaw)) < 0.12 &&
                            std::abs(s.pitch - self.aim_pitch) < 0.12) {
                            out.fire[mortar_slot] = true;
                        }
                        break;
                    }
                }
            }
        }

        out.aim_pitch = clamp_val(out.aim_pitch, self.min_pitch, self.max_pitch);
    }

    static bool is_mortar_arc_clear(
        const Vec3& mpivot,
        const BallisticSolution& sol,
        const WeaponConfig& mw,
        double muzzle_offset,
        const Vec3& self_pos,
        const World& world
    ) {
        Vec3 dir = vec_from_yaw_pitch(sol.yaw, sol.pitch);
        Vec3 p = mpivot + dir * muzzle_offset;
        Vec3 v = dir * mw.speed;
        int steps = std::max(4, static_cast<int>(std::floor(sol.flight_t / 0.08)));
        double dt = 0.08;
        for (int i = 0; i < steps - 1; ++i) {
            Vec3 nv = {v.x, v.y, v.z - mw.gravity * dt};
            Vec3 np = p + (v + nv) * (0.5 * dt);
            if (!world.has_solid_los(p, np)) {
                // Blocked mid-flight; check if too close to self
                if ((np - self_pos).len() < mw.splash_radius + 4.5) return false;
                return false;
            }
            p = np;
            v = nv;
        }
        return (p - self_pos).len() > mw.splash_radius + 4.0;
    }
};

} // namespace mf
