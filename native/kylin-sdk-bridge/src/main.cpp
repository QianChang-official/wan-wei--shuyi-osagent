#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

#include <kylin-ai/coreai/embedding/embedding.h>
#include <kylin-ai/coreai/embedding/modelinfo.h>
#include <kylin-ai/common/error.h>

#include <Database.h>
#include <types/Constants.h>
#include <types/FieldData.h>
#include <types/SearchArguments.h>
#include <types/SearchResults.h>

namespace {

using json = nlohmann::json;
constexpr const char* kResponsePrefix = "WANWEI_KYLIN_RESPONSE:";
constexpr const char* kDefaultEmbeddingModel = "ensemble-embd_gte-base_uint8-text";

class NativeError : public std::runtime_error {
public:
    explicit NativeError(const std::string& message) : std::runtime_error(message) {}
};

void emit_response(const json& response) {
    // Vendor libraries can emit diagnostics to stdout.  Prefixing the one
    // protocol envelope lets the Python caller reject incidental JSON logs.
    std::cout << kResponsePrefix << response.dump() << std::endl;
}

void require_status(const VectorDB::Status& status, const char* operation) {
    if (!status.IsOk()) {
        throw NativeError(std::string(operation) + "_failed_" + std::to_string(static_cast<int>(status.Code())));
    }
}

std::string required_string(const json& request, const char* name) {
    const auto it = request.find(name);
    if (it == request.end() || !it->is_string() || it->get<std::string>().empty()) {
        throw NativeError(std::string("missing_") + name);
    }
    return it->get<std::string>();
}

std::string optional_string(const json& request, const char* name) {
    const auto it = request.find(name);
    if (it == request.end() || it->is_null()) {
        return {};
    }
    if (!it->is_string()) {
        throw NativeError(std::string("invalid_") + name);
    }
    return it->get<std::string>();
}

int64_t required_int64(const json& request, const char* name) {
    const auto it = request.find(name);
    if (it == request.end() || !it->is_number_integer()) {
        throw NativeError(std::string("missing_") + name);
    }
    return it->get<int64_t>();
}

bool valid_collection_name(const std::string& value) {
    if (value.empty() || value.size() > 128 || (!std::isalpha(static_cast<unsigned char>(value[0])) && value[0] != '_')) {
        return false;
    }
    return std::all_of(value.begin() + 1, value.end(), [](unsigned char ch) {
        return std::isalnum(ch) || ch == '_';
    });
}

class EmbeddingRuntime {
public:
    explicit EmbeddingRuntime(const json& request) {
        session_ = text_embedding_create_session();
        if (session_ == nullptr) {
            throw NativeError("embedding_session_create_failed");
        }
        const int init_code = text_embedding_init_session(session_);
        if (init_code != 0) {
            throw NativeError("embedding_session_init_failed_" + std::to_string(init_code));
        }
        select_model(optional_string(request, "embedding_model"));
    }

    ~EmbeddingRuntime() {
        if (session_ != nullptr) {
            text_embedding_destroy_session(&session_);
        }
    }

    const std::string& model_name() const { return model_name_; }
    int dimension() const { return dimension_; }

    std::vector<float> embed(const std::string& text) {
        EmbeddingResult* result = nullptr;
        if (!text_embedding(session_, text.c_str(), &result) || result == nullptr) {
            throw NativeError("embedding_request_failed");
        }

        const int error_code = embedding_result_get_error_code(result);
        if (error_code != 0) {
            embedding_result_destroy(&result);
            throw NativeError("embedding_result_failed_" + std::to_string(error_code));
        }

        const int length = embedding_result_get_vector_length(result);
        float* data = embedding_result_get_vector_data(result);
        if (length <= 0 || data == nullptr) {
            embedding_result_destroy(&result);
            throw NativeError("embedding_result_invalid");
        }
        std::vector<float> vector(data, data + length);
        embedding_result_destroy(&result);
        return vector;
    }

private:
    void select_model(const std::string& requested_model) {
        int error_code = 0;
        EmbeddingModelList* models = text_embedding_get_model_list(session_, &error_code);
        const EmbeddingModelInfo* selected = nullptr;
        bool initialize_model = true;
        if (models != nullptr && error_code == 0) {
            const int count = embedding_model_list_get_count(models, &error_code);
            if (count <= 0 || error_code != 0) {
                throw NativeError("embedding_model_count_failed_" + std::to_string(error_code));
            }

            for (int index = 0; index < count; ++index) {
                const EmbeddingModelInfo* candidate = embedding_model_list_get_model(models, index, &error_code);
                if (candidate == nullptr || error_code != 0) {
                    continue;
                }
                const char* candidate_name = embedding_model_info_get_model_name(candidate, &error_code);
                if (candidate_name == nullptr || error_code != 0) {
                    continue;
                }
                if (requested_model.empty() || requested_model == candidate_name) {
                    selected = candidate;
                    model_name_ = candidate_name;
                    break;
                }
            }

            if (selected == nullptr) {
                throw NativeError("embedding_model_not_found");
            }

            dimension_ = embedding_model_info_get_model_dim(selected, &error_code);
            if (dimension_ <= 0 || error_code != 0) {
                throw NativeError("embedding_model_dimension_failed_" + std::to_string(error_code));
            }
        } else if (error_code == AI_COMMON_RUNTIME_OUTDATED) {
            model_name_ = requested_model.empty() ? kDefaultEmbeddingModel : requested_model;
            if (model_name_ != kDefaultEmbeddingModel) {
                throw NativeError("embedding_model_selection_unsupported");
            }
            initialize_model = false;
        } else {
            throw NativeError("embedding_model_list_failed_" + std::to_string(error_code));
        }

        if (initialize_model) {
            const int init_code = text_embedding_init_model(session_, model_name_.c_str());
            if (init_code != 0) {
                throw NativeError("embedding_model_init_failed_" + std::to_string(init_code));
            }
        }
    }

