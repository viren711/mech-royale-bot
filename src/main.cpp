#include "bot.hpp"
#include "json.hpp"
#include <condition_variable>
#include <cstdio>
#include <deque>
#include <exception>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#define READ_FD(fd, buf, sz) _read((fd), (buf), static_cast<unsigned int>(sz))
#else
#include <unistd.h>
#define READ_FD(fd, buf, sz) ::read((fd), (buf), (sz))
#endif

namespace {

struct LineQueue {
    std::mutex mu;
    std::condition_variable cv;
    std::deque<std::string> lines;
    bool eof = false;

    void push_batch(std::vector<std::string>& batch) {
        if (batch.empty()) return;
        {
            std::lock_guard<std::mutex> lk(mu);
            for (auto& s : batch) lines.push_back(std::move(s));
        }
        cv.notify_one();
    }

    void mark_eof() {
        {
            std::lock_guard<std::mutex> lk(mu);
            eof = true;
        }
        cv.notify_one();
    }

    bool drain(std::vector<std::string>& out, bool& out_eof) {
        std::unique_lock<std::mutex> lk(mu);
        cv.wait(lk, [&] { return !lines.empty() || eof; });
        while (!lines.empty()) {
            out.push_back(std::move(lines.front()));
            lines.pop_front();
        }
        out_eof = eof;
        return !out.empty();
    }
};

void reader_thread_fn(LineQueue* q) {
    char buf[65536];
    std::string carry;
    std::vector<std::string> batch;
    while (true) {
        auto n = READ_FD(0, buf, sizeof(buf));
        if (n <= 0) break;
        carry.append(buf, static_cast<size_t>(n));
        batch.clear();
        size_t pos = 0;
        while (true) {
            size_t nl = carry.find('\n', pos);
            if (nl == std::string::npos) break;
            size_t len = nl - pos;
            if (len > 0 && carry[pos + len - 1] == '\r') --len;
            if (len > 0) batch.emplace_back(carry, pos, len);
            pos = nl + 1;
        }
        if (pos > 0) carry.erase(0, pos);
        if (!batch.empty()) q->push_batch(batch);
    }
    if (!carry.empty()) {
        while (!carry.empty() && (carry.back() == '\r' || carry.back() == '\n')) carry.pop_back();
        if (!carry.empty()) {
            std::vector<std::string> last_b{std::move(carry)};
            q->push_batch(last_b);
        }
    }
    q->mark_eof();
}

void write_line(const std::string& s) {
    std::fwrite(s.data(), 1, s.size(), stdout);
    std::fputc('\n', stdout);
    std::fflush(stdout);
}

} // namespace

int main() {
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    LineQueue queue;
    std::thread reader(reader_thread_fn, &queue);
    reader.detach();

    mf::Bot bot;
    mf::Json last_safe_continuous = mf::Json::object();
    int error_count = 0;
    std::vector<std::string> batch;

    while (true) {
        batch.clear();
        bool eof = false;
        if (!queue.drain(batch, eof)) {
            if (eof) break;
            continue;
        }

        bool saw_end = false;
        mf::Json latest_obs;
        bool has_obs = false;

        for (const std::string& raw : batch) {
            mf::Json msg;
            if (!mf::Json::try_parse(raw, msg) || !msg.is_object()) continue;
            const std::string& tp = msg["type"].as_str();
            if (tp == "hello") {
                try {
                    bot.init(msg);
                } catch (const std::exception& e) {
                    std::fprintf(stderr, "init error: %s\n", e.what());
                    std::fflush(stderr);
                } catch (...) {
                    std::fprintf(stderr, "unknown init error\n");
                    std::fflush(stderr);
                }
                mf::Json ready = mf::Json::object();
                ready.set("type", "ready");
                ready.set("name", bot.name);
                write_line(ready.dump());
            } else if (tp == "obs") {
                latest_obs = std::move(msg);
                has_obs = true;
            } else if (tp == "end") {
                saw_end = true;
            }
        }

        if (saw_end) break;
        if (!has_obs) {
            if (eof) break;
            continue;
        }

        mf::Json action;
        try {
            action = bot.act(latest_obs);
            last_safe_continuous = mf::Json::object();
            if (action.has("move")) last_safe_continuous.set("move", action["move"]);
            if (action.has("aim")) last_safe_continuous.set("aim", action["aim"]);
            if (action.has("boost")) last_safe_continuous.set("boost", action["boost"]);
        } catch (const std::exception& e) {
            ++error_count;
            if (error_count <= 5) {
                std::fprintf(stderr, "act error at tick %lld: %s\n",
                             static_cast<long long>(latest_obs["tick"].as_i64(0)), e.what());
                std::fflush(stderr);
            }
            action = last_safe_continuous;
            action.set("type", "action");
            action.set("tick", latest_obs["tick"].as_i64(0));
        } catch (...) {
            action = last_safe_continuous;
            action.set("type", "action");
            action.set("tick", latest_obs["tick"].as_i64(0));
        }

        write_line(action.dump());
        if (eof) break;
    }

    return 0;
}
