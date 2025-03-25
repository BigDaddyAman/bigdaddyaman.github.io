import aioredis
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

    async def init(self):
        try:
            redis_url = os.getenv('REDIS_URL')
            if not redis_url:
                redis_url = f"redis://{os.getenv('REDISUSER')}:{os.getenv('REDIS_PASSWORD')}@{os.getenv('REDISHOST')}:{os.getenv('REDISPORT')}"
            
            self.redis = await aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            logger.info("Redis cache initialized")
        except Exception as e:
            logger.error(f"Redis initialization error: {e}")
            raise

    async def set_search_results(self, query: str, results: list, page: int = 1):
        """Cache search results"""
        try:
            cache_key = f"search:{query}:page:{page}"
            await self.redis.setex(
                cache_key,
                self.cache_ttl,
                json.dumps(results)
            )
        except Exception as e:
            logger.error(f"Redis cache set error: {e}")

    async def get_search_results(self, query: str, page: int = 1):
        """Get cached search results"""
        try:
            cache_key = f"search:{query}:page:{page}"
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)
            return None
        except Exception as e:
            logger.error(f"Redis cache get error: {e}")
            return None

    async def set_file_info(self, file_id: str, file_info: dict):
        """Cache file information"""
        try:
            cache_key = f"file:{file_id}"
            await self.redis.setex(
                cache_key,
                self.cache_ttl,
                json.dumps(file_info)
            )
        except Exception as e:
            logger.error(f"Redis cache set error: {e}")

    async def get_file_info(self, file_id: str):
        """Get cached file information"""
        try:
            cache_key = f"file:{file_id}"
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)
            return None
        except Exception as e:
            logger.error(f"Redis cache get error: {e}")
            return None

    async def clear_cache(self):
        """Clear all cached data"""
        try:
            await self.redis.flushdb()
            logger.info("Cache cleared")
        except Exception as e:
            logger.error(f"Redis cache clear error: {e}")
