import aioredis
import logging
from dotenv import load_dotenv
import os

load_dotenv()
logger = logging.getLogger(__name__)

class RedisManager:
    _instance = None
    _redis = None

    @classmethod
    async def get_instance(cls):
        if not cls._instance:
            cls._instance = RedisManager()
            await cls._instance.initialize()
        return cls._instance

    async def initialize(self):
        try:
            # Handle Railway Redis configuration
            redis_url = os.getenv('REDIS_URL')
            redis_host = os.getenv('REDISHOST')
            redis_port = os.getenv('REDISPORT')
            redis_user = os.getenv('REDISUSER')
            redis_pass = os.getenv('REDIS_PASSWORD')

            # If REDIS_URL is provided, use it directly
            if redis_url:
                connection_url = redis_url
            # Otherwise construct URL from individual components
            elif redis_host and redis_port:
                auth_str = f"{redis_user}:{redis_pass}@" if redis_user and redis_pass else ""
                connection_url = f"redis://{auth_str}{redis_host}:{redis_port}"
            else:
                # Fallback to localhost if no config provided
                connection_url = "redis://localhost:6379"

            self._redis = await aioredis.from_url(
                connection_url,
                encoding='utf-8',
                decode_responses=True
            )
            logger.info("Redis connection established")
            
        except Exception as e:
            logger.error(f"Redis connection error: {e}")
            raise

    # ...rest of existing methods...
