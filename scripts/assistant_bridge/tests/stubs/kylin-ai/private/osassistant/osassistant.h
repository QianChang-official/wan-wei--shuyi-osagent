/* Copyright (c) 2026 QianChang-official
 *
 * CI 语法检查用的 Kylin OsAssistant 桩头。
 *
 * 与官方 openkylin/libkyai-assistant 的
 *   include/kylin-ai/private/osassistant/osassistant.h
 * 保持同名同型（openkylin/upstream 分支，2026-09 快照），供 GitHub Actions 在
 * 没有麒麟 SDK 的环境里对 sidecar.cpp 做 -fsyntax-only 类型检查。
 * **真实构建必须使用官方 SDK 头文件**（apt install libkysdk-ai-private-dev），
 * 本文件不参与产物链接。
 */
#ifndef WANWEI_ASSISTANT_BRIDGE_TEST_STUB_OSASSISTANT_H
#define WANWEI_ASSISTANT_BRIDGE_TEST_STUB_OSASSISTANT_H

#include <functional>
#include <list>
#include <memory>
#include <string>
#include <vector>

namespace kyai {
namespace assistant {

using ChatResultCallback = std::function<void(const std::string)>;

enum PromptContentAccessType { ReadOnly = 1, ReadWrite, NoAccess };

struct Prompt {
    int id;
    std::string name;
    std::string content;
    PromptContentAccessType type;
};

struct Message {
    std::string user;
    std::string assistant;
};

class Features {
public:
    enum Feature {
        TextChat = 1,
        TextToImage = 2,
        ImageProcessing = 4,
        DocumentQA = 8
    };
    explicit Features(int features) : features_(features) {}
    bool containsFeature(Feature feature) const { return features_ & feature; }

private:
    int features_;
};

// 官方 Error 支持 bool 转换（true = 出错）
class Error {
public:
    Error() = default;
    explicit Error(bool failed) : failed_(failed) {}
    explicit operator bool() const { return failed_; }

private:
    bool failed_ = false;
};

class OsAssistant {
public:
    OsAssistant();
    ~OsAssistant();

    Error init();
    Error initWithChatHistory(std::vector<Message> messages, int promptId = -1);

    void setChatAsyncCallback(ChatResultCallback callback);
    Features supportedFeatures() const;

    void chatAsync(const std::string& message);
    void stopChat();

    void setPromptId(int promptId);
    void clearContext();

    std::vector<Prompt> prompts();
    bool setPromptOrder(std::list<int> promptIdList);
    int createPrompt(std::string name, std::string content);
    bool deletePrompt(int promptId);
    bool updatePrompt(int promptId, std::string name, std::string content);
};

}  // namespace assistant
}  // namespace kyai

#endif /* WANWEI_ASSISTANT_BRIDGE_TEST_STUB_OSASSISTANT_H */
