#pragma once

#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace mf {

struct Json {
    enum class Type : uint8_t { Null, Bool, Number, String, Array, Object };

    using Array = std::vector<Json>;
    using Object = std::vector<std::pair<std::string, Json>>;

    Type type = Type::Null;
    bool bool_val = false;
    double num_val = 0.0;
    std::string str_val;
    Array arr_val;
    Object obj_val;

    Json() : type(Type::Null) {}
    Json(std::nullptr_t) : type(Type::Null) {}
    Json(bool b) : type(Type::Bool), bool_val(b) {}
    Json(int v) : type(Type::Number), num_val(static_cast<double>(v)) {}
    Json(int64_t v) : type(Type::Number), num_val(static_cast<double>(v)) {}
    Json(double d) : type(Type::Number), num_val(std::isfinite(d) ? d : 0.0) {}
    Json(const char* s) : type(Type::String), str_val(s ? s : "") {}
    Json(std::string s) : type(Type::String), str_val(std::move(s)) {}
    Json(Array a) : type(Type::Array), arr_val(std::move(a)) {}
    Json(Object o) : type(Type::Object), obj_val(std::move(o)) {}

    static Json array() {
        Json j;
        j.type = Type::Array;
        return j;
    }

    static Json object() {
        Json j;
        j.type = Type::Object;
        return j;
    }

    static const Json& null_ref() {
        static const Json kNull;
        return kNull;
    }

    bool is_null() const { return type == Type::Null; }
    bool is_bool() const { return type == Type::Bool; }
    bool is_number() const { return type == Type::Number; }
    bool is_string() const { return type == Type::String; }
    bool is_array() const { return type == Type::Array; }
    bool is_object() const { return type == Type::Object; }

    double as_double(double def = 0.0) const {
        return (type == Type::Number && std::isfinite(num_val)) ? num_val : def;
    }
    int as_int(int def = 0) const {
        return (type == Type::Number && std::isfinite(num_val)) ? static_cast<int>(std::llround(num_val)) : def;
    }
    int64_t as_i64(int64_t def = 0) const {
        return (type == Type::Number && std::isfinite(num_val)) ? static_cast<int64_t>(std::llround(num_val)) : def;
    }
    bool as_bool(bool def = false) const {
        return type == Type::Bool ? bool_val : def;
    }
    const std::string& as_str() const {
        static const std::string kEmpty;
        return type == Type::String ? str_val : kEmpty;
    }
    std::string as_str(const std::string& def) const {
        return type == Type::String ? str_val : def;
    }

    const Json* find(const char* key) const {
        if (type != Type::Object) return nullptr;
        for (const auto& kv : obj_val) {
            if (kv.first == key) return &kv.second;
        }
        return nullptr;
    }

    const Json* find(const std::string& key) const {
        return find(key.c_str());
    }

    bool has(const char* key) const {
        return find(key) != nullptr;
    }

    const Json& operator[](const char* key) const {
        const Json* p = find(key);
        return p ? *p : null_ref();
    }

    const Json& operator[](const std::string& key) const {
        return (*this)[key.c_str()];
    }

    const Json& operator[](size_t idx) const {
        if (type != Type::Array || idx >= arr_val.size()) return null_ref();
        return arr_val[idx];
    }

    const Json& operator[](int idx) const {
        if (idx < 0) return null_ref();
        return (*this)[static_cast<size_t>(idx)];
    }

    Json& set(std::string key, Json val) {
        if (type != Type::Object) {
            type = Type::Object;
            obj_val.clear();
        }
        for (auto& kv : obj_val) {
            if (kv.first == key) {
                kv.second = std::move(val);
                return *this;
            }
        }
        obj_val.emplace_back(std::move(key), std::move(val));
        return *this;
    }

    void push(Json val) {
        if (type != Type::Array) {
            type = Type::Array;
            arr_val.clear();
        }
        arr_val.push_back(std::move(val));
    }

