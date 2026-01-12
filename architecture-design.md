# Marketing Personalization Platform - Architecture Design

## System Overview
This platform ingests raw conversation events, enriches them with embeddings and graph relationships, and serves low-latency recommendations. It uses multiple specialized databases to optimize for different access patterns.

## Data Flows

### 1) Conversation Data Ingestion
- **Input:** Raw chat data from users (`user_id`, `message`, `timestamp`).
- **Path:** Airflow orchestrates batch ingestion via Spark. Events are validated, normalized, and persisted.

### 2) Embedding Generation
- **Method:** Sentence Transformer creates 1024-dimensional embeddings per message.
- **Execution:** Spark batch job generates embeddings for all messages.

### 3) Vector Storage (Milvus)
- **Content:** Store embeddings with metadata (`user_id`, `message_id`).
- **Pattern:** Idempotent upserts using stable `message_id` to enable safe reprocessing.

### 4) Relationship Mapping (Neo4j)
- **Graph model:** Users, Messages, Campaigns, Intents.
- **Edges:** `User-[:SENT]->Message`, `Message-[:ABOUT]->Campaign`, `Message-[:HAS_INTENT]->Intent`.
- **Idempotency:** `MERGE` operations with deterministic IDs.

### 5) Analytics Layer
- **Aggregates:** User engagement, campaign performance, daily activity.
- **Storage:** Sync to BigQuery in production; SQLite mock for local/dev.

### 6) Caching & Latency Optimization (Redis)
- **Scope:** Cache recent user sessions and recommendation responses.
- **Pattern:** Cache-aside with TTL; graceful degradation if cache is unavailable.

## Architecture Diagram

```mermaid
flowchart TD
  %% Data sources
  Raw[Raw conversation events\n(user_id, message, timestamp)]

  %% Orchestration
  Airflow[Airflow DAG\nETL/ELT orchestration]

  %% Batch processing
  Spark[Spark pipeline\ningest -> embed -> store]
  Ingest[Ingestion & validation]
  Embed[Embedding generation\nSentenceTransformer 1024-dim]
  MilvusWrite[Vector write to Milvus\nwith user_id/message_id]
  Neo4jWrite[Graph write to Neo4j\nMERGE relationships]
  AnalyticsAgg[Analytics aggregation]
  BigQuery[(BigQuery)\nProduction analytics]
  SQLite[(SQLite)\nLocal/dev analytics]

  %% Real-time serving
  API[FastAPI service\n/recommendations]
  Redis[(Redis cache\nrecent sessions + recs)]
  MilvusRead[Vector search (Milvus)\nANN top-k]
  Neo4jRead[Graph traversal (Neo4j)\nneighbors/intents]
  Postgres[(Postgres)\nServing aggregates]

  %% Flow connections
  Raw -->|batch input| Airflow
  Airflow -->|scheduled runs| Spark
  Spark --> Ingest
  Ingest --> Embed
  Embed --> MilvusWrite
  Embed --> Neo4jWrite
  Ingest --> AnalyticsAgg
  AnalyticsAgg --> BigQuery
  AnalyticsAgg --> SQLite

  %% Serving reads
  API <-->|cache-aside| Redis
  API -->|vector query| MilvusRead
  API -->|graph query| Neo4jRead
  API -->|ranking/explainability| Postgres

  %% Shared stores
  MilvusWrite -.->|shared| MilvusRead
  Neo4jWrite -.->|shared| Neo4jRead
```

## ETL/ELT Orchestration

- **Airflow DAG** (`marketing_personalization_pipeline`) runs the Spark job on a schedule or manual trigger.
- Tasks are idempotent:
  - Stable `message_id` enables safe re-runs.
  - `MERGE` in Neo4j and upserts in Milvus prevent duplicates.
- Retries and alerting via Airflow.

## Real-time vs Batch Flows

- **Batch (ETL/ELT):**
  - Heavy compute: ingestion, embedding generation, analytics aggregation.
  - Runs via Spark orchestrated by Airflow.
  - Writes to Milvus, Neo4j, and analytics warehouse.

- **Real-time (Serving):**
  - Low-latency reads from Milvus, Neo4j, Postgres.
  - Redis caching to reduce tail latency.
  - FastAPI serves recommendations with fallbacks.

## Scaling and Fault Tolerance Strategy

### Scaling
- **Spark:** Scale out with more executors; partitioned reads/writes.
- **Milvus:** Shard/partition collections; asynchronous index builds; batch inserts.
- **Neo4j:** Uniqueness constraints; batch transactions; cluster for HA.
- **Postgres/BigQuery:** Partitioned tables; materialized views for hot aggregates.
- **Redis:** Cluster mode; TTL-based eviction.

### Fault Tolerance
- **Idempotent writes:** Stable IDs + `MERGE`/upsert semantics.
- **Retries:** Airflow task retries with backoff.
- **Graceful degradation:** API serves cached or popularity-based recs if downstream is unavailable.
- **Observability:** Logs, metrics, and tracing across pipeline and serving layers.

## Trade-offs

- **Multiple stores:** Optimized access patterns at the cost of duplication and ID management.
- **Batch + real-time separation:** Simpler operational model; requires coordination for freshness.
- **Spark for embeddings:** Scalable but heavier than a simple Python job; justified for large datasets.
- **BigQuery vs SQLite:** Production warehouse vs local convenience; both supported via abstraction.
