# Kylin Native SDK Integration

## Scope

`native/kylin-sdk-bridge` is a C++17 bridge over the official Kylin SDKs:

- `kysdk-coreai-embedding`: model discovery, session initialization, text embedding, result ownership and cleanup.
- `kysdk-vector-engine-client`: local database loading, collection management, upsert, cosine search and delete.

The Python runtime invokes the bridge through one JSON request on stdin. Text is
never passed through command-line arguments. The bridge is optional so the
standard Docker image and non-Kylin development hosts remain runnable.

## Runtime Behavior

`WANWEI_KYLIN_NATIVE_MODE=auto` is the default:

1. An active, policy-approved Capsule is embedded and upserted through the
   Kylin bridge when `wanwei-kylin-sdk-bridge` is installed.
2. `/memory/v2/search` uses native embedding plus vector search as the primary
   retrieval backend. Governance filtering and evidence cards remain in Python.
3. If the bridge is absent or a native operation fails, FTS5 is used with
   `retrieval.backend=fts_fallback` and a non-sensitive fallback reason.
4. Forgetting a Capsule deletes its FTS entry immediately and requests native
   vector deletion. A failed native delete is marked `delete_pending` in the
   local mapping table and audit log rather than reported as completed.
5. Capsules written before the bridge was installed remain on the FTS fallback
   until they are migrated through the bounded reindex operation. This prevents
   an empty native index from silently hiding existing eligible memory.

An empty successful vector search remains an empty native result; it does not
silently fall back to keyword search.

## Kylin Build Prerequisites

Install the official runtime and development packages available for the target
Kylin release:

```bash
sudo apt install \
  libkylin-coreai-embedding-dev \
  libkysdk-vector-engine-client-dev \
  libkylin-ai-proto-dev \
  libkysdk-ai-common-dev \
  nlohmann-json3-dev cmake pkg-config
```

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

The default discovery path is `PATH`, then
`/usr/local/bin/wanwei-kylin-sdk-bridge`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `WANWEI_KYLIN_NATIVE_MODE` | `auto` | Set to `off` only to force FTS fallback. |
| `WANWEI_KYLIN_SDK_BRIDGE` | discovered executable | Absolute bridge override. |
| `WANWEI_KYLIN_EMBEDDING_MODEL` | first text model returned by SDK | Pin a vendor model name. |
| `WANWEI_KYLIN_VECTOR_DB` | sibling `kylin-vector.db` next to `memory.db` | Local vector database file. |
| `WANWEI_KYLIN_VECTOR_COLLECTION` | `wanwei_memory_capsules` | Vector collection name. |
| `WANWEI_KYLIN_VECTOR_APP_ID` | `wanwei-shuyi-osagent` | Kylin vector-engine application identity. |
| `WANWEI_KYLIN_SDK_TIMEOUT_SECONDS` | `10` | Per native bridge request timeout, bounded to 1-60 seconds. |

Inspect readiness without sending content:

```bash
curl http://127.0.0.1:8010/kylin/sdk/status
```

`available=true` proves that the bridge initialized an official embedding
session and model and connected to the configured vector-engine database. The
response also exposes the selected model, dimension, and eligible/indexed/
pending Capsule counts without returning memory content or credentials.

After installing the bridge against an existing memory database, migrate in
bounded batches until `index.pending` is zero. The endpoint requires the normal
`X-API-Key`:

```bash
curl -X POST 'http://127.0.0.1:8010/kylin/sdk/reindex?limit=25' \
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
