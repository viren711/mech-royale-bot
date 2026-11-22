#pragma once

#include "json.hpp"
#include <string>
#include <unordered_map>
#include <vector>

namespace mf {

struct WeaponConfig {
    double damage = 45.0;
    double cooldown = 0.24;
    double speed = 252.0;
    double range = 230.0;
    double spread_deg = 0.6;
    double mag = 12.0;
    double reload = 2.4;

    // Mortar
    double splash = 160.0;
    double splash_radius = 7.0;
    double splash_edge = 0.3;
    double gravity = 22.0;
    double ttl = 7.0;
    double knock = 16.0;
    double knock_up = 9.0;
    double drain = 45.0;

    // Laser
    double charge = 0.75;
    double min_charge = 0.15;
    double min_frac = 0.35;
    double hold_s = 2.0;
    double pierce = 0.0;
    double charge_turn_mult = 1.0;
    double cookoff = 0.6;

    // Lightning
    double cone_deg = 30.0;
    double chain = 2.0;
    double chain_range = 14.0;
    double chain_falloff = 0.7;
    double energy = 3.0;
    double short_s = 2.0;
};

struct UpgradeEffect {
    std::string path;
    bool has_mul = false;
    double mul = 1.0;
    bool has_add = false;
    double add = 0.0;
};

struct UpgradeDef {
    std::string id;
    std::string name;
    std::string desc;
    std::string requires_weapon;
    int max_stacks = 1;
    std::vector<UpgradeEffect> effects;
};

struct ZonePhase {
    double hold_s = 60.0;
    double shrink_s = 50.0;
    double radius = 380.0;
    double dps = 20.0;
};

struct GameConfig {
    // match
    double tick_hz = 20.0;
    int decide_every = 2;
    double duration_s = 480.0;
    int mechs = 16;

    // bot
    double tick_budget_ms = 50.0;
    double offer_timeout_s = 5.0;

    // mech defaults
    double mech_radius = 2.5;
    double mech_height = 9.0;
    double eye_height = 8.0;
    double muzzle_height = 7.0;
    double mech_hp = 1400.0;
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
    double energy = 100.0;
    double energy_regen = 18.0;
    double energy_regen_delay = 0.6;
    double boost_drain = 17.0;
    double jet_drain = 15.0;
    double turn_rate = 4.0;
    double pitch_rate = 3.0;
    double min_pitch = -0.7;
    double max_pitch = 1.3;
    double regen_delay = 5.0;
    double regen_per_s = 45.0;
    double charge_move_mult = 0.5;
    double self_damage_mult = 0.5;
    double rear_mult = 1.5;
    double front_arc_deg = 180.0;

    // vision
    double vision_range = 200.0;
    double vision_fov_deg = 120.0;
    double vision_near_range = 45.0;
    bool canopy_blocks = true;
    bool show_enemy_hp = true;
    double memory_s = 5.0;

    // sound
    double bearing_noise_deg = 7.0;
    double sound_near = 60.0;
    double sound_mid = 160.0;

    // weapons
    WeaponConfig gun;
    WeaponConfig mortar;
    WeaponConfig laser;
    WeaponConfig lightning;

    // cubes, crates, loot, npc, drops
    double cube_pickup_radius = 3.5;
    double hp_per_cube = 0.04;
    double damage_per_cube = 0.04;
    int stat_cap = 10;
    double size_per_cube = 0.05;
    std::vector<int> upgrade_thresholds;

    double crate_hp = 300.0;
    double crate_radius = 1.4;
    double crate_height = 2.4;

    double loot_pickup_radius = 4.0;
    double loot_equip_s = 1.0;

    double npc_hp = 350.0;
    double npc_radius = 1.8;
    double npc_height = 3.5;
    double npc_aggro_range = 45.0;
    double npc_damage = 25.0;

    bool has_drops = false;
    std::vector<double> drop_times;
    double drop_fall_s = 25.0;
    double drop_radius = 8.0;
    double drop_capture_s = 4.0;
    double drop_cubes = 3.0;

    // zone
    double zone_start_cx = 41.3;
    double zone_start_cy = -72.8;
    double zone_start_radius = 560.0;
    std::vector<ZonePhase> zone_phases;

    // upgrades
    std::vector<UpgradeDef> upgrades;
    std::unordered_map<std::string, UpgradeDef> upgrade_by_id;

