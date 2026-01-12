# Scaling Plan

This document describes how to evolve this prototype to production scale.

## Goals

- **10M+ users** with ongoing conversation events
- **Sub-100ms vector queries** (p50 and p95) for online serving
- **Cost-efficient** cloud operation (predictable spend, elastic scaling)

## 1) Handle 10M+ users

### Data model & identifiers
- Use stable, deterministic IDs (`message_id`, `user_id`, `campaign_id`) to enable **idempotent upserts**.
- Separate **event ingestion** (append-only) from **feature/materialized views** (derived, rebuildable).

### Storage layout
- **Raw events**: move from local JSON to object storage (S3/GCS) partitioned by date/hour.
- **MongoDB** (if retained) becomes optional; at scale consider:
  - Object storage (cheap) for raw replay
  - A streaming log (Kafka/PubSub) for real-time event transport

### Batch + streaming processing
- Keep Spark for large backfills, but add a streaming path:
  - **Kafka/PubSub -> Spark Structured Streaming / Flink / Beam**
  - Micro-batch embeddings for new events + periodic compaction
- Use Airflow for:
  - scheduled backfills
  - model version rollouts
  - recomputing aggregates

### Analytics layer
- Replace Postgres-only analytics with a warehouse for scale:
  - BigQuery/Snowflake/Redshift for large scans and BI
- Keep Postgres for **serving aggregates** only (hot subset / materialized tables) if needed.

## 2) Ensure sub-100 ms vector queries

### Milvus collection strategy
- **Partitioning**
  - Partition by time (e.g., month/week) and/or tenant/campaign if multi-tenant.
  - Keep “hot” partitions small for lower latency.

- **Indexing**
  - Use ANN indexes (e.g., HNSW/IVF-PQ depending on recall/latency needs).
  - Build indexes asynchronously; avoid heavy index builds during peak traffic.

- **Query pattern**
  - Keep `top_k` small (e.g., 10–200 depending on reranking stage).
  - Use metadata filters to reduce candidate set (campaign, locale, time window).

### Online architecture
- **Separate read and write paths**
  - Online reads hit Milvus query nodes.
  - Writes/ingestion go through dedicated write pipeline; use buffering and batch upserts.

- **Caching**
  - Cache the final recommendations in Redis keyed by `user_id` and relevant context.
  - Cache embeddings for frequently queried users/messages.

- **Reranking**
  - Two-stage retrieval:
    1. ANN retrieval in Milvus (fast)
    2. Lightweight rerank using Postgres aggregates / business rules
  - Keep the reranker in-process to avoid extra network hops.

### Latency SLO engineering
- Measure p50/p95 by endpoint and by dependency (Milvus, Neo4j, Postgres).
- Apply timeouts and fallbacks:
  - If Neo4j is slow/unavailable, serve vector-only recommendations.
  - If Milvus is slow, serve cached or popularity-based recommendations.

## 3) Maintain cost efficiency in cloud environments

### Compute
- Prefer **autoscaling** for stateless services:
  - FastAPI service: horizontal pod autoscaling (HPA) based on CPU/latency/QPS.
  - Airflow workers: scale to zero when idle (where possible).

### Storage tiers
- Raw events and large historical data in **object storage**.
- Keep only hot / serving data in:
  - Milvus
  - Neo4j
  - Redis
  - Postgres (serving aggregates)

### Index and retention strategy
- Apply TTL and retention policies:
  - Drop/compact old partitions in Milvus if not required for personalization.
  - Keep graph edges only for a rolling window unless long-term history is required.
- Use downsampling for analytics (daily aggregates rather than raw events).

### Operational efficiency
- Use managed services when justified:
  - Managed Postgres
  - Managed Redis
  - Managed Kafka/PubSub
  - Managed warehouse
- Keep Milvus/Neo4j managed or self-hosted depending on:
  - SLA and team expertise
  - cost vs operational overhead

### Observability
- Metrics: QPS, latency, error rates, cache hit rate, Milvus recall/latency.
- Tracing across API -> Milvus/Neo4j/Postgres.
- Alert on SLO burn rates.

## Suggested target architecture (production)

- **Ingress**: API Gateway + Auth
- **Online serving**: FastAPI (stateless) + Redis
- **Vector**: Milvus cluster (partitioned, indexed) + embedding service
- **Graph**: Neo4j cluster or alternative (if graph needs exceed Neo4j cost)
- **Streaming**: Kafka/PubSub
- **Batch**: Spark on Kubernetes/Dataproc/EMR
- **Warehouse**: BigQuery/Snowflake
- **Orchestration**: Airflow for batch/backfills + model lifecycle
