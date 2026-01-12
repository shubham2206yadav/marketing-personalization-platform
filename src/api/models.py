from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class RecommendationRequest(BaseModel):
    """Request model for getting recommendations."""
    user_id: str = Field(..., description="The ID of the user to get recommendations for")
    top_k: int = Field(5, description="Number of recommendations to return", ge=1, le=20)
    min_confidence: float = Field(0.5, description="Minimum confidence score for recommendations", ge=0.0, le=1.0)
    include_explanation: bool = Field(True, description="Whether to include explanation for recommendations")

class RecommendationItem(BaseModel):
    """A single recommendation item."""
    campaign_id: str = Field(..., description="The ID of the recommended campaign")
    score: float = Field(..., description="Recommendation score (0-1)", ge=0.0, le=1.0)
    confidence: float = Field(..., description="Confidence level (0-1)", ge=0.0, le=1.0)
    explanation: Optional[str] = Field(None, description="Explanation for the recommendation")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata about the recommendation")

class RecommendationResponse(BaseModel):
    """Response model for recommendations."""
    user_id: str = Field(..., description="The ID of the user")
    recommendations: List[RecommendationItem] = Field(..., description="List of recommended items")
    source: str = Field(..., description="Source of the recommendations (e.g., 'hybrid', 'cache')")
    timestamp: Optional[datetime] = Field(default_factory=datetime.utcnow, description="Timestamp of the response")
    latency_ms: float = Field(..., description="Request processing time in milliseconds")

class HealthCheckResponse(BaseModel):
    """Health check response model."""
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Current server time")
    dependencies: Dict[str, str] = Field(..., description="Status of service dependencies")

class ErrorResponse(BaseModel):
    """Error response model."""
    error: str = Field(..., description="Error message")
    code: int = Field(..., description="HTTP status code")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")

class UserEngagementMetrics(BaseModel):
    """User engagement metrics model."""
    user_id: str = Field(..., description="The ID of the user")
    message_count: int = Field(..., description="Total number of messages from the user")
    engagement_score: str = Field(..., description="Engagement level (low/medium/high)")
    last_active: datetime = Field(..., description="Timestamp of last activity")
    preferred_campaigns: List[str] = Field(..., description="List of preferred campaign IDs")

class CampaignPerformanceMetrics(BaseModel):
    """Campaign performance metrics model."""
    campaign_id: str = Field(..., description="The ID of the campaign")
    total_messages: int = Field(..., description="Total number of messages for this campaign")
    unique_users: int = Field(..., description="Number of unique users engaged with this campaign")
    avg_sentiment: float = Field(..., description="Average sentiment score (0-1)")
    last_updated: datetime = Field(..., description="When the metrics were last updated")
