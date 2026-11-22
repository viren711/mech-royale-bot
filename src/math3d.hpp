#pragma once

#include <algorithm>
#include <cmath>
#include <vector>

namespace mf {

constexpr double kPi = 3.14159265358979323846;
constexpr double kTwoPi = 2.0 * kPi;

struct Vec2 {
    double x = 0.0;
    double y = 0.0;

    Vec2() = default;
    Vec2(double x_, double y_) : x(x_), y(y_) {}

    Vec2 operator+(const Vec2& o) const { return {x + o.x, y + o.y}; }
    Vec2 operator-(const Vec2& o) const { return {x - o.x, y - o.y}; }
    Vec2 operator*(double s) const { return {x * s, y * s}; }
    Vec2 operator/(double s) const { return {x / s, y / s}; }
    Vec2& operator+=(const Vec2& o) { x += o.x; y += o.y; return *this; }
    Vec2& operator-=(const Vec2& o) { x -= o.x; y -= o.y; return *this; }

    double dot(const Vec2& o) const { return x * o.x + y * o.y; }
    double cross(const Vec2& o) const { return x * o.y - y * o.x; }
    double len_sq() const { return x * x + y * y; }
    double len() const { return std::hypot(x, y); }
    Vec2 normalized() const {
        double l = len();
        return l > 1e-9 ? Vec2(x / l, y / l) : Vec2(0.0, 0.0);
    }
};

struct Vec3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;

    Vec3() = default;
    Vec3(double x_, double y_, double z_) : x(x_), y(y_), z(z_) {}

    Vec3 operator+(const Vec3& o) const { return {x + o.x, y + o.y, z + o.z}; }
    Vec3 operator-(const Vec3& o) const { return {x - o.x, y - o.y, z - o.z}; }
    Vec3 operator*(double s) const { return {x * s, y * s, z * s}; }
    Vec3 operator/(double s) const { return {x / s, y / s, z / s}; }
    Vec3& operator+=(const Vec3& o) { x += o.x; y += o.y; z += o.z; return *this; }

    Vec2 xy() const { return {x, y}; }
    double dot(const Vec3& o) const { return x * o.x + y * o.y + z * o.z; }
    double len_sq() const { return x * x + y * y + z * z; }
    double len() const { return std::sqrt(len_sq()); }
    double dist_xy(const Vec3& o) const { return std::hypot(x - o.x, y - o.y); }
    Vec3 normalized() const {
        double l = len();
        return l > 1e-9 ? Vec3(x / l, y / l, z / l) : Vec3(1.0, 0.0, 0.0);
    }
};

inline double clamp_val(double v, double lo, double hi) {
    return std::max(lo, std::min(hi, v));
}

inline double wrap_angle(double a) {
    a = std::fmod(a + kPi, kTwoPi);
    if (a < 0.0) a += kTwoPi;
    return a - kPi;
}

inline double angle_diff(double target, double current) {
    return wrap_angle(target - current);
}

inline double deg_to_rad(double deg) {
    return deg * (kPi / 180.0);
}

inline Vec3 vec_from_yaw_pitch(double yaw, double pitch) {
    double cp = std::cos(pitch);
    return {cp * std::cos(yaw), cp * std::sin(yaw), std::sin(pitch)};
}

inline void yaw_pitch_from_vec(const Vec3& v, double& yaw, double& pitch) {
    yaw = std::atan2(v.y, v.x);
    double h = std::hypot(v.x, v.y);
    pitch = std::atan2(v.z, h);
}

// Exact 3D ray vs vertical cylinder [z_min, z_max] centered at (cx, cy) with radius R.
// Returns true if intersected in [0, max_t], writing earliest t >= 0 to out_t.
inline bool ray_cylinder_hit(
    const Vec3& orig,
    const Vec3& dir,
    double max_t,
    double cx,
    double cy,
    double z_min,
    double z_max,
    double radius,
    double* out_t = nullptr
) {
    double ox = orig.x - cx;
    double oy = orig.y - cy;
    double a = dir.x * dir.x + dir.y * dir.y;

    double t_enter = 0.0;
    double t_exit = max_t;

    if (a < 1e-12) {
        if (ox * ox + oy * oy > radius * radius) return false;
    } else {
        double b = 2.0 * (ox * dir.x + oy * dir.y);
        double c = ox * ox + oy * oy - radius * radius;
        double disc = b * b - 4.0 * a * c;
        if (disc < 0.0) return false;
        double sq = std::sqrt(disc);
        double inv = 0.5 / a;
        double r0 = (-b - sq) * inv;
        double r1 = (-b + sq) * inv;
        if (r0 > r1) std::swap(r0, r1);
        t_enter = std::max(t_enter, r0);
        t_exit = std::min(t_exit, r1);
        if (t_enter > t_exit) return false;
    }

    if (std::abs(dir.z) < 1e-12) {
        if (orig.z < z_min || orig.z > z_max) return false;
    } else {
        double tz0 = (z_min - orig.z) / dir.z;
        double tz1 = (z_max - orig.z) / dir.z;
        if (tz0 > tz1) std::swap(tz0, tz1);
        t_enter = std::max(t_enter, tz0);
        t_exit = std::min(t_exit, tz1);
        if (t_enter > t_exit) return false;
    }

    if (t_enter < 0.0 || t_enter > max_t) return false;
    if (out_t) *out_t = t_enter;
    return true;
}

// Minimum 2D distance from point P to segment AB, and parameter s in [0,1].
inline double dist_point_seg_2d(const Vec2& p, const Vec2& a, const Vec2& b, Vec2* closest = nullptr) {
    Vec2 ab = b - a;
    double len2 = ab.len_sq();
    double s = 0.0;
    if (len2 > 1e-12) {
        s = clamp_val((p - a).dot(ab) / len2, 0.0, 1.0);
    }
    Vec2 q = a + ab * s;
    if (closest) *closest = q;
    return (p - q).len();
}