    static WeaponConfig parse_weapon(const Json& w) {
        WeaponConfig c;
        c.damage = w["damage"].as_double(c.damage);
        c.cooldown = w["cooldown"].as_double(c.cooldown);
        c.speed = w["speed"].as_double(c.speed);
        c.range = w["range"].as_double(c.range);
        c.spread_deg = w["spread_deg"].as_double(c.spread_deg);
        c.mag = w["mag"].as_double(c.mag);
        c.reload = w["reload"].as_double(c.reload);
        c.splash = w["splash"].as_double(c.splash);
        c.splash_radius = w["splash_radius"].as_double(c.splash_radius);
        c.splash_edge = w["splash_edge"].as_double(c.splash_edge);
        c.gravity = w["gravity"].as_double(c.gravity);
        c.ttl = w["ttl"].as_double(c.ttl);
        c.knock = w["knock"].as_double(c.knock);
        c.knock_up = w["knock_up"].as_double(c.knock_up);
        c.drain = w["drain"].as_double(c.drain);
        c.charge = w["charge"].as_double(c.charge);
        c.min_charge = w["min_charge"].as_double(c.min_charge);
        c.min_frac = w["min_frac"].as_double(c.min_frac);
        c.hold_s = w["hold_s"].as_double(c.hold_s);
        c.pierce = w["pierce"].as_double(c.pierce);
        c.charge_turn_mult = w["charge_turn_mult"].as_double(c.charge_turn_mult);
        c.cookoff = w["cookoff"].as_double(c.cookoff);
        c.cone_deg = w["cone_deg"].as_double(c.cone_deg);
        c.chain = w["chain"].as_double(c.chain);
        c.chain_range = w["chain_range"].as_double(c.chain_range);
        c.chain_falloff = w["chain_falloff"].as_double(c.chain_falloff);
        c.energy = w["energy"].as_double(c.energy);
        c.short_s = w["short_s"].as_double(c.short_s);
        return c;
    }

