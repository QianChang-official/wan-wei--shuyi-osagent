# Copyright (c) 2026 QianChang-official
# Mulan PSL v2
#
# 目标说明：
#   make        编译 sidecar（需要麒麟 SDK：sudo apt install libkysdk-ai-private-dev）
#   make check  自检依赖（编译器 / SDK 头文件 / glib pkg-config），缺什么报什么
#   make test   可移植验证：JSON 工具单测 + sidecar 桩头语法检查（CI 同款，无需 SDK）
#   make clean  清理产物
CXX ?= g++
PKGFLAGS := $(shell pkg-config --cflags --libs glib-2.0 gio-2.0)
CXXFLAGS ?= -I/usr/include/kylin-ai -O2 -Wall -Wextra -std=c++17
SDK_HEADER := /usr/include/kylin-ai/private/osassistant/osassistant.h

all: wanwei-assistant-sidecar

wanwei-assistant-sidecar: sidecar.cpp json_util.h
	$(CXX) $(CXXFLAGS) sidecar.cpp -o wanwei-assistant-sidecar -lkyai-assistant -pthread $(PKGFLAGS)

# 依赖自检：SDK 装不上时给出可操作的报错，而不是让编译以晦涩的缺头文件失败
check:
	@command -v $(CXX) >/dev/null || { echo "缺少 C++ 编译器（$(CXX)）"; exit 1; }
	@pkg-config --exists glib-2.0 || { echo "缺少 glib-2.0 开发包（apt install libglib2.0-dev）"; exit 1; }
	@test -f $(SDK_HEADER) || { echo "缺少麒麟 SDK 头文件 $(SDK_HEADER)（apt install libkysdk-ai-private-dev）"; exit 1; }
	@echo "依赖齐备：$(CXX) / glib-2.0 / 麒麟 SDK"

# 可移植验证：不依赖麒麟 SDK，GitHub CI 与本地都可跑（与 tests/ 下的桩头文件配套）
test:
	$(CXX) -std=c++17 -Wall -Wextra -I. tests/json_util_test.cpp -o json_util_test
	./json_util_test
	$(CXX) -std=c++17 -Wall -Wextra -fsyntax-only -Itests/stubs -I. sidecar.cpp
	@echo "可移植验证通过（JSON 单测 + sidecar 语法检查）"

clean:
	rm -f wanwei-assistant-sidecar json_util_test

.PHONY: all check test clean
