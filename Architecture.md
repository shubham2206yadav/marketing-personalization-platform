# Architecture

## Overview
This project is a prototype **marketing personalization platform** that runs a batch Spark pipeline to ingest conversations, generate embeddings, and write to multiple specialized datastores. A FastAPI service then serves low-latency recommendations using a **hybrid retrieval** approach.

## System diagram

```mermaid
flowchart LR
  subgraph Batch[Batch pipeline (Airflow -> Spark)]
    Raw[Conversation events\n(user_id, message, timestamp, campaign)]
    Airflow[Airflow DAG\nmarketing_personalization_pipeline]
    Spark[Spark job\npython -m src.pipeline.main]

    Raw --> Airflow --> Spark

    Spark --> Ingest[Ingestion + validation]
    Ingest --> Embed[Embeddings\nSentenceTransformer]
    Embed --> Milvus[(Milvus\nvector index)]
    Embed --> Neo4j[(Neo4j\nknowledge graph)]
    Ingest --> Analytics[(Postgres\nanalytics tables)]
    Ingest --> Mongo[(MongoDB\ndocument store)]

    Analytics --> Report[analytics_report.json]
  end

  subgraph Serving[Real-time serving (FastAPI)]
    Client[Clients]
    API[FastAPI\n/recommendations]
    Cache[(Redis\ncache)]

    Client --> API
    API <--> Cache
    API -->|ANN vector search| Milvus
    API -->|graph traversal / joins| Neo4j
    API -->|ranking + explainability| Analytics
  end
```

## Component responsibilities

### Ingestion
- Parses raw conversation events from the sample JSON input.
- Normalizes schema and timestamps so downstream aggregation and joins are reliable.

### Embedding generation
- Generates embeddings for conversation messages (SentenceTransformer).
- Stored alongside metadata (user/campaign/message identifiers).

### Milvus (vector DB)
- Stores embeddings for approximate nearest-neighbor search.
- Used by the API to find similar users/messages efficiently.

### Neo4j (graph DB)
- Stores relationships such as `User -> Message -> Campaign`.
- Enables explainable traversal-based recommendation features.

### Postgres (analytics)
- Stores aggregated tables (engagement, campaign performance, daily activity).
- Used by the API for ranking, heuristics, and dashboards/reports.

### MongoDB (document store)
- Stores raw/enriched conversation documents.
- Useful for replay, audits, and flexible schema evolution.

### Redis (cache)
- Cache-aside caching of recommendation responses.
- Reduces p95 latency and load on Milvus/Neo4j.

### Airflow (orchestration)
- Runs the pipeline as an idempotent batch DAG with retries and observability via task logs.

## Key design choices & trade-offs

- **Spark for batch processing**
  - Pros: scalable for large batches, good for embedding + aggregation workloads.
  - Cons: heavier operational footprint than simple Python jobs.

- **Milvus for vectors, Neo4j for relationships**
  - Pros: each system is optimized for its access pattern (ANN vs graph traversal).
  - Cons: data duplication across stores requires careful ID strategy + idempotency.

- **Postgres for analytics (vs BigQuery)**
  - Pros: local-friendly and simple for a prototype.
  - Cons: for very large scale analytics, a warehouse (BigQuery/Snowflake) is better.

- **Redis cache-aside**
  - Pros: simplest approach; works well when recs are requested repeatedly.
  - Cons: cache invalidation must be aligned with pipeline refresh cadence.