    static GameConfig from_json(const Json& cfg) {
        GameConfig g;
        const auto& m = cfg["match"];
        g.tick_hz = m["tick_hz"].as_double(g.tick_hz);
        g.decide_every = m["decide_every"].as_int(g.decide_every);
        g.duration_s = m["duration_s"].as_double(g.duration_s);
        g.mechs = m["mechs"].as_int(g.mechs);

        const auto& b = cfg["bot"];
        g.tick_budget_ms = b["tick_budget_ms"].as_double(g.tick_budget_ms);
        g.offer_timeout_s = b["offer_timeout_s"].as_double(g.offer_timeout_s);

        const auto& mc = cfg["mech"];
        g.mech_radius = mc["radius"].as_double(g.mech_radius);
        g.mech_height = mc["height"].as_double(g.mech_height);
        g.eye_height = mc["eye_height"].as_double(g.eye_height);
        g.muzzle_height = mc["muzzle_height"].as_double(g.muzzle_height);
        g.mech_hp = mc["hp"].as_double(g.mech_hp);
        g.walk_speed = mc["walk_speed"].as_double(g.walk_speed);
        g.boost_speed = mc["boost_speed"].as_double(g.boost_speed);
        g.ground_accel = mc["ground_accel"].as_double(g.ground_accel);
        g.air_accel = mc["air_accel"].as_double(g.air_accel);
        g.gravity = mc["gravity"].as_double(g.gravity);
        g.jump_speed = mc["jump_speed"].as_double(g.jump_speed);
        g.jet_accel = mc["jet_accel"].as_double(g.jet_accel);
        g.max_rise_speed = mc["max_rise_speed"].as_double(g.max_rise_speed);
        g.step_up = mc["step_up"].as_double(g.step_up);
        g.max_slope_deg = mc["max_slope_deg"].as_double(g.max_slope_deg);
        g.energy = mc["energy"].as_double(g.energy);
        g.energy_regen = mc["energy_regen"].as_double(g.energy_regen);
        g.energy_regen_delay = mc["energy_regen_delay"].as_double(g.energy_regen_delay);
        g.boost_drain = mc["boost_drain"].as_double(g.boost_drain);
        g.jet_drain = mc["jet_drain"].as_double(g.jet_drain);
        g.turn_rate = mc["turn_rate"].as_double(g.turn_rate);
        g.pitch_rate = mc["pitch_rate"].as_double(g.pitch_rate);
        g.min_pitch = mc["min_pitch"].as_double(g.min_pitch);
        g.max_pitch = mc["max_pitch"].as_double(g.max_pitch);
        g.regen_delay = mc["regen_delay"].as_double(g.regen_delay);
        g.regen_per_s = mc["regen_per_s"].as_double(g.regen_per_s);
        g.charge_move_mult = mc["charge_move_mult"].as_double(g.charge_move_mult);
        g.self_damage_mult = mc["self_damage_mult"].as_double(g.self_damage_mult);
        g.rear_mult = mc["rear_mult"].as_double(g.rear_mult);
        g.front_arc_deg = mc["front_arc_deg"].as_double(g.front_arc_deg);

        const auto& v = cfg["vision"];
        g.vision_range = v["range"].as_double(g.vision_range);
        g.vision_fov_deg = v["fov_deg"].as_double(g.vision_fov_deg);
        g.vision_near_range = v["near_range"].as_double(g.vision_near_range);
        g.canopy_blocks = v["canopy_blocks"].as_bool(g.canopy_blocks);
        g.show_enemy_hp = v["show_enemy_hp"].as_bool(g.show_enemy_hp);
        g.memory_s = v["memory_s"].as_double(g.memory_s);

        const auto& s = cfg["sound"];
        g.bearing_noise_deg = s["bearing_noise_deg"].as_double(g.bearing_noise_deg);
        g.sound_near = s["near"].as_double(g.sound_near);
        g.sound_mid = s["mid"].as_double(g.sound_mid);

        const auto& ws = cfg["weapons"];
        g.gun = parse_weapon(ws["gun"]);
        g.mortar = parse_weapon(ws["mortar"]);
        g.laser = parse_weapon(ws["laser"]);
        g.lightning = parse_weapon(ws["lightning"]);

        const auto& cu = cfg["cubes"];
        g.cube_pickup_radius = cu["pickup_radius"].as_double(g.cube_pickup_radius);
        g.hp_per_cube = cu["hp_per_cube"].as_double(g.hp_per_cube);
        g.damage_per_cube = cu["damage_per_cube"].as_double(g.damage_per_cube);
        g.stat_cap = cu["stat_cap"].as_int(g.stat_cap);
        g.size_per_cube = cu["size_per_cube"].as_double(g.size_per_cube);
        for (const auto& t : cu["upgrade_thresholds"].arr_val) {
            g.upgrade_thresholds.push_back(t.as_int());
        }

        const auto& cr = cfg["crates"];
        g.crate_hp = cr["hp"].as_double(g.crate_hp);
        g.crate_radius = cr["radius"].as_double(g.crate_radius);
        g.crate_height = cr["height"].as_double(g.crate_height);

        const auto& lo = cfg["loot"];
        g.loot_pickup_radius = lo["pickup_radius"].as_double(g.loot_pickup_radius);
        g.loot_equip_s = lo["equip_s"].as_double(g.loot_equip_s);

        const auto& np = cfg["npc"];
        g.npc_hp = np["hp"].as_double(g.npc_hp);
        g.npc_radius = np["radius"].as_double(g.npc_radius);
        g.npc_height = np["height"].as_double(g.npc_height);
        g.npc_aggro_range = np["aggro_range"].as_double(g.npc_aggro_range);
        g.npc_damage = np["damage"].as_double(g.npc_damage);

        if (cfg.has("drops") && cfg["drops"].is_object()) {
            g.has_drops = true;
            const auto& dr = cfg["drops"];
            for (const auto& t : dr["times"].arr_val) g.drop_times.push_back(t.as_double());
            g.drop_fall_s = dr["fall_s"].as_double(g.drop_fall_s);
            g.drop_radius = dr["radius"].as_double(g.drop_radius);
            g.drop_capture_s = dr["capture_s"].as_double(g.drop_capture_s);
            g.drop_cubes = dr["cubes"].as_double(g.drop_cubes);
        }

        const auto& z = cfg["zone"];
        if (z["start_center"].arr_val.size() >= 2) {
            g.zone_start_cx = z["start_center"][0].as_double(g.zone_start_cx);
            g.zone_start_cy = z["start_center"][1].as_double(g.zone_start_cy);
        }
        g.zone_start_radius = z["start_radius"].as_double(g.zone_start_radius);
        for (const auto& zp : z["phases"].arr_val) {
            ZonePhase p;
            p.hold_s = zp["hold_s"].as_double(p.hold_s);
            p.shrink_s = zp["shrink_s"].as_double(p.shrink_s);
            p.radius = zp["radius"].as_double(p.radius);
            p.dps = zp["dps"].as_double(p.dps);
            g.zone_phases.push_back(p);
        }

        for (const auto& up : cfg["upgrades"].arr_val) {
            UpgradeDef u;
            u.id = up["id"].as_str();
            u.name = up["name"].as_str();
            u.desc = up["desc"].as_str();
            u.requires_weapon = up["requires"].as_str("");
            u.max_stacks = up["max"].as_int(1);
            for (const auto& ef : up["effects"].arr_val) {
                UpgradeEffect e;
                e.path = ef["path"].as_str();
                if (ef.has("mul")) {
                    e.has_mul = true;
                    e.mul = ef["mul"].as_double(1.0);
                }
                if (ef.has("add")) {
                    e.has_add = true;
                    e.add = ef["add"].as_double(0.0);
                }
                u.effects.push_back(e);
            }
            g.upgrade_by_id[u.id] = u;
            g.upgrades.push_back(std::move(u));
        }

        return g;
    }
};

} // namespace mf
