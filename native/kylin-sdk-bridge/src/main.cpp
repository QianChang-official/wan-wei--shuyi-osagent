#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <iostream>
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

json handle_upsert(const json& request) {
    EmbeddingRuntime embedding(request);
    const int64_t vector_id = required_int64(request, "vector_id");
    const std::string capsule_id = required_string(request, "capsule_id");
    const std::vector<float> vector = embedding.embed(required_string(request, "text"));
    VectorRuntime vector_db(request);
    vector_db.upsert(vector_id, capsule_id, vector);
    return {
        {"ok", true},
        {"vector_id", vector_id},
        {"dimension", static_cast<int>(vector.size())},
        {"model", embedding.model_name()},
    };
}

json handle_search(const json& request) {
    EmbeddingRuntime embedding(request);
    const std::vector<float> vector = embedding.embed(required_string(request, "text"));
    const int64_t top_k = request.value("top_k", 5);
    VectorRuntime vector_db(request);
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

json handle_delete(const json& request) {
    VectorRuntime vector_db(request);
    const int64_t vector_id = required_int64(request, "vector_id");
    return {{"ok", true}, {"vector_id", vector_id}, {"deleted", vector_db.erase(vector_id)}};
}

json handle_probe(const json& request) {
    // A process-level probe is not enough: initialize both official SDKs so
    // Python only advertises native availability after the model and the
    // vector-engine connection have both succeeded.
    EmbeddingRuntime embedding(request);
    VectorRuntime vector_db(request);
    const std::vector<float> vector = embedding.embed("wanwei native sdk probe");
    return {
        {"ok", true},
        {"capabilities", {{"embedding", true}, {"vector_database", true}}},
        {"model", embedding.model_name()},
        {"dimension", static_cast<int>(vector.size())},
    };
}

json dispatch(const json& request) {
    const std::string action = required_string(request, "action");
    if (action == "probe") {
        return handle_probe(request);
    }
    if (action == "upsert") {
        return handle_upsert(request);
    }
    if (action == "search") {
        return handle_search(request);
    }
    if (action == "delete") {
        return handle_delete(request);
    }
    throw NativeError("unknown_action");
}

}  // namespace

int main() {
    try {
        json request;
        std::cin >> request;
        emit_response(dispatch(request));
        return 0;
    } catch (const std::exception&) {
        // The Python caller records only a generic failure, so bridge errors
        // cannot accidentally place input text in stdout or audit storage.
        emit_response(json{{"ok", false}, {"error", "native_operation_failed"}});
        return 0;
    }
}
