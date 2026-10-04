// wanwei-assistant-sidecar: HTTP bridge to Kylin OsAssistant
// API:
//   GET  /health                      -> {"ok":true}
//   POST /chat {"text":"..."}         -> {"reply":"...","length":N,"timed_out":bool}
//   (reply 为流式分片原始 JSON 串的拼接,由 adapter 侧解析出纯文本;
//    服务端硬超时 90s,超时返回已收集内容并置 timed_out=true)
// Copyright (c) 2026 QianChang-official
//
// 宛委·枢忆 is licensed under Mulan PSL v2.
// You can use this software according to the terms of the Mulan PSL v2.
// You may obtain a copy of Mulan PSL v2 at:
// http://license.coscl.org.cn/MulanPSL2
//
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.
#include <kylin-ai/private/osassistant/osassistant.h>
#include <glib.h>
#include <iostream>
#include <string>
#include <sstream>
#include <memory>
#include <atomic>
#include <thread>
#include <chrono>
#include <mutex>
#include <csignal>
#include <cstring>
#include <cstdlib>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <arpa/inet.h>

using namespace kyai::assistant;

static OsAssistant* g_assistant = nullptr;
static std::mutex g_chat_mutex;

// 单次 chat 的共享状态:堆上持有,异步 callback 按值捕获 shared_ptr,
// 防止 90s 硬超时后 OsAssistant 仍派发残留事件时写入已析构的栈对象(UB)。
struct ChatState {
    std::mutex reply_mutex;              // callback 追加与 watcher/响应读取并发防护
    std::string reply;
    std::atomic<bool> done{false};
    std::atomic<bool> timed_out{false};
    std::atomic<guint> timeout_source_id{0};  // 已自删时置 0,避免 g_source_remove 空摘

    size_t reply_size() {
        std::lock_guard<std::mutex> lock(reply_mutex);
        return reply.size();
    }
};

// simple json escape(控制字符转 \u00XX,保证输出恒为合法 JSON)
static std::string jesc(const std::string& s) {
    static const char* HEX = "0123456789abcdef";
    std::string o;
    o.reserve(s.size() + 16);
    for (unsigned char c : s) {
        switch (c) {
            case '"': o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n"; break;
            case '\r': o += "\\r"; break;
            case '\t': o += "\\t"; break;
            default:
                if (c < 0x20) {
                    o += "\\u00";
                    o += HEX[(c >> 4) & 0xf];
                    o += HEX[c & 0xf];
                } else {
                    o += static_cast<char>(c);
                }
        }
    }
    return o;
}

// pos 处引号前连续反斜杠个数(用于判定该引号是否被转义)
static size_t count_trailing_backslashes(const std::string& s, size_t pos) {
    size_t n = 0;
    while (pos > n && s[pos - n - 1] == '\\') ++n;
    return n;
}

// 在 body 中手写提取 "key":"value" 的 value 原文(保留转义序列,无 JSON 库依赖)。
// 限定输入为 adapter 侧 json.dumps 产出的标准 JSON。
static std::string extract_json_string_field(const std::string& body, const char* key) {
    const std::string needle = std::string("\"") + key + "\"";
    size_t key_pos = body.find(needle);
    if (key_pos == std::string::npos) return "";
    size_t colon = body.find(':', key_pos + needle.size());
    if (colon == std::string::npos) return "";          // 防御 find 语义:npos+1 会回绕
    size_t c1 = body.find('"', colon + 1);
    if (c1 == std::string::npos) return "";
    size_t c2 = body.find('"', c1 + 1);
    // 奇数个前导反斜杠 => 引号被转义,继续找下一个真正的结束引号
    while (c2 != std::string::npos && count_trailing_backslashes(body, c2) % 2 == 1)
        c2 = body.find('"', c2 + 1);
    if (c2 == std::string::npos) return "";
    return body.substr(c1 + 1, c2 - c1 - 1);
}

static std::string handle_chat(const std::string& body) {
    std::string text = extract_json_string_field(body, "text");
    if (text.empty()) {
        return "{\"error\":\"text required\"}";
    }

    std::lock_guard<std::mutex> lock(g_chat_mutex);
    auto state = std::make_shared<ChatState>();
    g_assistant->clearContext();
    g_assistant->setChatAsyncCallback([state](const std::string& chunk) {
        std::lock_guard<std::mutex> lock(state->reply_mutex);
        state->reply += chunk;
    });
    // parse text json back for content array
    std::string msg = "{\"content\":[{\"text\":\"" + jesc(text) + "\"}]}";
    g_assistant->chatAsync(msg);

    // glib mainloop pump in this thread, hard timeout 90s
    GMainLoop* loop = g_main_loop_new(nullptr, FALSE);
    guint timeout_id = g_timeout_add_seconds(90, [](gpointer data) -> gboolean {
        auto* st = static_cast<ChatState*>(data);
        st->timed_out.store(true);
        st->done.store(true);               // watcher 线程感知后统一 quit,本回调不碰 loop
        st->timeout_source_id.store(0);     // 自删标记
        return G_SOURCE_REMOVE;
    }, state.get());
    state->timeout_source_id.store(timeout_id);

    // mark done when reply stops growing for ~2.1s (streaming finished heuristic)
    std::thread watcher([state, loop]() {
        size_t last = 0; int stable = 0;
        while (!state->done.load() && stable < 7) {
            std::this_thread::sleep_for(std::chrono::milliseconds(300));
            size_t cur = state->reply_size();
            if (cur == last) stable++; else stable = 0;
            last = cur;
        }
        state->done.store(true);
        g_main_loop_quit(loop);             // 线程安全,run 返回后不再依赖 loop
    });
    g_main_loop_run(loop);
    watcher.join();

    // 移除未触发的 90s 定时器 source:它仍挂在默认 context 上,
    // 若放任存活,下次任何线程 pump 默认 context 时会引用已 unref 的 loop(UAF)。
    guint pending = state->timeout_source_id.exchange(0);
    if (pending != 0) g_source_remove(pending);
    g_main_loop_unref(loop);                // 修复:原实现每请求泄漏一个 GMainLoop

    std::string full_reply;
    {
        std::lock_guard<std::mutex> lock(state->reply_mutex);
        full_reply = state->reply;
    }
    std::ostringstream oss;
    oss << "{\"reply\":\"" << jesc(full_reply)
        << "\",\"length\":" << full_reply.size()
        << ",\"timed_out\":" << (state->timed_out.load() ? "true" : "false") << "}";
    return oss.str();
}

