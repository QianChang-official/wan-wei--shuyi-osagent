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
//
// 便携 JSON 工具：不依赖 Kylin SDK / GLib / 第三方 JSON 库，可独立编译单测
// （tests/json_util_test.cpp）。sidecar 的请求解析与响应序列化都走这里。
#ifndef WANWEI_ASSISTANT_BRIDGE_JSON_UTIL_H
#define WANWEI_ASSISTANT_BRIDGE_JSON_UTIL_H

#include <cstdint>
#include <string>

namespace wanwei {
namespace json {

namespace detail {

inline void skip_ws(const std::string& s, std::size_t& i) {
    while (i < s.size() && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r')) {
        ++i;
    }
}

inline bool hex4(const std::string& s, std::size_t i, std::uint32_t& out) {
    if (i + 4 > s.size()) {
        return false;
    }
    std::uint32_t value = 0;
    for (std::size_t k = 0; k < 4; ++k) {
        const char c = s[i + k];
        value <<= 4;
        if (c >= '0' && c <= '9') {
            value |= static_cast<std::uint32_t>(c - '0');
        } else if (c >= 'a' && c <= 'f') {
            value |= static_cast<std::uint32_t>(c - 'a' + 10);
        } else if (c >= 'A' && c <= 'F') {
            value |= static_cast<std::uint32_t>(c - 'A' + 10);
        } else {
            return false;
        }
    }
    out = value;
    return true;
}

inline void append_utf8(std::string& out, std::uint32_t cp) {
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

// 解析一个 JSON 字符串字面量（i 指向起始双引号，返回时越过结束双引号）。
// 严格按 JSON 规范：拒绝未转义的 < 0x20 控制字符，正确处理 \\uXXXX 与代理对。
inline bool parse_string(const std::string& s, std::size_t& i, std::string& out) {
    if (i >= s.size() || s[i] != '"') {
        return false;
    }
    ++i;
    while (i < s.size()) {
        const unsigned char c = static_cast<unsigned char>(s[i]);
        if (c == '"') {
            ++i;
            return true;
        }
        if (c < 0x20) {
            return false;  // 裸控制字符：非法 JSON
        }
        if (c != '\\') {
            out.push_back(static_cast<char>(c));
            ++i;
            continue;
        }
        ++i;
        if (i >= s.size()) {
            return false;
        }
        const char esc = s[i++];
        switch (esc) {
            case '"': out.push_back('"'); break;
            case '\\': out.push_back('\\'); break;
            case '/': out.push_back('/'); break;
            case 'b': out.push_back('\b'); break;
            case 'f': out.push_back('\f'); break;
            case 'n': out.push_back('\n'); break;
            case 'r': out.push_back('\r'); break;
            case 't': out.push_back('\t'); break;
            case 'u': {
                std::uint32_t cp = 0;
                if (!hex4(s, i, cp)) {
                    return false;
                }
                i += 4;
                if (cp >= 0xD800 && cp <= 0xDBFF) {
                    // 高代理：必须跟一个低代理
                    if (i + 1 >= s.size() || s[i] != '\\' || s[i + 1] != 'u') {
                        return false;
                    }
                    i += 2;
                    std::uint32_t low = 0;
                    if (!hex4(s, i, low) || low < 0xDC00 || low > 0xDFFF) {
                        return false;
                    }
                    i += 4;
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
                } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
                    return false;  // 孤立低代理
                }
                append_utf8(out, cp);
                break;
            }
            default:
                return false;
        }
    }
    return false;  // 未闭合
}

inline bool skip_value(const std::string& s, std::size_t& i);

inline bool skip_container(const std::string& s, std::size_t& i, char open, char close) {
    if (i >= s.size() || s[i] != open) {
        return false;
    }
    ++i;
    detail::skip_ws(s, i);
    if (i < s.size() && s[i] == close) {
        ++i;
        return true;
    }
    while (i < s.size()) {
        detail::skip_ws(s, i);
        if (open == '{') {
            std::string ignored_key;
            if (!detail::parse_string(s, i, ignored_key)) {
                return false;
            }
            detail::skip_ws(s, i);
            if (i >= s.size() || s[i] != ':') {
                return false;
            }
            ++i;
        }
        detail::skip_ws(s, i);
        if (!detail::skip_value(s, i)) {
            return false;
        }
        detail::skip_ws(s, i);
        if (i < s.size() && s[i] == ',') {
            ++i;
            continue;
        }
        if (i < s.size() && s[i] == close) {
            ++i;
            return true;
        }
        return false;
    }
    return false;
}

inline bool skip_value(const std::string& s, std::size_t& i) {
    if (i >= s.size()) {
        return false;
    }
    const char c = s[i];
    if (c == '"') {
        std::string ignored;
        return detail::parse_string(s, i, ignored);
    }
    if (c == '{') {
        return detail::skip_container(s, i, '{', '}');
    }
    if (c == '[') {
        return detail::skip_container(s, i, '[', ']');
    }
    const std::size_t start = i;
    while (i < s.size() && s[i] != ',' && s[i] != '}' && s[i] != ']' && s[i] != ' ' && s[i] != '\t' &&
           s[i] != '\n' && s[i] != '\r') {
        ++i;
    }
    return i > start;  // 数字/true/false/null 等标量
}

}  // namespace detail

// 转义为合法 JSON 字符串内容（不含外层引号）。控制字符统一转 \uXXXX，
// 保证输出永远是合法 JSON——旧实现会漏出裸控制字符。
inline std::string escape(const std::string& input) {
    static const char* kHex = "0123456789abcdef";
    std::string out;
    out.reserve(input.size() + 8);
    for (unsigned char c : input) {
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
                    out += "\\u00";
                    out.push_back(kHex[(c >> 4) & 0x0F]);
                    out.push_back(kHex[c & 0x0F]);
                } else {
                    out.push_back(static_cast<char>(c));
                }
        }
    }
    return out;
}

