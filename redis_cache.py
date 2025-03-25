import redis
import json
import os
from dotenv import load_dotenv
import logging
from typing import Optional, Any, List
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

    async def keys(self, pattern: str) -> List[str]:
        """Get all keys matching pattern"""
        try:
            if not self.redis:
                return []
            return self.redis.keys(pattern)
        except Exception as e:
            logger.error(f"Redis keys error: {e}")
            return []

    async def scan_iter(self, pattern: str) -> List[str]:
        """Scan keys matching pattern (more efficient than keys)"""
        try:
            if not self.redis:
                return []
            return [key for key in self.redis.scan_iter(pattern)]
        except Exception as e:
            logger.error(f"Redis scan error: {e}")
            return []

    async def check_cache(self, keyword: str) -> dict:
        """Check cache status for a keyword"""
        try:
            if not self.redis:
                return {"status": "disconnected"}
                
            pattern = f"*{keyword}*"
            all_keys = await self.scan_iter(pattern)
            cache_data = {}
            
            for key in all_keys:
                value = self.redis.get(key)
                ttl = self.redis.ttl(key)
                cache_data[key] = {
                    "value": value,
                    "ttl": ttl
                }
                
            return {
                "status": "connected",
                "total_keys": len(all_keys),
                "data": cache_data
            }
            
        except Exception as e:
            logger.error(f"Redis check cache error: {e}")
            return {"status": "error", "message": str(e)}

    async def debug_info(self) -> dict:
        """Get Redis debug information"""
        try:
            if not self.redis:
                return {"status": "disconnected"}
                
            info = self.redis.info()
            return {
                "status": "connected",
                "used_memory": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
                "total_keys": len(self.redis.keys("*")),
                "uptime_days": info.get("uptime_in_days")
            }
            
        except Exception as e:
            logger.error(f"Redis debug info error: {e}")
            return {"status": "error", "message": str(e)}

# Create singleton instance
redis_cache = RedisCache()

# Add command to check Redis cache
async def check_redis_command(event, client):
    """Handle /redischeck command"""
    if event.sender_id not in AUTHORIZED_USER_IDS:
        await event.reply("You are not authorized to use this command.")
        return

    try:
        # Get debug info
        debug_info = await redis_cache.debug_info()
        
        # Get cache info for current search if available
        cache_info = None
        if event.message.text:
            parts = event.message.text.split(maxsplit=1)
            if len(parts) > 1:
                keyword = parts[1]
                cache_info = await redis_cache.check_cache(keyword)

        # Format response
        response = "📊 Redis Cache Status:\n\n"
        response += f"Status: {debug_info['status']}\n"
        if debug_info['status'] == 'connected':
            response += f"Memory Used: {debug_info['used_memory']}\n"
            response += f"Connected Clients: {debug_info['connected_clients']}\n"
            response += f"Total Keys: {debug_info['total_keys']}\n"
            response += f"Uptime (days): {debug_info['uptime_days']}\n"
            
        if cache_info:
            response += f"\n🔍 Cache for '{keyword}':\n"
            response += f"Found Keys: {cache_info['total_keys']}\n"
            if cache_info['total_keys'] > 0:
                for key, data in cache_info['data'].items():
                    response += f"\nKey: {key}\n"
                    response += f"TTL: {data['ttl']}s\n"

        await event.reply(response)
        
    except Exception as e:
        logger.error(f"Redis check command error: {e}")
        await event.reply("Error checking Redis cache status.")

# Add this to your setup_bot_handlers function
    client.add_event_handler(
        lambda e: check_redis_command(e, client),
        events.NewMessage(pattern='/redischeck')
    )
