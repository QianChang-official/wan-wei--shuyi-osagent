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


// 召回宛委记忆(调宛委HTTP API,curl子进程;返回拼接的记忆上下文,失败返回空)
static std::string recall_wanwei_memory(const std::string& text) {
    // 组装command请求体
    std::string esc;
    for (char c : text) {
        if (c == '"' ) esc += "\\\""; else if (c=='\\') esc += "\\\\"; else esc += c;
    }
    std::string payload = "{\"goal\":\"" + esc + "\"}";
    std::string cmd = "KEY=$(cat ~/.config/wanwei-shuyi-desktop/api-key 2>/dev/null); "
                      "curl -s -m 20 -X POST http://127.0.0.1:8010/memory/v2/command "
                      "-H 'Content-Type: application/json' -H \"X-API-Key: $KEY\" --data '" + payload + "'";
    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe) return "";
    std::string out;
    char buf[4096];
    while (fgets(buf, sizeof(buf), pipe)) out += buf;
    pclose(pipe);
    if (out.empty()) return "";
    // 从返回JSON里抽 recalled_memories 的 content 文本(简易截取,不做完整JSON解析)
    std::string ctx;
    size_t pos = 0;
    while (true) {
        size_t pv = out.find("\"preference_value\" : \"", pos);
        size_t ls = out.find("\"lessons\" : \"", pos);
        size_t st = out.find("\"statement\" : \"", pos);
        size_t best = std::string::npos; size_t len = 0; std::string which;
        auto pick = [&](size_t v, const char* w){ if (v != std::string::npos && (best==std::string::npos || v<best)) { best=v; which=w; } };
        pick(pv, "preference_value"); pick(ls, "lessons"); pick(st, "statement");
        if (best == std::string::npos) break;
        size_t start = best + strlen("\"X\" : \"") - 3;
        start = out.find('"', best) + 1;
        size_t end = out.find("\"", start);
        if (end == std::string::npos) break;
        ctx += "- " + which + ": " + out.substr(start, end-start) + "\n";
        pos = end + 1;
    }
    return ctx;
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
    std::string memory_ctx = recall_wanwei_memory(text);
    std::string final_text = text;
    if (!memory_ctx.empty()) {
        final_text = "[系统提示]以下是用户的历史偏好记忆,回答时请优先遵循这些偏好,并可向用户确认是否正确:\n" + memory_ctx + "\n[用户问题]" + text;
    }
    std::atomic<bool> done{false};
    std::string full_reply;

    g_assistant->setChatAsyncCallback([&](const std::string& chunk) {
        full_reply += chunk;
    });
    // parse text json back for content array
    std::string msg = "{\"content\":[{\"text\":\"" + jesc(final_text) + "\"}]}";
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