// 读满整个请求:headers + Content-Length 指定的 body。
// 仅凭 "\r\n\r\n" 出现就停止 recv 会截断分段到达的 POST body。
static bool http_read_request(int client, std::string& req) {
    char buf[65536];
    size_t header_end = std::string::npos;
    size_t content_length = 0;
    while (true) {
        if (header_end == std::string::npos) {
            size_t pos = req.find("\r\n\r\n");
            if (pos != std::string::npos) {
                header_end = pos + 4;
                size_t cl = req.find("Content-Length:");
                if (cl == std::string::npos) cl = req.find("content-length:");
                if (cl != std::string::npos)
                    content_length = static_cast<size_t>(
                        std::strtoul(req.c_str() + cl + 15, nullptr, 10));
            }
        }
        if (header_end != std::string::npos &&
            req.size() - header_end >= content_length)
            return true;
        int n = recv(client, buf, sizeof(buf), 0);
        if (n <= 0)
            return header_end != std::string::npos &&
                   req.size() - header_end >= content_length;
        req.append(buf, static_cast<size_t>(n));
        if (req.size() > (1u << 20)) return false;   // 1MB 防护
    }
}

int main() {
    // 客户端提前断开时 send 会触发 SIGPIPE 并杀死整个 sidecar,
    // 演示现场手机 H5 刷新/断连是常态,必须忽略交由 errno 处理。
    std::signal(SIGPIPE, SIG_IGN);

    // 端口可用环境变量覆盖（同一台机器并行演示多套时避免 8021 冲突）
    int port = 8021;
    if (const char* envPort = std::getenv("WANWEI_SIDECAR_PORT"); envPort && *envPort) {
        port = std::atoi(envPort);
        if (port < 1 || port > 65535) {
            std::cerr << "{\"fatal\":\"WANWEI_SIDECAR_PORT out of range (1-65535)\"}" << std::endl;
            return 1;
        }
    }

    // assistant init on main thread (glib context)
    g_assistant = new OsAssistant();
    Error err = g_assistant->init();
    if (err) {
        std::cerr << "{\"fatal\":\"assistant init failed\"}" << std::endl;
        return 1;
    }
    std::cerr << "{\"ready\":true}" << std::endl;

    int server = socket(AF_INET, SOCK_STREAM, 0);
    if (server < 0) {
        std::cerr << "{\"fatal\":\"socket failed\"}" << std::endl;
        return 1;
    }
    int opt = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");
    addr.sin_port = htons(static_cast<uint16_t>(port));
    if (bind(server, (sockaddr*)&addr, sizeof(addr)) < 0) {
        std::cerr << "{\"fatal\":\"bind failed\",\"port\":" << port << "}" << std::endl;
        return 1;
    }
    listen(server, 8);
    std::cerr << "{\"listening\":" << port << "}" << std::endl;

    while (true) {
        int client = accept(server, nullptr, nullptr);
        if (client < 0) continue;
        std::thread([client]() {
            std::string req;
            std::string resp_body;
            const char* status = "200 OK";
            if (!http_read_request(client, req)) {
                resp_body = "{\"error\":\"malformed request\"}";
                status = "400 Bad Request";
            } else if (req.find("GET /health") == 0) {
                resp_body = "{\"ok\":true}";
            } else if (req.find("POST /chat") == 0) {
                size_t pos = req.find("\r\n\r\n");
                std::string body = pos == std::string::npos ? "" : req.substr(pos + 4);
                resp_body = handle_chat(body);
                // handle_chat 的参数错误（如缺 text）以 400 如实返回
                if (resp_body.rfind("{\"error\"", 0) == 0) status = "400 Bad Request";
            } else {
                resp_body = "{\"error\":\"not found\"}";
                status = "404 Not Found";
            }
            std::string http = std::string("HTTP/1.1 ") + status + "\r\nContent-Type: application/json\r\nContent-Length: "
                + std::to_string(resp_body.size()) + "\r\nConnection: close\r\n\r\n" + resp_body;
            send(client, http.c_str(), http.size(), 0);
            close(client);
        }).detach();
    }
}