// Solve quadratic intercept for projectile of speed `proj_speed` leaving `muzzle_offset` along aim from `pivot`.
// Returns true if valid intercept found within reasonable time; sets aim_yaw, aim_pitch, flight_t.
inline bool solve_gun_lead(
    const Vec3& pivot,
    const Vec3& target_pos,
    const Vec3& target_vel,
    double proj_speed,
    double muzzle_offset,
    double& out_yaw,
    double& out_pitch,
    double& out_flight_t
) {
    Vec3 rel = target_pos - pivot;
    double dist = rel.len();
    if (dist < 1e-4) {
        yaw_pitch_from_vec(Vec3(1, 0, 0), out_yaw, out_pitch);
        out_flight_t = 0.0;
        return true;
    }
    double t = std::max(0.0, (dist - muzzle_offset) / std::max(1.0, proj_speed));
    Vec3 aim_vec = rel;
    for (int iter = 0; iter < 5; ++iter) {
        Vec3 pred = target_pos + target_vel * t;
        Vec3 d = pred - pivot;
        double dlen = d.len();
        if (dlen < 1e-4) break;
        Vec3 dir = d / dlen;
        Vec3 shot_start = pivot + dir * std::min(muzzle_offset, std::max(0.0, dlen - 0.5));
        Vec3 shot_vec = pred - shot_start;
        double slen = shot_vec.len();
        double t_new = slen / std::max(1.0, proj_speed);
        // Also solve quadratic directly around current shot_start for fast movers
        Vec3 r = target_pos - shot_start;
        double a = target_vel.len_sq() - proj_speed * proj_speed;
        double b = 2.0 * r.dot(target_vel);
        double c = r.len_sq();
        if (std::abs(a) > 1e-6) {
            double disc = b * b - 4.0 * a * c;
            if (disc >= 0.0) {
                double sq = std::sqrt(disc);
                double t1 = (-b - sq) / (2.0 * a);
                double t2 = (-b + sq) / (2.0 * a);
                double best = -1.0;
                if (t1 > 0.0 && (best < 0.0 || t1 < best)) best = t1;
                if (t2 > 0.0 && (best < 0.0 || t2 < best)) best = t2;
                if (best >= 0.0) t_new = best;
            }
        }
        t = 0.5 * t + 0.5 * clamp_val(t_new, 0.0, 3.0);
        aim_vec = target_pos + target_vel * t - pivot;
    }
    yaw_pitch_from_vec(aim_vec, out_yaw, out_pitch);
    out_flight_t = t;
    return true;
}

struct BallisticSolution {
    double yaw = 0.0;
    double pitch = 0.0;
    double flight_t = 0.0;
    bool high_arc = false;
};

// Solve 3D ballistic mortar launch with gravity g and muzzle_offset forward along aim.
// Returns 0, 1, or 2 solutions (low arc first, high arc second).
inline std::vector<BallisticSolution> solve_mortar_ballistic(
    const Vec3& pivot,
    const Vec3& target_pos,
    const Vec3& target_vel,
    double speed,
    double gravity,
    double muzzle_offset,
    double min_pitch,
    double max_pitch
) {
    std::vector<BallisticSolution> sols;
    for (int mode = 0; mode < 2; ++mode) {
        bool high = (mode == 1);
        double t_est = clamp_val((target_pos - pivot).len() / std::max(1.0, speed), 0.1, 6.0);
        bool ok = true;
        double best_yaw = 0.0, best_pitch = 0.0;
        for (int iter = 0; iter < 6; ++iter) {
            Vec3 pred = target_pos + target_vel * t_est;
            // Approximate start point using current yaw/pitch if iter > 0
            double yaw = std::atan2(pred.y - pivot.y, pred.x - pivot.x);
            Vec3 start = pivot;
            if (iter > 0) {
                start = pivot + vec_from_yaw_pitch(best_yaw, best_pitch) * muzzle_offset;
                yaw = std::atan2(pred.y - start.y, pred.x - start.x);
            } else {
                Vec2 hd = Vec2(pred.x - pivot.x, pred.y - pivot.y).normalized();
                start = pivot + Vec3(hd.x * muzzle_offset * 0.7, hd.y * muzzle_offset * 0.7, 0.0);
            }
            double dx = pred.x - start.x;
            double dy = pred.y - start.y;
            double R = std::hypot(dx, dy);
            double dz = pred.z - start.z;
            if (R < 0.5) {
                ok = false;
                break;
            }
            double v2 = speed * speed;
            double v4 = v2 * v2;
            double disc = v4 - gravity * (gravity * R * R + 2.0 * dz * v2);
            if (disc < 0.0) {
                ok = false;
                break;
            }
            double sq = std::sqrt(disc);
            double tan_theta = high ? (v2 + sq) / (gravity * R) : (v2 - sq) / (gravity * R);
            double pitch = std::atan(tan_theta);
            if (pitch < min_pitch || pitch > max_pitch) {
                ok = false;
                break;
            }
            double cp = std::cos(pitch);
            if (cp < 1e-4) {
                ok = false;
                break;
            }
            double t_new = R / (speed * cp);
            best_yaw = yaw;
            best_pitch = pitch;
            t_est = 0.5 * t_est + 0.5 * t_new;
        }
        if (ok && t_est > 0.0 && t_est <= 7.0) {
            sols.push_back({best_yaw, best_pitch, t_est, high});
        }
    }
    return sols;
}

} // namespace mf
