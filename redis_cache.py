import redis
import json
import os
from dotenv import load_dotenv
import logging
from typing import Optional, Any
from urllib.parse import urlparse

load_dotenv()
logger = logging.getLogger(__name__)

class RedisCache:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisCache, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize Redis connection using Railway's environment variables"""
        try:
            # Get all possible Redis env variables from Railway
            redis_url = os.getenv('REDIS_URL') or os.getenv('REDIS_PUBLIC_URL')
            redis_host = os.getenv('REDISHOST')
            redis_port = os.getenv('REDISPORT')
            redis_password = os.getenv('REDIS_PASSWORD') or os.getenv('REDISPASSWORD')
            redis_user = os.getenv('REDISUSER')
            
            if redis_url:
                # Prefer URL-based connection if available
                self.redis = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    ssl=True,
                    ssl_cert_reqs=None
                )
            elif redis_host:
                # Fallback to individual connection parameters
                self.redis = redis.Redis(
                    host=redis_host,
                    port=int(redis_port or 6379),
                    username=redis_user,
                    password=redis_password,
                    decode_responses=True,
                    ssl=True,
                    ssl_cert_reqs=None
                )
            else:
                # Local development fallback
                self.redis = redis.Redis(
                    host='localhost',
                    port=6379,
                    decode_responses=True
                )
            
            # Test connection
            self.redis.ping()
            logger.info("Redis cache initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis: {e}")
            self.redis = None

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            if not self.redis:
                return None
            value = self.redis.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None

    async def set(self, key: str, value: Any, expire: int = 3600) -> bool:
        """Set value in cache with expiration"""
        try:
            if not self.redis:
                return False
            return self.redis.setex(key, expire, json.dumps(value))
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        try:
            if not self.redis:
                return False
            return bool(self.redis.delete(key))
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return False

# Create singleton instance
redis_cache = RedisCache()
