FROM python:3.10-slim AS api

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM apache/airflow:2.8.0-python3.11 AS airflow

USER root

RUN apt-get update \
  && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# Set JAVA_HOME - try to detect automatically, fallback to common paths
RUN JAVA_ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64") && \
    if [ -d "/usr/lib/jvm/java-17-openjdk-${JAVA_ARCH}" ]; then \
      JAVA_HOME_PATH="/usr/lib/jvm/java-17-openjdk-${JAVA_ARCH}"; \
    elif [ -d "/usr/lib/jvm/java-17-openjdk-arm64" ]; then \
      JAVA_HOME_PATH="/usr/lib/jvm/java-17-openjdk-arm64"; \
    elif [ -d "/usr/lib/jvm/java-17-openjdk-amd64" ]; then \
      JAVA_HOME_PATH="/usr/lib/jvm/java-17-openjdk-amd64"; \
    else \
      JAVA_HOME_PATH=$(find /usr/lib/jvm -maxdepth 1 -type d -name "java-17-openjdk-*" 2>/dev/null | head -1); \
    fi && \
    echo "Detected JAVA_HOME: $JAVA_HOME_PATH" && \
    if [ -n "$JAVA_HOME_PATH" ] && [ -d "$JAVA_HOME_PATH" ]; then \
      echo "JAVA_HOME=$JAVA_HOME_PATH" >> /etc/environment; \
    fi

# Default JAVA_HOME (will be overridden if detection worked)
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64

# Copy entrypoint script
COPY src/dags/airflow-entrypoint.sh /opt/airflow/dags/airflow-entrypoint.sh
RUN chmod +x /opt/airflow/dags/airflow-entrypoint.sh

USER airflow

RUN pip install --no-cache-dir \
  pyspark==3.5.0 \
  pandas==2.1.1 \
  numpy==1.26.0 \
  sentence-transformers==2.2.2 \
  scikit-learn==1.3.0 \
  transformers==4.26.1 \
  tokenizers==0.13.3 \
  huggingface-hub==0.12.1 \
  pymilvus==2.4.0 \
  environs==9.5.0 \
  marshmallow==3.20.1 \
  neo4j==5.15.0 \
  redis==4.6.0 \
  psycopg2-binary==2.9.9 \
  sqlalchemy==1.4.36 \
  pymongo==4.6.1 \
  prometheus-client==0.17.1 \
  tqdm==4.66.1 \
  python-json-logger==2.0.7

FROM python:3.10-slim AS dashboard

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY data /app/data

EXPOSE 8501

CMD ["streamlit", "run", "src/dashboard/app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