    static void append_escaped(std::string& out, const std::string& s) {
        out.push_back('"');
        for (unsigned char c : s) {
            switch (c) {
                case '"': out += "\\\""; break;
                case '\\': out += "\\\\"; break;
                case '\b': out += "\\b"; break;
                case '\f': out += "\\f"; break;
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (c < 0x20) {
                        char buf[8];
                        std::snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned>(c));
                        out += buf;
                    } else {
                        out.push_back(static_cast<char>(c));
                    }
                    break;
            }
        }
        out.push_back('"');
    }

    void serialize(std::string& out) const {
        switch (type) {
            case Type::Null:
                out += "null";
                break;
            case Type::Bool:
                out += (bool_val ? "true" : "false");
                break;
            case Type::Number: {
                double v = std::isfinite(num_val) ? num_val : 0.0;
                if (std::abs(v) < 1e-12) v = 0.0;
                if (v == std::floor(v) && std::abs(v) < 9e15) {
                    char buf[32];
                    std::snprintf(buf, sizeof(buf), "%lld", static_cast<long long>(v));
                    out += buf;
                } else {
                    char buf[48];
                    std::snprintf(buf, sizeof(buf), "%.9g", v);
                    out += buf;
                }
                break;
            }
            case Type::String:
                append_escaped(out, str_val);
                break;
            case Type::Array:
                out.push_back('[');
                for (size_t i = 0; i < arr_val.size(); ++i) {
                    if (i > 0) out.push_back(',');
                    arr_val[i].serialize(out);
                }
                out.push_back(']');
                break;
            case Type::Object:
                out.push_back('{');
                for (size_t i = 0; i < obj_val.size(); ++i) {
                    if (i > 0) out.push_back(',');
                    append_escaped(out, obj_val[i].first);
                    out.push_back(':');
                    obj_val[i].second.serialize(out);
                }
                out.push_back('}');
                break;
        }
    }

    std::string dump() const {
        std::string out;
        out.reserve(256);
        serialize(out);
        return out;
    }

    class Parser {
    public:
        explicit Parser(const char* data, size_t len) : p_(data), end_(data + len) {}

        Json parse_root() {
            skip_ws();
            Json v = parse_value();
            skip_ws();
            if (p_ != end_) {
                throw std::runtime_error("Trailing characters in JSON");
            }
            return v;
        }

    private:
        const char* p_;
        const char* end_;

        void skip_ws() {
            while (p_ < end_ && (*p_ == ' ' || *p_ == '\t' || *p_ == '\n' || *p_ == '\r')) {
                ++p_;
            }
        }

        char peek() const {
            return p_ < end_ ? *p_ : '\0';
        }

        char get() {
            if (p_ >= end_) throw std::runtime_error("Unexpected end of JSON");
            return *p_++;
        }

        Json parse_value() {
            skip_ws();
            if (p_ >= end_) throw std::runtime_error("Unexpected EOF in JSON value");
            char c = *p_;
            if (c == '{') return parse_object();
            if (c == '[') return parse_array();
            if (c == '"') return Json(parse_string());
            if (c == 't') {
                if (end_ - p_ >= 4 && std::memcmp(p_, "true", 4) == 0) {
                    p_ += 4;
                    return Json(true);
                }
                throw std::runtime_error("Invalid token near 't'");
            }
            if (c == 'f') {
                if (end_ - p_ >= 5 && std::memcmp(p_, "false", 5) == 0) {
                    p_ += 5;
                    return Json(false);
                }
                throw std::runtime_error("Invalid token near 'f'");
            }
            if (c == 'n') {
                if (end_ - p_ >= 4 && std::memcmp(p_, "null", 4) == 0) {
                    p_ += 4;
                    return Json(nullptr);
                }
                throw std::runtime_error("Invalid token near 'n'");
            }
            if (c == '-' || (c >= '0' && c <= '9')) {
                return parse_number();
            }
            throw std::runtime_error("Unexpected character in JSON");
        }

        static uint32_t parse_hex4(const char*& p, const char* end) {
            if (end - p < 4) throw std::runtime_error("Truncated \\u escape");
            uint32_t val = 0;
            for (int i = 0; i < 4; ++i) {
                char c = p[i];
                val <<= 4;
                if (c >= '0' && c <= '9') val |= (c - '0');
                else if (c >= 'a' && c <= 'f') val |= (c - 'a' + 10);
                else if (c >= 'A' && c <= 'F') val |= (c - 'A' + 10);
                else throw std::runtime_error("Invalid hex in \\u escape");
            }
            p += 4;
            return val;
        }

        static void append_utf8(std::string& out, uint32_t cp) {
            if (cp <= 0x7F) {
                out.push_back(static_cast<char>(cp));
            } else if (cp <= 0x7FF) {
                out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
                out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
            } else if (cp <= 0xFFFF) {
                out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
                out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
                out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
            } else {
                out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
                out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
                out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
                out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
            }
        }

        std::string parse_string() {
            if (get() != '"') throw std::runtime_error("Expected '\"'");
            std::string s;
            while (p_ < end_) {
                char c = *p_++;
                if (c == '"') return s;
                if (c == '\\') {
                    char e = get();
                    switch (e) {
                        case '"': s.push_back('"'); break;
                        case '\\': s.push_back('\\'); break;
                        case '/': s.push_back('/'); break;
                        case 'b': s.push_back('\b'); break;
                        case 'f': s.push_back('\f'); break;
                        case 'n': s.push_back('\n'); break;
                        case 'r': s.push_back('\r'); break;
                        case 't': s.push_back('\t'); break;
                        case 'u': {
                            uint32_t cp = parse_hex4(p_, end_);
                            if (cp >= 0xD800 && cp <= 0xDBFF && end_ - p_ >= 2 && p_[0] == '\\' && p_[1] == 'u') {
                                p_ += 2;
                                uint32_t lo = parse_hex4(p_, end_);
                                if (lo >= 0xDC00 && lo <= 0xDFFF) {
                                    cp = 0x10000 + (((cp - 0xD800) << 10) | (lo - 0xDC00));
                                }
                            }
                            append_utf8(s, cp);
                            break;
                        }
                        default: throw std::runtime_error("Invalid escape sequence");
                    }
                } else {
                    s.push_back(c);
                }
            }
            throw std::runtime_error("Unterminated string");
        }

        Json parse_number() {
            const char* start = p_;
            if (*p_ == '-') ++p_;
            if (p_ >= end_) throw std::runtime_error("Invalid number");
            if (*p_ == '0') {
                ++p_;
            } else if (*p_ >= '1' && *p_ <= '9') {
                while (p_ < end_ && *p_ >= '0' && *p_ <= '9') ++p_;
            } else {
                throw std::runtime_error("Invalid number digit");
            }
            if (p_ < end_ && *p_ == '.') {
                ++p_;
                if (p_ >= end_ || *p_ < '0' || *p_ > '9') throw std::runtime_error("Invalid fraction");
                while (p_ < end_ && *p_ >= '0' && *p_ <= '9') ++p_;
            }
            if (p_ < end_ && (*p_ == 'e' || *p_ == 'E')) {
                ++p_;
                if (p_ < end_ && (*p_ == '+' || *p_ == '-')) ++p_;
                if (p_ >= end_ || *p_ < '0' || *p_ > '9') throw std::runtime_error("Invalid exponent");
                while (p_ < end_ && *p_ >= '0' && *p_ <= '9') ++p_;
            }
            std::string tmp(start, static_cast<size_t>(p_ - start));
            char* parse_end = nullptr;
            double v = std::strtod(tmp.c_str(), &parse_end);
            if (!std::isfinite(v)) v = 0.0;
            return Json(v);
        }

        Json parse_array() {
            get(); // '['
            Json j = Json::array();
            skip_ws();
            if (peek() == ']') {
                get();
                return j;
            }
            while (true) {
                j.arr_val.push_back(parse_value());
                skip_ws();
                char c = get();
                if (c == ']') break;
                if (c != ',') throw std::runtime_error("Expected ',' or ']' in array");
            }
            return j;
        }

        Json parse_object() {
            get(); // '{'
            Json j = Json::object();
            skip_ws();
            if (peek() == '}') {
                get();
                return j;
            }
            while (true) {
                skip_ws();
                std::string key = parse_string();
                skip_ws();
                if (get() != ':') throw std::runtime_error("Expected ':' in object");
                Json val = parse_value();
                j.obj_val.emplace_back(std::move(key), std::move(val));
                skip_ws();
                char c = get();
                if (c == '}') break;
                if (c != ',') throw std::runtime_error("Expected ',' or '}' in object");
            }
            return j;
        }
    };

    static Json parse(const std::string& text) {
        Parser p(text.data(), text.size());
        return p.parse_root();
    }

    static bool try_parse(const std::string& text, Json& out) {
        try {
            out = parse(text);
            return true;
        } catch (...) {
            return false;
        }
    }
};

} // namespace mf