    TextEmbeddingSession* session_{nullptr};
    std::string model_name_;
    int dimension_{0};
};

class VectorRuntime {
public:
    explicit VectorRuntime(const json& request)
        : collection_(required_string(request, "collection")),
          db_file_(required_string(request, "db_file")) {
        if (!valid_collection_name(collection_)) {
            throw NativeError("invalid_collection");
        }
        const std::filesystem::path db_path(db_file_);
        if (db_path.has_parent_path()) {
            std::filesystem::create_directories(db_path.parent_path());
        }

        client_ = VectorDB::Database::Create();
        if (!client_) {
            throw NativeError("vector_client_create_failed");
        }
        require_status(client_->Connect(VectorDB::ConnectParam(required_string(request, "app_id"))), "vector_connect");
        require_status(client_->LoadDBFile(db_file_), "vector_load_db");
    }

    ~VectorRuntime() {
        if (client_) {
            client_->Disconnect();
        }
    }

    void upsert(int64_t vector_id, const std::string& capsule_id, const std::vector<float>& vector) {
        ensure_collection(static_cast<int>(vector.size()));
        std::vector<VectorDB::FieldDataPtr> fields{
            std::make_shared<VectorDB::Int64FieldData>(
                DEFAULT_ID_FIELD_NAME, std::vector<int64_t>{vector_id}),
            std::make_shared<VectorDB::FloatVecFieldData>(
                DEFAULT_VECTOR_FIELD_NAME, std::vector<std::vector<float>>{vector}),
            std::make_shared<VectorDB::JsonFieldData>(
                DYNAMIC_FIELD_NAME, std::vector<json>{json{{"capsule_id", capsule_id}}}),
        };
        VectorDB::DmlResults results;
        require_status(client_->Upsert(collection_, fields, results), "vector_upsert");
    }

    std::vector<std::pair<int64_t, float>> search(const std::vector<float>& vector, int64_t top_k) {
        bool exists = false;
        require_status(client_->HasCollection(collection_, exists), "vector_has_collection");
        if (!exists) {
            return {};
        }

        VectorDB::SearchArguments arguments(collection_, std::max<int64_t>(1, top_k));
        require_status(arguments.AddTargetVector(DEFAULT_VECTOR_FIELD_NAME, vector), "vector_add_target");
        require_status(arguments.SetGuaranteeTimestamp(VectorDB::GuaranteeStrongTs()), "vector_consistency");
        VectorDB::SearchResults results;
        require_status(client_->Search(arguments, results), "vector_search");

        std::vector<std::pair<int64_t, float>> hits;
        for (auto& single : results.Results()) {
            if (!single.Ids().IsIntegerID()) {
                continue;
            }
            const auto& ids = single.Ids().IntIDArray();
            const auto& scores = single.Scores();
            const size_t count = std::min(ids.size(), scores.size());
            for (size_t index = 0; index < count; ++index) {
                hits.emplace_back(ids[index], scores[index]);
            }
        }
        return hits;
    }

    bool erase(int64_t vector_id) {
        bool exists = false;
        require_status(client_->HasCollection(collection_, exists), "vector_has_collection");
        if (!exists) {
            return false;
        }
        VectorDB::DmlResults results;
        require_status(
            client_->Delete(collection_, "id in [" + std::to_string(vector_id) + "]", results),
            "vector_delete");
        return true;
    }

private:
    void ensure_collection(int dimension) {
        bool exists = false;
        require_status(client_->HasCollection(collection_, exists), "vector_has_collection");
        if (!exists) {
            require_status(client_->CreateCollection(collection_, dimension, false, true), "vector_create_collection");
        }
    }

    std::shared_ptr<VectorDB::Database> client_;
    std::string collection_;
    std::string db_file_;
};

// 请求间复用的运行时缓存:模型加载与向量库连接只在首个请求发生一次,
// 键含全部会影响运行时构造的配置项——配置变化时自然重建,不跨配置复用。
class RuntimeCache {
public:
    EmbeddingRuntime& embedding(const json& request) {
        const std::string key = optional_string(request, "embedding_model");
        const auto it = embeddings_.find(key);
        if (it != embeddings_.end()) {
            return *it->second;
        }
        return *embeddings_.emplace(key, std::make_unique<EmbeddingRuntime>(request)).first->second;
    }

