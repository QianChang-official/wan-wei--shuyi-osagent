# Kylin Native SDK Integration

## Scope

`native/kylin-sdk-bridge` is a C++17 bridge over the official Kylin SDKs:

- `kysdk-coreai-embedding`: model discovery, session initialization, text embedding, result ownership and cleanup.
- `kysdk-vector-engine-client`: local database loading, collection management, upsert, cosine search and delete.

The Python runtime invokes the bridge through one JSON request on stdin. Text is
never passed through command-line arguments. The bridge emits one response line
prefixed with `WANWEI_KYLIN_RESPONSE:`; incidental vendor diagnostics cannot be
mistaken for a successful response. The bridge is optional so the standard
Docker image and non-Kylin development hosts remain runnable.

## Runtime Behavior

`WANWEI_KYLIN_NATIVE_MODE=auto` is the default:

1. An active, policy-approved Capsule is embedded and upserted through the
   Kylin bridge when `wanwei-kylin-sdk-bridge` is installed.
2. `/memory/v2/search` uses native embedding plus vector search as the primary
   retrieval backend. Governance filtering and evidence cards remain in Python.
3. If the bridge is absent or a native operation fails, FTS5 is used with
   `retrieval.backend=fts_fallback` and a non-sensitive fallback reason.
4. Forget confirmation commits the legacy/v2 Capsule changes, both FTS indexes,
   confirmation ticket, minimized audit event and native-delete intent in one
   SQLite transaction. Native deletion runs only after that commit. Failed or
   uncertain deletes remain in a durable `delete_pending`/tombstone outbox and
   a bounded startup/background sweeper retries them without client replay.
5. Capsules written before the bridge was installed remain on the FTS fallback
   until they are migrated through the bounded reindex operation. This prevents
   an empty native index from silently hiding existing eligible memory.
6. An isolated `index_failed` Capsule does not disable native retrieval for
   healthy Capsules. Its matching FTS result is selected by a bounded SQL join
   rather than materializing every failed ID, then surfaced with
   `retrieval_backend=fts_fallback` and `native_index_failed_capsule`.
7. Every indexing attempt has a persistent generation and a fresh vector ID
   when a stale lease is reclaimed. Claim and publish use generation-aware CAS;
   a late worker can only tombstone/delete its own superseded ID. This fences
   write/forget and stale-worker crash windows without allowing vector revival.

`hard_delete` physically removes the v2 Capsule row after staging its native
vector cleanup. Soft/cascade modes retain only the governed forgotten record.

An empty successful vector search remains an empty native result; it does not
silently fall back to keyword search.

## Kylin Build Prerequisites

The successful Kylin V11 2603 run required the runtime, embedding engine,
vector service, ONNX backend, text model, and development headers below. Let
APT resolve the matching dependency closure from the target Kylin repository:

```bash
sudo apt update
sudo apt install \
  kylin-ai-runtime \
  kylin-ai-vector-engine \
  kytensor-client \
  libkylin-ondevice-embedding-engine \
  onnxruntime-backend \
  kylin-ai-abstract-models \
  kylin-gte-base-model \
  libkylin-coreai-embedding-dev \
  libkysdk-vector-engine-client-dev \
  libkylin-ai-proto-dev \
  libkysdk-ai-common-dev \
  nlohmann-json3-dev cmake pkg-config
```

The VM evidence used these repository versions: `kylin-ai-runtime`
`1.2.0.4-0k0.1`, `kylin-ai-vector-engine` `1.2.0.1-0k1.0`,
`kytensor-client` `2.49.0.6-ok7k0.14`,
`libkylin-ondevice-embedding-engine` `1.2.0.0-0k1.0`,
`onnxruntime-backend` `1.0.1-ok6k0.1`, `kylin-ai-abstract-models`
`1.2.0.1-0k1.0`, `kylin-gte-base-model` `1.0.0.1-0k0.9`,
`libkylin-coreai-embedding-dev` `1.2.0.0-0k0.4`, and
`libkysdk-vector-engine-client-dev` `1.2.0.0-0k1.1`. Repository candidates
may advance; verify the resolved versions and rerun the probe instead of
assuming a newer combination is compatible.

The vector SDK itself depends on the Kylin vector-engine service and its
transport dependencies. Confirm both pkg-config entries before building:

```bash
pkg-config --modversion kysdk-coreai-embedding
pkg-config --modversion kysdk-vector-engine-client
```

Build and install the bridge:

```bash
cmake -S native/kylin-sdk-bridge -B build/kylin-sdk-bridge
cmake --build build/kylin-sdk-bridge --parallel
sudo cmake --install build/kylin-sdk-bridge
```

Development mode uses only the fixed CMake install path
`/usr/local/bin/wanwei-kylin-sdk-bridge`; custom locations must be configured
through an absolute `WANWEI_KYLIN_SDK_BRIDGE` path. Production mode requires
that explicit path so process execution does not inherit untrusted PATH ordering.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `WANWEI_KYLIN_NATIVE_MODE` | `auto` | Set to `off` only to force FTS fallback. |
| `WANWEI_KYLIN_SDK_BRIDGE` | `/usr/local/bin/wanwei-kylin-sdk-bridge` in development | Absolute trusted bridge path; required in production and for custom locations. |
| `WANWEI_KYLIN_EMBEDDING_MODEL` | first text model returned by SDK | Pin a vendor model name. |
| `WANWEI_KYLIN_VECTOR_DB` | sibling `kylin-vector.db` next to `memory.db` | Local vector database file. |
| `WANWEI_KYLIN_VECTOR_COLLECTION` | `wanwei_memory_capsules` | Vector collection name. |
| `WANWEI_KYLIN_VECTOR_APP_ID` | `wanwei-shuyi-osagent` | Kylin vector-engine application identity. |
| `WANWEI_KYLIN_SDK_TIMEOUT_SECONDS` | `10` | Per native bridge request timeout, bounded to 1-60 seconds. |

Inspect readiness without sending content:

```bash
curl http://127.0.0.1:8010/kylin/sdk/status \
  -H "X-API-Key: $WANWEI_API_KEY"
```

`available=true` proves that the bridge initialized an official embedding
session and model and connected to the configured vector-engine database. The
response also exposes the selected model, dimension, eligible/indexed/failed/
pending Capsule counts, `delete_pending` cleanup backlog, and reindex activity
without returning memory content or credentials.

After installing the bridge against an existing memory database, queue bounded
background batches until `index.pending` is zero. The endpoint defaults to 10
Capsules and accepts at most 25, returning `202 Accepted` when a batch is
queued. Poll `/kylin/sdk/status` for progress. Failed Capsules are not retried
unless `retry_failed=true` is supplied after the operator has corrected the
underlying SDK issue. The endpoint requires the normal `X-API-Key`:

```bash
curl -X POST 'http://127.0.0.1:8010/kylin/sdk/reindex?limit=10' \
  -H "X-API-Key: $WANWEI_API_KEY"
```

## Evidence Required Before Claiming Completion

1. Build the bridge on the target Kylin VM with both official dev packages.
2. Record `/kylin/sdk/status`, complete any reported reindex backlog, and record a successful Capsule write with
   `native_index.backend=kylin_native`.
3. Search non-keyword-equivalent text and record
   `retrieval.backend=kylin_native` plus returned evidence cards.
4. Forget the Capsule and verify the vector deletion audit has no pending ID.
5. Measure retrieval latency against the competition target before claiming the
   target is met.
