"""
Recommendation service implementing hybrid retrieval.
"""
import os
import logging
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer
from pymilvus import connections, Collection
from pymilvus import utility
from neo4j import GraphDatabase
from src.pipeline.analytics_db import AnalyticsDB
import numpy as np

logger = logging.getLogger(__name__)

# Initialize sentence transformer model
MODEL_NAME = "all-MiniLM-L6-v2"
_embedding_model = None

def get_embedding_model():
    """Get or initialize the embedding model."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(MODEL_NAME)
    return _embedding_model


class RecommendationService:
    """Service for generating hybrid recommendations."""
    
    def __init__(self):
        # Milvus connection
        self.milvus_host = os.getenv("MILVUS_HOST", "localhost")
        self.milvus_port = os.getenv("MILVUS_PORT", "19530")
        self.milvus_collection = "marketing_embeddings"
        
        # Neo4j connection
        self.neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        
        # Analytics DB connection
        db_type = os.getenv("ANALYTICS_DB_TYPE", "sqlite").lower()
        if db_type == "sqlite":
            db_config = {
                "type": "sqlite",
                "path": os.getenv("ANALYTICS_DB_PATH", "analytics.db")
            }
        else:
            db_config = {
                "type": "postgresql",
                "host": os.getenv("POSTGRES_HOST", "localhost"),
                "port": os.getenv("POSTGRES_PORT", "5432"),
                "database": os.getenv("POSTGRES_DB", "analytics"),
                "user": os.getenv("POSTGRES_USER", "user"),
                "password": os.getenv("POSTGRES_PASSWORD", "password")
            }
        self.analytics_db = AnalyticsDB(db_config)
        
        # Initialize connections (lazy initialization)
        self._milvus_connected = False
        self._neo4j_driver = None
    
    def _ensure_milvus_connection(self):
        """Ensure Milvus connection is established."""
        if not self._milvus_connected:
            try:
                connections.connect("default", host=self.milvus_host, port=self.milvus_port)
                self._milvus_connected = True
                logger.info(f"Connected to Milvus at {self.milvus_host}:{self.milvus_port}")
            except Exception as e:
                logger.error(f"Failed to connect to Milvus: {e}")
                raise
    
    def _get_neo4j_driver(self):
        """Get or create Neo4j driver."""
        if self._neo4j_driver is None:
            try:
                self._neo4j_driver = GraphDatabase.driver(
                    self.neo4j_uri,
                    auth=(self.neo4j_user, self.neo4j_password)
                )
                # Test connection
                with self.neo4j_driver.session() as session:
                    session.run("RETURN 1")
                logger.info(f"Connected to Neo4j at {self.neo4j_uri}")
            except Exception as e:
                logger.error(f"Failed to connect to Neo4j: {e}")
                raise
        return self._neo4j_driver
    
    def get_user_embedding(self, user_id: str) -> Optional[List[float]]:
        """Get average embedding for a user from their messages."""
        try:
            self._ensure_milvus_connection()
            
            if not utility.has_collection(self.milvus_collection):
                logger.warning(f"Collection {self.milvus_collection} does not exist")
                return None
            
            collection = Collection(self.milvus_collection)
            collection.load()
            
            # Query all messages for this user
            results = collection.query(
                expr=f'user_id == "{user_id}"',
                output_fields=["embedding"],
                limit=1000
            )
            
            if not results:
                logger.warning(f"No embeddings found for user {user_id}")
                return None
            
            # Calculate average embedding
            embeddings = [r["embedding"] for r in results]
            avg_embedding = np.mean(embeddings, axis=0).tolist()
            return avg_embedding
            
        except Exception as e:
            logger.error(f"Error getting user embedding: {e}")
            return None
    
    def get_similar_users_vector(self, user_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve top K most similar users via Milvus vector search.
        
        Returns:
            List of similar users with similarity scores
        """
        try:
            # Get user embedding
            user_embedding = self.get_user_embedding(user_id)
            if user_embedding is None:
                logger.warning(f"Could not get embedding for user {user_id}")
                return []
            
            self._ensure_milvus_connection()
            
            if not utility.has_collection(self.milvus_collection):
                logger.warning(f"Collection {self.milvus_collection} does not exist")
                return []
            
            collection = Collection(self.milvus_collection)
            collection.load()
            
            # Search for similar vectors (excluding the query user)
            search_params = {
                "metric_type": "L2",
                "params": {"nprobe": 10}
            }
            
            results = collection.search(
                data=[user_embedding],
                anns_field="embedding",
                param=search_params,
                limit=top_k * 10,  # Get more results to filter
                output_fields=["user_id", "campaign_id", "message"]
            )
            
            # Extract unique users and their similarities
            similar_users = {}
            for hits in results:
                for hit in hits:
                    similar_user_id = hit.entity.get("user_id")
                    if similar_user_id != user_id:  # Exclude query user
                        if similar_user_id not in similar_users:
                            similar_users[similar_user_id] = {
                                "user_id": similar_user_id,
                                "similarity": float(hit.score),
                                "count": 1
                            }
                        else:
                            # Average similarity if user appears multiple times
                            similar_users[similar_user_id]["similarity"] = (
                                similar_users[similar_user_id]["similarity"] + float(hit.score)
                            ) / 2
                            similar_users[similar_user_id]["count"] += 1
            
            # Sort by similarity (lower L2 distance = higher similarity)
            similar_users_list = sorted(
                similar_users.values(),
                key=lambda x: x["similarity"],
                reverse=False  # Lower distance is better
            )[:top_k]
            
            # Normalize similarity scores to 0-1 range (inverse of distance)
            max_distance = max([u["similarity"] for u in similar_users_list]) if similar_users_list else 1.0
            for user in similar_users_list:
                # Convert distance to similarity (1 / (1 + distance))
                user["similarity"] = 1.0 / (1.0 + user["similarity"])
            
            return similar_users_list
            
        except Exception as e:
            logger.error(f"Error in vector search for user {user_id}: {e}")
            return []
    
    def get_campaigns_for_users(self, user_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch campaigns connected to users via Neo4j.
        
        Returns:
            List of campaigns with user associations
        """
        try:
            if not user_ids:
                return []
            
            query = """
            MATCH (u:User)-[:SENT]->(m:Message)-[:ABOUT]->(c:Campaign)
            WHERE u.userId IN $user_ids
            WITH c, COUNT(DISTINCT u) AS user_count, COLLECT(DISTINCT u.userId) AS user_list
            RETURN c.campaignId AS campaign_id, user_count, user_list
            ORDER BY user_count DESC
            """
            
            driver = self._get_neo4j_driver()
            with driver.session() as session:
                results = session.run(query, user_ids=user_ids)
                campaigns = []
                for record in results:
                    campaigns.append({
                        "campaign_id": record["campaign_id"],
                        "user_count": record["user_count"],
                        "user_list": record["user_list"]
                    })
                
                return campaigns
                
        except Exception as e:
            logger.error(f"Error fetching campaigns from Neo4j: {e}")
            return []
    
    def get_campaign_engagement_frequency(self, campaign_ids: List[str]) -> Dict[str, float]:
        """
        Get engagement frequency for campaigns from analytics DB.
        
        Returns:
            Dictionary mapping campaign_id to engagement frequency score
        """
        try:
            df = self.analytics_db.get_campaign_engagement_frequency(campaign_ids)
            
            if df.empty:
                return {}
            
            # Calculate engagement frequency score (normalized)
            max_engagement = df["engagement_count"].max() if not df.empty else 1.0
            engagement_scores = {}
            
            for _, row in df.iterrows():
                campaign_id = row["campaign_id"]
                # Normalize engagement count to 0-1 range
                engagement_scores[campaign_id] = float(row["engagement_count"]) / max_engagement if max_engagement > 0 else 0.0
            
            return engagement_scores
            
        except Exception as e:
            logger.error(f"Error getting campaign engagement frequency: {e}")
            return {}
    
    def get_recommendations(self, user_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Get hybrid recommendations for a user.
        
        Steps:
        1. Retrieve top 5 most similar users (via Milvus vector search)
        2. Fetch campaigns connected to those users (via Neo4j)
        3. Rank results by engagement frequency (from analytics DB)
        
        Returns:
            List of recommended campaigns with scores and explanations
        """
        try:
            # Step 1: Get similar users via vector search
            similar_users = self.get_similar_users_vector(user_id, top_k=5)
            
            if not similar_users:
                logger.warning(f"No similar users found for user {user_id}")
                return []
            
            similar_user_ids = [u["user_id"] for u in similar_users]
            logger.info(f"Found {len(similar_user_ids)} similar users: {similar_user_ids}")
            
            # Step 2: Get campaigns for similar users via Neo4j
            campaigns = self.get_campaigns_for_users(similar_user_ids)
            
            if not campaigns:
                logger.warning(f"No campaigns found for similar users")
                return []
            
            campaign_ids = [c["campaign_id"] for c in campaigns]
            logger.info(f"Found {len(campaign_ids)} campaigns: {campaign_ids}")
            
            # Step 3: Get engagement frequency from analytics DB
            engagement_scores = self.get_campaign_engagement_frequency(campaign_ids)
            
            # Combine scores and rank
            recommendations = []
            for campaign in campaigns:
                campaign_id = campaign["campaign_id"]
                
                # Calculate combined score
                # - User similarity weight: 0.3
                # - User count weight: 0.2
                # - Engagement frequency weight: 0.5
                
                # Average similarity of users who engaged with this campaign
                relevant_users = [u for u in similar_users if u["user_id"] in campaign["user_list"]]
                avg_similarity = np.mean([u["similarity"] for u in relevant_users]) if relevant_users else 0.0
                
                # Normalized user count
                user_count_score = min(campaign["user_count"] / len(similar_user_ids), 1.0) if similar_user_ids else 0.0
                
                # Engagement frequency score
                engagement_score = engagement_scores.get(campaign_id, 0.0)
                
                # Combined score
                combined_score = (
                    0.3 * avg_similarity +
                    0.2 * user_count_score +
                    0.5 * engagement_score
                )
                
                recommendations.append({
                    "campaign_id": campaign_id,
                    "score": float(combined_score),
                    "confidence": float(min(combined_score * 1.2, 1.0)),  # Boost confidence slightly
                    "explanation": f"Recommended because {campaign['user_count']} similar users engaged with this campaign",
                    "metadata": {
                        "similarity_score": float(avg_similarity),
                        "user_count": int(campaign["user_count"]),
                        "engagement_frequency": float(engagement_score),
                        "similar_users": campaign["user_list"][:3]  # Top 3 similar users
                    }
                })
            
            # Sort by combined score (descending)
            recommendations.sort(key=lambda x: x["score"], reverse=True)
            
            # Return top K
            return recommendations[:top_k]
            
        except Exception as e:
            logger.error(f"Error generating recommendations for user {user_id}: {e}", exc_info=True)
            return []


# Global service instance
_recommendation_service = None

def get_recommendation_service() -> RecommendationService:
    """Get or create recommendation service instance."""
    global _recommendation_service
    if _recommendation_service is None:
        _recommendation_service = RecommendationService()
    return _recommendation_service
