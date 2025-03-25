import redis
import json
import logging
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class RedisCache:
    def __init__(self):
        self.redis = None
        self.cache_ttl = 3600  # 1 hour cache
        self.init()  # Initialize when instance is created

    def init(self):
        try:
            redis_url = os.getenv('REDIS_URL')
            if not redis_url:
                redis_url = f"redis://{os.getenv('REDISUSER')}:{os.getenv('REDIS_PASSWORD')}@{os.getenv('REDISHOST')}:{os.getenv('REDISPORT')}"
            
            self.redis = redis.from_url(
                redis_url,
                decode_responses=True
            )
            logger.info("Redis cache initialized")
        except Exception as e:
            logger.error(f"Redis initialization error: {e}")
            self.redis = None

    def set_search_results(self, query: str, results: list, page: int = 1):
        """Cache search results"""
        if not self.redis:
            return
        try:
            cache_key = f"search:{query}:page:{page}"
            self.redis.setex(
                cache_key,
                self.cache_ttl,
                json.dumps(results)
            )
        except Exception as e:
            logger.error(f"Redis cache set error: {e}")

    def get_search_results(self, query: str, page: int = 1):
        """Get cached search results"""
        if not self.redis:
            return None
        try:
            cache_key = f"search:{query}:page:{page}"
            cached = self.redis.get(cache_key)
            if cached:
                return json.loads(cached)
            return None
        except Exception as e:
            logger.error(f"Redis cache get error: {e}")
            return None

    def clear_cache(self):
        """Clear all cached data"""
        if not self.redis:
            return
        try:
            self.redis.flushdb()
            logger.info("Cache cleared")
        except Exception as e:
            logger.error(f"Redis cache clear error: {e}")

redis_cache = RedisCache()  # Create a singleton instance
