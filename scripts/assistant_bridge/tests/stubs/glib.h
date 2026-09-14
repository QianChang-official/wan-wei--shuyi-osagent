/* Copyright (c) 2026 QianChang-official
 *
 * CI 语法检查用的最小 GLib 桩头（仅声明 sidecar.cpp 用到的符号）。
 *
 * 用途：GitHub Actions 跑不起麒麟 SDK 环境，为了让 sidecar 的 C++ 代码在 CI 里
 * 至少过一遍语法与类型检查（-fsyntax-only），这里提供与真实 API 同名同型的声明。
 * **真实构建必须使用系统 glib-2.0**（Makefile 通过 pkg-config 取头文件与库），
 * 本文件只在 tests/ 下被 CI 检查引用，不参与产物链接。
 */
#ifndef WANWEI_ASSISTANT_BRIDGE_TEST_STUB_GLIB_H
#define WANWEI_ASSISTANT_BRIDGE_TEST_STUB_GLIB_H

#ifdef __cplusplus
extern "C" {
#endif

typedef int gboolean;
typedef void* gpointer;

typedef struct _GMainContext GMainContext;
typedef struct _GMainLoop GMainLoop;

typedef gboolean (*GSourceFunc)(gpointer user_data);
typedef void (*GDestroyNotify)(gpointer data);

#define FALSE 0
#define TRUE 1
#define G_PRIORITY_DEFAULT 0
#define G_SOURCE_REMOVE ((gboolean)0)
#define G_SOURCE_CONTINUE ((gboolean)1)

GMainContext* g_main_context_new(void);
void g_main_context_unref(GMainContext* context);
void g_main_context_push_thread_default(GMainContext* context);
void g_main_context_pop_thread_default(GMainContext* context);
void g_main_context_invoke_full(GMainContext* context, int priority, GSourceFunc function, gpointer data,
                                GDestroyNotify notify);

GMainLoop* g_main_loop_new(GMainContext* context, gboolean is_running);
void g_main_loop_run(GMainLoop* loop);
void g_main_loop_quit(GMainLoop* loop);
void g_main_loop_unref(GMainLoop* loop);

#ifdef __cplusplus
}
#endif

#endif /* WANWEI_ASSISTANT_BRIDGE_TEST_STUB_GLIB_H */
