# Milvus Standalone Deployment — Configuration Guide

Docker Compose deployment of [Milvus](https://milvus.io) v3.0.0 (standalone mode), adapted from the
[official standalone compose file](https://milvus.io/docs/install_standalone-docker-compose.md)
with host ports remapped into the `23310-23319` range.

> **Object storage note:** MinIO has stopped accepting community changes and removed its
> historical images from Docker Hub (`pull access denied for minio/minio`). Following the
> [official Milvus blog](https://milvus.io/blog/evaluating-rustfs-as-a-viable-s3-compatible-object-storage-backend-for-milvus.md),
> this stack uses [RustFS](https://rustfs.com/) — an S3-compatible object store — as the
> drop-in replacement for MinIO.

- Compose file: [`docker-compose.yml`](../docker-compose.yml) (project root)
- Deployment target: local development / single-host

---

## 1. Stack Overview

| Service | Container name | Image | Purpose |
|---|---|---|---|
| `standalone` | `milvus-standalone` | `milvusdb/milvus:v3.0.0` | Milvus vector database (standalone mode) |
| `etcd` | `milvus-etcd` | `quay.io/coreos/etcd:v3.5.25` | Metadata storage for Milvus |
| `rustfs` | `milvus-rustfs` | `rustfs/rustfs:latest` | S3-compatible object storage for Milvus data files |

All three services run on a dedicated Docker network named `milvus` (the compose default network,
renamed). Milvus reaches etcd and RustFS over this internal network via service names
(`etcd:2379`, `rustfs:9000`), so internal ports never change even if host ports do.

> The official blog references an Aliyun-registry RustFS image
> (`registry.cn-hangzhou.aliyuncs.com/rustfs/rustfs`), but that repository is no longer
> available; this stack uses the equivalent `rustfs/rustfs` image from Docker Hub.

## 2. Port Mapping

Only four of the ten reserved ports (`23310-23319`) are in use; the rest are free for future
services (e.g. Attu, backup tooling, or additional instances).

| Host port | Container port | Service | Protocol / Use |
|---|---|---|---|
| **23310** | 19530 | Milvus | gRPC — **the port SDK clients connect to** |
| **23311** | 9091 | Milvus | HTTP — metrics endpoint and built-in WebUI |
| 23312 | 9000 | RustFS | HTTP — S3 API (only needed by external backup/migration tools) |
| 23313 | 9001 | RustFS | HTTP — web console |
| 23314-23319 | — | — | Reserved, unassigned |

Notes:

- **etcd is intentionally not exposed.** Nothing outside the `milvus` network needs it.
- Milvus WebUI: `http://localhost:23311/webui/` (note the trailing slash). Log lines inside the
  container print the internal port `9091`; that is cosmetic — the working host address is `23311`.
- RustFS console: `http://localhost:23313/`, credentials `minioadmin` / `minioadmin`.

## 3. Milvus Service Configuration

The `standalone` service is configured through environment variables (per the
[RustFS deployment guide](https://milvus.io/blog/evaluating-rustfs-as-a-viable-s3-compatible-object-storage-backend-for-milvus.md)):

```yaml
environment:
  MINIO_REGION: us-east-1
  ETCD_ENDPOINTS: etcd:2379
  MINIO_ADDRESS: rustfs:9000        # points at RustFS — Milvus still uses MINIO_* names for S3 config
  MINIO_ACCESS_KEY: minioadmin
  MINIO_SECRET_KEY: minioadmin
  MINIO_USE_SSL: "false"
  MQ_TYPE: rocksmq                  # standalone message queue (local rocksdb-based)
```

Despite the `MINIO_` prefix, these are Milvus's generic S3 backend settings; RustFS serves the
same S3 API. To tune Milvus itself (limits, log level, etc.), the recommended path is mounting a
`milvus.yaml` overrides file instead of editing this compose:

```yaml
# add under standalone.volumes
- ./milvus.yaml:/milvus/configs/milvus.yaml
```

Reference: [Milvus config reference](https://milvus.io/docs/configure-docker.md).

Other service-level settings inherited from upstream:

- `security_opt: seccomp:unconfined` — required by the Milvus image.
- Healthcheck — `curl http://localhost:9091/healthz` every 30s, with a 90s `start_period`
  (first boot can take a while; the container is `health: starting` until then).
  RustFS's healthcheck probes `http://localhost:9000/health`.
- `depends_on` orders startup (etcd, rustfs first) but does **not** wait for healthy — Milvus
  retries its dependencies internally.

## 4. Data Persistence

All state is stored on bind mounts under `./volumes/` relative to the compose file:

```
volumes/
├── etcd/     # metadata (etcd data dir)
├── rustfs/   # object storage (collections, indexes, segments)
└── milvus/   # milvus internal storage (/var/lib/milvus)
```

The RustFS container runs as non-root user `rustfs` (UID 10001). On a native Linux host, run
`chown -R 10001:10001 volumes/rustfs` if you create the directory manually. On WSL `/mnt/*`
(Windows drives) ownership is ignored and the default 0777 permissions allow the container to
write.

The base directory can be overridden without editing the file:

```bash
DOCKER_VOLUME_DIRECTORY=/data/milvus docker compose up -d
```

Deleting `./volumes/` **deletes all collections and data**. Keep it out of version control
(see `.gitignore`).

## 5. Operations

```bash
# start (detached)
docker compose up -d

# check status / wait for healthy
docker compose ps

# follow logs
docker compose logs -f standalone

# verify Milvus is serving
curl http://localhost:23311/healthz

# stop (data preserved)
docker compose down

# stop and wipe all data
docker compose down && rm -rf volumes/
```

## 6. Connecting Clients

| Client | Address |
|---|---|
| pymilvus / milvus-sdk (gRPC) | `localhost:23310` |
| RESTful API (v2) | `http://localhost:23310/v2/vectordb` (multiplexed on the gRPC port; **POST-only** — opening it in a browser shows 404, that is expected) |
| WebUI | `http://localhost:23311/webui/` |
| Attu (GUI, if deployed separately) | point it at `localhost:23310` |

Example:

```python
from pymilvus import MilvusClient

client = MilvusClient(uri="http://localhost:23310")
```

When running a client **inside** another container on the same Docker network, use
`milvus-standalone:19530` instead.

## 7. Troubleshooting

- **`pull access denied for minio/minio`** — this is *why* this stack uses RustFS: MinIO removed
  its images from Docker Hub. Do not switch the compose back to the old `minio/minio` service.
  (As a fallback, MinIO's historical images do remain on `quay.io/minio/minio`.)
- **`port is already allocated`** — something else on the host holds 23310-23313. Remap the host
  side (left number) in `docker-compose.yml`; container-side ports must stay as-is.
- **Standalone stuck in `health: starting`** — normal for up to ~90s after first start
  (`start_period: 90s`). Longer than that, check `docker compose logs etcd rustfs`.
- **Rebuilt but data looks stale / corrupt after a version change** — image upgrades usually
  migrate in place; if a clean slate is acceptable, see the wipe command in §5. For real
  upgrades, follow the [official upgrade guide](https://milvus.io/docs/upgrade_milvus_standalone-docker.md).
- **Windows (Docker Desktop + Git Bash)** — paths in `DOCKER_VOLUME_DIRECTORY` must be valid
  from Docker Desktop's file sharing settings; plain relative `./volumes` always works.
