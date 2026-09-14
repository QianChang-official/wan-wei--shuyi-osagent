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
// json_util.h 的独立单元测试（不依赖 Kylin SDK / GLib，可在任意 CI 编译运行）：
//   g++ -std=c++17 -I.. json_util_test.cpp -o json_util_test && ./json_util_test
#include "../json_util.h"

#include <cstdio>
#include <string>

namespace {

int g_failures = 0;

void check(bool condition, const char* what) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", what);
        ++g_failures;
    }
}

void check_eq(const std::string& actual, const std::string& expected, const char* what) {
    if (actual != expected) {
        std::fprintf(stderr, "FAIL: %s\n  expected: [%s]\n  actual:   [%s]\n", what, expected.c_str(),
                     actual.c_str());
        ++g_failures;
    }
}

void test_escape_control_characters() {
    // 裸控制字符必须被转义，否则响应不是合法 JSON（旧实现漏掉这一条）
    check_eq(wanwei::json::escape(std::string("a\x01\x1f""b")), "a\\u0001\\u001fb", "escape control chars");
    check_eq(wanwei::json::escape("line1\nline2"), "line1\\nline2", "escape newline");
    check_eq(wanwei::json::escape("say \"hi\""), "say \\\"hi\\\"", "escape quote");
    check_eq(wanwei::json::escape("back\\slash"), "back\\\\slash", "escape backslash");
    check_eq(wanwei::json::escape("\r\t\b\f"), "\\r\\t\\b\\f", "escape shorthands");
    check_eq(wanwei::json::escape("中文 UTF-8"), "中文 UTF-8", "utf8 passthrough");
}

void test_extract_simple() {
    std::string out;
    check(wanwei::json::extract_string("{\"text\":\"你好\"}", "text", out), "extract simple");
    check_eq(out, "你好", "extract simple value");

    out.clear();
    check(wanwei::json::extract_string("  {  \"text\" : \"hi\" , \"timeout\" : 60 }  ", "text", out), "extract with ws");
    check_eq(out, "hi", "extract with ws value");
}

void test_extract_decodes_escapes() {
    std::string out;
    // 转义引号：旧实现的子串裁剪会把 \" 原样带出去
    check(wanwei::json::extract_string("{\"text\":\"say \\\"hi\\\"\"}", "text", out), "extract escaped quote");
    check_eq(out, "say \"hi\"", "escaped quote decoded");

    out.clear();
    check(wanwei::json::extract_string("{\"text\":\"line1\\nline2\"}", "text", out), "extract escaped newline");
    check_eq(out, "line1\nline2", "escaped newline decoded");

    out.clear();
    check(wanwei::json::extract_string("{\"text\":\"\\u4f60\\u597d\"}", "text", out), "extract \\u escapes");
    check_eq(out, "你好", "bmp \\u decoded");

    out.clear();
    check(wanwei::json::extract_string("{\"text\":\"\\ud83d\\ude00\"}", "text", out), "extract surrogate pair");
    check_eq(out, "\xf0\x9f\x98\x80", "surrogate pair decoded");
}

void test_key_not_confused_by_values_or_nesting() {
    std::string out;
    // 值里出现 "text" 字样：旧实现的 body.find("\"text\"") 会在这里误命中
    check(wanwei::json::extract_string("{\"prompt\":\"please set \\\"text\\\" field\", \"text\":\"real\"}", "text", out),
          "value containing key text");
    check_eq(out, "real", "value containing key text -> real match");

    out.clear();
    // 嵌套对象里的同名键不应命中顶层
    check(wanwei::json::extract_string("{\"outer\":{\"text\":\"nested\"},\"text\":\"top\"}", "text", out),
          "nested same-name key skipped");
    check_eq(out, "top", "nested same-name key -> top level");
}

void test_rejects_malformed() {
    std::string out;
    check(!wanwei::json::extract_string("", "text", out), "reject empty");
    check(!wanwei::json::extract_string("[]", "text", out), "reject array root");
    check(!wanwei::json::extract_string("{\"text\":\"unterminated}", "text", out), "reject unterminated string");
    check(!wanwei::json::extract_string("{\"text\":\"raw\x01control\"}", "text", out), "reject raw control");
    check(!wanwei::json::extract_string("{\"text\":123}", "text", out), "reject non-string value");
    check(!wanwei::json::extract_string("{\"other\":\"x\"}", "text", out), "reject missing key");
    check(!wanwei::json::extract_string("{\"text\":\"\\ud83d\"}", "text", out), "reject lone high surrogate");
    check(!wanwei::json::extract_string("{\"text\":\"\\udc00\"}", "text", out), "reject lone low surrogate");
}

void test_extract_int() {
    long long value = 0;
    check(wanwei::json::extract_int("{\"timeout\":60}", "timeout", value), "extract int");
    check(value == 60, "extract int value");

    check(wanwei::json::extract_int("{\"text\":\"x\", \"timeout\": -5}", "timeout", value), "extract negative int");
    check(value == -5, "extract negative int value");

    check(!wanwei::json::extract_int("{\"timeout\":\"60\"}", "timeout", value), "reject quoted int");
    check(!wanwei::json::extract_int("{\"text\":\"x\"}", "timeout", value), "reject missing int");
}

}  // namespace

int main() {
    test_escape_control_characters();
    test_extract_simple();
    test_extract_decodes_escapes();
    test_key_not_confused_by_values_or_nesting();
    test_rejects_malformed();
    test_extract_int();

    if (g_failures == 0) {
        std::printf("json_util_test: all checks passed\n");
        return 0;
    }
    std::fprintf(stderr, "json_util_test: %d failure(s)\n", g_failures);
    return 1;
}
