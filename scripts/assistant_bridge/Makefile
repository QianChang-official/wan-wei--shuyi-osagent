# Copyright (c) 2026 QianChang-official
# Mulan PSL v2
CXX ?= g++
PKGFLAGS := $(shell pkg-config --cflags --libs glib-2.0 gio-2.0)
CXXFLAGS := -I/usr/include/kylin-ai -O2 -Wall

all: wanwei-assistant-sidecar

wanwei-assistant-sidecar: sidecar.cpp
	$(CXX) $(CXXFLAGS) sidecar.cpp -o wanwei-assistant-sidecar -lkyai-assistant -pthread $(PKGFLAGS)

clean:
	rm -f wanwei-assistant-sidecar

.PHONY: all clean