// 从 JSON 文档的顶层对象中取字符串字段。键匹配基于解析后的键字符串
// （不是子串搜索），因此「值里含同名字样」或「嵌套对象里的同名键」都不会误命中。
inline bool extract_string(const std::string& document, const std::string& key, std::string& out) {
    std::size_t i = 0;
    detail::skip_ws(document, i);
    if (i >= document.size() || document[i] != '{') {
        return false;
    }
    ++i;
    while (i < document.size()) {
        detail::skip_ws(document, i);
        if (i < document.size() && document[i] == '}') {
            return false;  // 扫描完顶层，未命中
        }
        std::string found_key;
        if (!detail::parse_string(document, i, found_key)) {
            return false;
        }
        detail::skip_ws(document, i);
        if (i >= document.size() || document[i] != ':') {
            return false;
        }
        ++i;
        detail::skip_ws(document, i);
        if (found_key == key) {
            if (i < document.size() && document[i] == '"') {
                return detail::parse_string(document, i, out);
            }
            return false;  // 命中键但值不是字符串
        }
        if (!detail::skip_value(document, i)) {
            return false;
        }
        detail::skip_ws(document, i);
        if (i < document.size() && document[i] == ',') {
            ++i;
            continue;
        }
        if (i < document.size() && document[i] == '}') {
            return false;
        }
        return false;
    }
    return false;
}

// 顶层整数/布尔字段（用于 timeout 等可选开关）。
inline bool extract_int(const std::string& document, const std::string& key, long long& out) {
    std::size_t i = 0;
    detail::skip_ws(document, i);
    if (i >= document.size() || document[i] != '{') {
        return false;
    }
    ++i;
    while (i < document.size()) {
        detail::skip_ws(document, i);
        if (i < document.size() && document[i] == '}') {
            return false;
        }
        std::string found_key;
        if (!detail::parse_string(document, i, found_key)) {
            return false;
        }
        detail::skip_ws(document, i);
        if (i >= document.size() || document[i] != ':') {
            return false;
        }
        ++i;
        detail::skip_ws(document, i);
        if (found_key == key) {
            const std::size_t start = i;
            if (i < document.size() && (document[i] == '-' || document[i] == '+')) {
                ++i;
            }
            while (i < document.size() && document[i] >= '0' && document[i] <= '9') {
                ++i;
            }
            if (i == start) {
                return false;
            }
            try {
                out = std::stoll(document.substr(start, i - start));
            } catch (...) {
                return false;
            }
            return true;
        }
        if (!detail::skip_value(document, i)) {
            return false;
        }
        detail::skip_ws(document, i);
        if (i < document.size() && document[i] == ',') {
            ++i;
            continue;
        }
        return false;
    }
    return false;
}

}  // namespace json
}  // namespace wanwei

#endif  // WANWEI_ASSISTANT_BRIDGE_JSON_UTIL_H
