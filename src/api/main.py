import os
import time
import json
import logging
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import redis
from datetime import datetime, timedelta
import uvicorn

# Import models
from .models import (
    RecommendationRequest,
    RecommendationResponse,
    RecommendationItem,
    HealthCheckResponse,
    ErrorResponse,
    UserEngagementMetrics,
    CampaignPerformanceMetrics
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('api.log')
    ]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Marketing Personalization API",
    description="API for personalized marketing recommendations",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Redis client
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True
)

# Cache TTL in seconds
CACHE_TTL = 3600  # 1 hour

# Import recommendation service
from .recommendation_service import get_recommendation_service
from src.pipeline.monitoring import get_api_monitor, api_requests_total, api_request_duration_seconds
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

def get_user_engagement_metrics(user_id: str) -> Dict[str, Any]:
    """Mock function to get user engagement metrics."""
    return {
        "user_id": user_id,
        "message_count": 42,
        "engagement_score": "high",
        "last_active": datetime.utcnow().isoformat(),
        "preferred_campaigns": ["campaign_1", "campaign_3", "campaign_5"]
    }

def get_campaign_performance(campaign_id: str) -> Dict[str, Any]:
    """Mock function to get campaign performance metrics."""
    return {
        "campaign_id": campaign_id,
        "total_messages": 150,
        "unique_users": 85,
        "avg_sentiment": 0.75,
        "last_updated": datetime.utcnow().isoformat()
    }

# API Endpoints

@app.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """Health check endpoint."""
    try:
        redis_ok = bool(redis_client.ping())
        redis_status = "ok" if redis_ok else "unavailable"
    except Exception:
        redis_status = "unavailable"

    dependencies = {
        "redis": redis_status,
        # Add other dependencies here
    }
    
    return {
        "status": "healthy",
        "version": "1.0.0",
        "dependencies": dependencies
    }

@app.get("/recommendations/{user_id}", response_model=RecommendationResponse)
async def get_recommendations(user_id: str, top_k: int = 5):
    """
    Get personalized marketing recommendations for a user.
    
    This endpoint implements hybrid retrieval:
    1. Retrieves top 5 most similar users (via Milvus vector search)
    2. Fetches campaigns connected to those users (via Neo4j)
    3. Returns results ranked by engagement frequency (from analytics DB)
    """
    start_time = time.time()
    monitor = get_api_monitor()
    
    # Check cache first
    cache_key = f"recs:{user_id}:{top_k}"
    try:
        cached_result = redis_client.get(cache_key)
    except Exception:
        cached_result = None
    
    if cached_result:
        duration = time.time() - start_time
        result = json.loads(cached_result)
        result["source"] = "cache"
        result["latency_ms"] = duration * 1000
        monitor.log_request("/recommendations/{user_id}", "GET", 200, duration, user_id=user_id, source="cache")
        logger.info(f"Returned cached recommendations for user {user_id}")
        return result
    
    try:
        # Get recommendation service
        recommendation_service = get_recommendation_service()
        
        # Get hybrid recommendations
        recommendations = recommendation_service.get_recommendations(user_id, top_k=top_k)
        
        if not recommendations:
            logger.warning(f"No recommendations found for user {user_id}")
            recommendations = []
        
        # Prepare response
        duration = time.time() - start_time
        response = {
            "user_id": user_id,
            "recommendations": recommendations,
            "source": "hybrid",
            "timestamp": datetime.utcnow(),
            "latency_ms": duration * 1000
        }
        
        # Cache the result
        try:
            redis_client.setex(cache_key, CACHE_TTL, json.dumps(response, default=str))
        except Exception as e:
            logger.warning(f"Could not cache result: {e}")
        
        monitor.log_request("/recommendations/{user_id}", "GET", 200, duration, user_id=user_id, 
                          source="hybrid", recommendations_count=len(recommendations))
        logger.info(f"Generated {len(recommendations)} recommendations for user {user_id} in {response['latency_ms']:.2f}ms")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        duration = time.time() - start_time
        monitor.log_request("/recommendations/{user_id}", "GET", 500, duration, user_id=user_id, error=str(e))
        logger.error(f"Error generating recommendations for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating recommendations: {str(e)}"
        )


@app.post("/recommendations", response_model=RecommendationResponse)
async def get_recommendations_post(request: RecommendationRequest):
    """Get personalized marketing recommendations for a user (POST endpoint for compatibility)."""
    return await get_recommendations(request.user_id, request.top_k)

@app.get("/users/{user_id}/engagement", response_model=UserEngagementMetrics)
async def get_user_engagement(user_id: str):
    """Get engagement metrics for a specific user."""
    try:
        metrics = get_user_engagement_metrics(user_id)
        return metrics
    except Exception as e:
        logger.error(f"Error getting user engagement: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found or error retrieving metrics"
        )

@app.get("/campaigns/{campaign_id}/performance", response_model=CampaignPerformanceMetrics)
async def get_campaign_performance_metrics(campaign_id: str):
    """Get performance metrics for a specific campaign."""
    start_time = time.time()
    monitor = get_api_monitor()
    
    try:
        metrics = get_campaign_performance(campaign_id)
        duration = time.time() - start_time
        monitor.log_request("/campaigns/{campaign_id}/performance", "GET", 200, duration, campaign_id=campaign_id)
        return metrics
    except Exception as e:
        duration = time.time() - start_time
        monitor.log_request("/campaigns/{campaign_id}/performance", "GET", 404, duration, campaign_id=campaign_id, error=str(e))
        logger.error(f"Error getting campaign performance: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Campaign {campaign_id} not found or error retrieving metrics"
        )


@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/stats")
async def get_api_stats():
    """Get API statistics."""
    monitor = get_api_monitor()
    stats = monitor.get_latency_stats()
    return {
        "endpoint": "all",
        "statistics": stats,
        "timestamp": datetime.utcnow().isoformat()
    }

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "code": exc.status_code,
            "path": request.url.path
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handle all other exceptions."""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "detail": str(exc)
        }
    )

# Startup event
@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    logger.info("Starting Marketing Personalization API...")
    
    # Test Redis connection
    try:
        redis_client.ping()
        logger.info("Connected to Redis")
    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis: {str(e)}")
        # Don't raise here to allow the app to start without Redis
        # (in a real app, you might want to handle this differently)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
