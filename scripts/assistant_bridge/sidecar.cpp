// Copyright (c) 2026 QianChang-official
#
// 宛委·枢忆 is licensed under Mulan PSL v2.
// You can use this software according to the terms of the Mulan PSL v2.
// You may obtain a copy of the Mulan PSL v2 at:
// http://license.coscl.org.cn/MulanPSL2
#
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.
// wanwei-assistant-sidecar: HTTP bridge to Kylin OsAssistant
// POST /chat {"text":"...", "timeout":60} -> {"reply":"...", "chunks":N, "elapsed":S}
#include <kylin-ai/private/osassistant/osassistant.h>
#include <glib.h>
#include <iostream>
#include <string>
#include <sstream>
#include <atomic>
#include <thread>
#include <chrono>
#include <mutex>
#include <cstring>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <arpa/inet.h>

using namespace kyai::assistant;

static OsAssistant* g_assistant = nullptr;
static std::mutex g_chat_mutex;

static std::string http_get_body(const std::string& req) {
    size_t pos = req.find("\r\n\r\n");
    return pos == std::string::npos ? "" : req.substr(pos + 4);
}

// simple json escape
static std::string jesc(const std::string& s) {
    std::string o;
    for (char c : s) {
        switch (c) {
            case '"': o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n"; break;
            case '\r': o += "\\r"; break;
            case '\t': o += "\\t"; break;
            default: o += c;
        }
    }
    return o;
}

static std::string handle_chat(const std::string& body) {
    // parse {"text":"..."} - find "text" field manually (no json lib)
    std::string text;
    size_t tp = body.find("\"text\"");
    if (tp != std::string::npos) {
        size_t c1 = body.find('"', body.find(':', tp) + 1);
        size_t c2 = body.find('"', c1 + 1);
        while (c2 != std::string::npos && body[c2-1] == '\\') c2 = body.find('"', c2 + 1);
        if (c1 != std::string::npos && c2 != std::string::npos)
            text = body.substr(c1 + 1, c2 - c1 - 1);
    }
    if (text.empty()) {
        return "{\"error\":\"text required\"}";
    }

    std::lock_guard<std::mutex> lock(g_chat_mutex);
    g_assistant->clearContext();
    std::atomic<bool> done{false};
    std::string full_reply;

    g_assistant->setChatAsyncCallback([&](const std::string& chunk) {
        full_reply += chunk;
    });
    // parse text json back for content array
    std::string msg = "{\"content\":[{\"text\":\"" + jesc(text) + "\"}]}";
    g_assistant->chatAsync(msg);

    // glib mainloop pump in this thread with timeout 90s
    GMainLoop* loop = g_main_loop_new(nullptr, FALSE);
    struct Ctx { GMainLoop* loop; std::atomic<bool>* done; };
    Ctx ctx{loop, &done};
    g_timeout_add(300, [](gpointer data) -> gboolean {
        Ctx* c = (Ctx*)data;
        if (*(c->done)) { g_main_loop_quit(c->loop); return G_SOURCE_REMOVE; }
        return G_SOURCE_CONTINUE;
    }, &ctx);
    g_timeout_add_seconds(90, [](gpointer data) -> gboolean {
        g_main_loop_quit((GMainLoop*)data);
        return G_SOURCE_REMOVE;
    }, loop);
    // mark done when reply stops growing for 2s (streaming finished heuristic)
    std::thread watcher([&]() {
        size_t last = 0; int stable = 0;
        while (!done && stable < 7) {
            std::this_thread::sleep_for(std::chrono::milliseconds(300));
            if (full_reply.size() == last) stable++; else stable = 0;
            last = full_reply.size();
        }
        done = true;
        g_main_loop_quit(loop);
    });
    g_main_loop_run(loop);
    watcher.join();

    std::ostringstream oss;
    oss << "{\"reply\":\"" << jesc(full_reply) << "\",\"length\":" << full_reply.size() << "}";
    return oss.str();
}

int main() {
    // assistant init on main thread (glib context)
    g_assistant = new OsAssistant();
    Error err = g_assistant->init();
    if (err) {
        std::cerr << "{\"fatal\":\"assistant init failed\"}" << std::endl;
        return 1;
    }
    std::cerr << "{\"ready\":true}" << std::endl;

    int server = socket(AF_INET, SOCK_STREAM, 0);
    int opt = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");
    addr.sin_port = htons(8021);
    if (bind(server, (sockaddr*)&addr, sizeof(addr)) < 0) {
        std::cerr << "{\"fatal\":\"bind 8021 failed\"}" << std::endl;
        return 1;
    }
    listen(server, 8);
    std::cerr << "{\"listening\":8021}" << std::endl;

    while (true) {
        int client = accept(server, nullptr, nullptr);
        if (client < 0) continue;
        std::thread([client]() {
            char buf[65536];
            std::string req;
            while (req.find("\r\n\r\n") == std::string::npos) {
                int n = recv(client, buf, sizeof(buf), 0);
                if (n <= 0) break;
                req.append(buf, n);
                if (req.size() > 1<<20) break;
            }
            std::string body = http_get_body(req);
            std::string resp_body;
            if (req.find("GET /health") == 0) {
                resp_body = "{\"ok\":true}";
            } else if (req.find("POST /chat") == 0) {
                resp_body = handle_chat(body);
            } else {
                resp_body = "{\"error\":\"not found\"}";
            }
            std::string headers = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n";
            headers += "Content-Length: " + std::to_string(resp_body.size());
            headers += "\r\nConnection: close\r\n\r\n";
            std::string http = headers + resp_body;
            send(client, http.c_str(), http.size(), 0);
            close(client);
        }).detach();
    }
}