    VectorRuntime& vector_db(const json& request) {
        const std::string key =
            required_string(request, "app_id") + "\x1f" +
            required_string(request, "collection") + "\x1f" +
            required_string(request, "db_file");
        const auto it = vector_dbs_.find(key);
        if (it != vector_dbs_.end()) {
            return *it->second;
        }
        return *vector_dbs_.emplace(key, std::make_unique<VectorRuntime>(request)).first->second;
    }

private:
    std::map<std::string, std::unique_ptr<EmbeddingRuntime>> embeddings_;
    std::map<std::string, std::unique_ptr<VectorRuntime>> vector_dbs_;
};

json handle_upsert(const json& request, RuntimeCache& cache) {
    EmbeddingRuntime& embedding = cache.embedding(request);
    const int64_t vector_id = required_int64(request, "vector_id");
    const std::string capsule_id = required_string(request, "capsule_id");
    const std::vector<float> vector = embedding.embed(required_string(request, "text"));
    VectorRuntime& vector_db = cache.vector_db(request);
    vector_db.upsert(vector_id, capsule_id, vector);
    return {
        {"ok", true},
        {"vector_id", vector_id},
        {"dimension", static_cast<int>(vector.size())},
        {"model", embedding.model_name()},
    };
}

json handle_search(const json& request, RuntimeCache& cache) {
    EmbeddingRuntime& embedding = cache.embedding(request);
    const std::vector<float> vector = embedding.embed(required_string(request, "text"));
    const int64_t top_k = request.value("top_k", 5);
    VectorRuntime& vector_db = cache.vector_db(request);
    const auto native_hits = vector_db.search(vector, top_k);

    json hits = json::array();
    for (const auto& [vector_id, score] : native_hits) {
        hits.push_back({{"vector_id", vector_id}, {"score", score}});
    }
    return {
        {"ok", true},
        {"hits", hits},
        {"dimension", static_cast<int>(vector.size())},
        {"model", embedding.model_name()},
    };
}

json handle_delete(const json& request, RuntimeCache& cache) {
    VectorRuntime& vector_db = cache.vector_db(request);
    const int64_t vector_id = required_int64(request, "vector_id");
    return {{"ok", true}, {"vector_id", vector_id}, {"deleted", vector_db.erase(vector_id)}};
}

json handle_probe(const json& request, RuntimeCache& cache) {
    // A process-level probe is not enough: initialize both official SDKs so
    // Python only advertises native availability after the model and the
    // vector-engine connection have both succeeded.
    EmbeddingRuntime& embedding = cache.embedding(request);
    VectorRuntime& vector_db = cache.vector_db(request);
    const std::vector<float> vector = embedding.embed("wanwei native sdk probe");
    return {
        {"ok", true},
        {"capabilities", {{"embedding", true}, {"vector_database", true}}},
        {"model", embedding.model_name()},
        {"dimension", static_cast<int>(vector.size())},
    };
}

json dispatch(const json& request, RuntimeCache& cache) {
    const std::string action = required_string(request, "action");
    if (action == "probe") {
        return handle_probe(request, cache);
    }
    if (action == "upsert") {
        return handle_upsert(request, cache);
    }
    if (action == "search") {
        return handle_search(request, cache);
    }
    if (action == "delete") {
        return handle_delete(request, cache);
    }
    throw NativeError("unknown_action");
}

}  // namespace

// 进程模型（延迟优化的核心改动）:
//
// 旧版:main 读一个请求、处理、退出——每次 search 都要重新加载 embedding
// 模型并重连向量库,单次查询 ~200ms 里绝大部分是重复的初始化开销。
// 新版:按行循环处理请求直到 EOF。RuntimeCache 以 (模型, 集合, 库文件,
// app_id) 为键复用 EmbeddingRuntime / VectorRuntime——模型只在首个请求
// 加载一次,后续请求只付 embed + search 的真实成本。
//
// 向后兼容:旧的一次性调用方(写一个请求后关 stdin)在循环里表现为
// 处理一行后读到 EOF 退出,行为与旧版逐字节一致。
int main() {
    std::ios::sync_with_stdio(false);
    RuntimeCache cache;
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.find_first_not_of(" \t\r\n") == std::string::npos) {
            continue;  // 忽略空行(对端 flush 语义)
        }
        json response;
        try {
            const json request = json::parse(line);
            response = dispatch(request, cache);
        } catch (const std::exception&) {
            // The Python caller records only a generic failure, so bridge
            // errors cannot accidentally place input text in stdout or audit
            // storage.
            response = json{{"ok", false}, {"error", "native_operation_failed"}};
        }
        emit_response(response);
        std::cout.flush();
    }
    return 0;
}
