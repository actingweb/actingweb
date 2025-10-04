# ActingWeb Caching Implementation Guide

## Overview

This document provides guidance for implementing intelligent caching in ActingWeb endpoints to improve performance. Based on the successful MCP endpoint optimization that achieved 50x performance improvement (50ms → 1ms), this pattern can be applied to other endpoints and the code can possibly be generalized and reused.

## Cache Architecture

### Core Components

```python
# Global cache structure (per endpoint)
_token_cache: Dict[str, Dict[str, Any]] = {}
_actor_cache: Dict[str, Dict[str, Any]] = {}
_trust_cache: Dict[str, Any] = {}
_cache_ttl = 300  # 5 minutes

# Cache entry structure
cache_entry = {
    'data': actual_data,
    'timestamp': time.time(),
    'ttl': 300
}
```

### Cache Key Strategy

Use composite keys for maximum cache efficiency:

```python
# Token cache: "token_hash:actor_id"
token_key = f"{hashlib.sha256(token.encode()).hexdigest()[:16]}:{actor_id}"

# Actor cache: "actor_id:property_subset"
actor_key = f"{actor_id}:basic"  # for basic actor info
actor_key = f"{actor_id}:full"   # for full actor with properties

# Trust cache: "actor_id:relationship_type"
trust_key = f"{actor_id}:peer_relationships"
trust_key = f"{actor_id}:trust_types"
```

## Implementation Pattern

### 1. Cache-Enabled Authentication

```python
def authenticate_and_get_actor_cached(self) -> Any:
    """Cached version of authentication with ~1ms response time"""
    
    # Extract and validate token
    token = self.extract_token()
    if not token:
        return None
    
    # Check token cache first
    token_key = f"{hashlib.sha256(token.encode()).hexdigest()[:16]}:{self.actor_id}"
    
    if token_key in _token_cache:
        entry = _token_cache[token_key]
        if time.time() - entry['timestamp'] < entry['ttl']:
            # Cache hit - return cached data
            return entry['data']
        else:
            # Cache expired - remove entry
            del _token_cache[token_key]
    
    # Cache miss - perform full authentication
    result = self.authenticate_and_get_actor_uncached()
    
    # Store in cache if successful
    if result:
        _token_cache[token_key] = {
            'data': result,
            'timestamp': time.time(),
            'ttl': _cache_ttl
        }
    
    return result
```

### 2. Cached Database Queries

```python
def get_trust_relationships_cached(self, actor_id: str) -> List[Dict[str, Any]]:
    """Cache trust relationships for faster repeated access"""
    
    cache_key = f"{actor_id}:trust_relationships"
    
    # Check cache first
    if cache_key in _trust_cache:
        entry = _trust_cache[cache_key]
        if time.time() - entry['timestamp'] < entry['ttl']:
            return entry['data']
        else:
            del _trust_cache[cache_key]
    
    # Cache miss - query database
    trust_list = self.actor.trust.get()
    relationships = []
    for trust in trust_list:
        relationships.append({
            'peer': trust['peer'],
            'type': trust.get('type', 'friend'),
            'relationship': trust.get('relationship', 'friend'),
            'established_via': trust.get('established_via'),
        })
    
    # Cache the results
    _trust_cache[cache_key] = {
        'data': relationships,
        'timestamp': time.time(),
        'ttl': _cache_ttl
    }
    
    return relationships
```

### 3. Cache Invalidation

```python
def invalidate_actor_cache(self, actor_id: str) -> None:
    """Invalidate all cache entries for a specific actor"""
    
    # Invalidate token cache entries
    keys_to_remove = [k for k in _token_cache.keys() if k.endswith(f":{actor_id}")]
    for key in keys_to_remove:
        del _token_cache[key]
    
    # Invalidate actor cache entries  
    keys_to_remove = [k for k in _actor_cache.keys() if k.startswith(f"{actor_id}:")]
    for key in keys_to_remove:
        del _actor_cache[key]
    
    # Invalidate trust cache entries
    keys_to_remove = [k for k in _trust_cache.keys() if k.startswith(f"{actor_id}:")]
    for key in keys_to_remove:
        del _trust_cache[key]

def on_trust_modified(self, actor_id: str) -> None:
    """Call this when trust relationships change"""
    trust_keys = [k for k in _trust_cache.keys() if k.startswith(f"{actor_id}:")]
    for key in trust_keys:
        del _trust_cache[key]
```

## Endpoints to Optimize

### High Priority (Frequent Access)

1. **OAuth2 Endpoints** (`oauth2_endpoints.py`)
   - `/oauth/authorize` - Cache authorization checks
   - `/oauth/token` - Cache token validation
   - `/oauth/userinfo` - Cache user profile data

2. **Properties Handler** (`properties.py`)
   - `GET /{actor}/properties` - Cache property lists
   - `GET /{actor}/properties/{prop}` - Cache individual properties

3. **Trust Handler** (`trust.py`)
   - `GET /{actor}/trust` - Cache trust relationship lists
   - Trust validation during requests

4. **Base Handler Authentication** (`base_handler.py`)
   - Token validation and actor loading
   - Permission checks

### Medium Priority

1. **Subscriptions Handler** (`subscriptions.py`)
   - Subscription list retrieval
   - Event routing decisions

2. **Methods Handler** (`methods.py`)
   - Available methods discovery
   - Method permission checks

3. **Actions Handler** (`actions.py`)
   - Action permission validation
   - Action metadata retrieval

## Cache Configuration

### TTL Guidelines

```python
# Authentication and tokens (short TTL for security)
AUTH_CACHE_TTL = 300  # 5 minutes

# Actor basic info (medium TTL)
ACTOR_CACHE_TTL = 900  # 15 minutes

# Properties (longer TTL, less frequent changes)
PROPERTY_CACHE_TTL = 1800  # 30 minutes

# Trust relationships (medium TTL)
TRUST_CACHE_TTL = 600  # 10 minutes

# Static data (longest TTL)
METADATA_CACHE_TTL = 3600  # 1 hour
```

### Memory Management

```python
def cleanup_expired_cache() -> None:
    """Periodic cleanup of expired cache entries"""
    current_time = time.time()
    
    # Clean token cache
    expired_keys = [
        k for k, v in _token_cache.items() 
        if current_time - v['timestamp'] > v['ttl']
    ]
    for key in expired_keys:
        del _token_cache[key]
    
    # Repeat for other caches...

# Call periodically or implement LRU eviction
def setup_cache_cleanup():
    import threading
    import time
    
    def cleanup_worker():
        while True:
            time.sleep(60)  # Clean every minute
            cleanup_expired_cache()
    
    cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
    cleanup_thread.start()
```

## Performance Monitoring

### Cache Hit Rate Tracking

```python
_cache_stats = {
    'token_hits': 0,
    'token_misses': 0,
    'actor_hits': 0,
    'actor_misses': 0,
    'trust_hits': 0,
    'trust_misses': 0,
}

def record_cache_hit(cache_type: str):
    _cache_stats[f'{cache_type}_hits'] += 1

def record_cache_miss(cache_type: str):
    _cache_stats[f'{cache_type}_misses'] += 1

def get_cache_hit_rate(cache_type: str) -> float:
    hits = _cache_stats.get(f'{cache_type}_hits', 0)
    misses = _cache_stats.get(f'{cache_type}_misses', 0)
    total = hits + misses
    return (hits / total * 100) if total > 0 else 0
```

### Performance Logging

```python
def log_cache_performance(endpoint: str, duration: float, cache_hit: bool):
    """Log performance metrics for monitoring"""
    status = "HIT" if cache_hit else "MISS"
    logging.info(f"CACHE {status} {endpoint}: {duration:.1f}ms")
    
    # Optional: Send to metrics system
    if hasattr(self, 'metrics_client'):
        self.metrics_client.timing(f'cache.{endpoint}.duration', duration)
        self.metrics_client.incr(f'cache.{endpoint}.{status.lower()}')
```

## Security Considerations

### Token Security

```python
def secure_token_key(token: str, actor_id: str) -> str:
    """Create secure cache key without storing full token"""
    # Use first 16 chars of SHA256 hash for security
    token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
    return f"{token_hash}:{actor_id}"
```

### Cache Data Sanitization

```python
def sanitize_for_cache(data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove sensitive data before caching"""
    sensitive_fields = ['password', 'secret', 'private_key', 'token']
    
    sanitized = {}
    for key, value in data.items():
        if key.lower() not in sensitive_fields:
            sanitized[key] = value
    
    return sanitized
```

## Testing Cache Implementation

### Unit Tests

```python
def test_cache_hit_performance():
    """Test that cache hits are significantly faster"""
    
    # First call (cache miss)
    start = time.time()
    result1 = handler.get_data_cached()
    miss_duration = time.time() - start
    
    # Second call (cache hit)
    start = time.time() 
    result2 = handler.get_data_cached()
    hit_duration = time.time() - start
    
    # Cache hit should be at least 10x faster
    assert hit_duration < miss_duration / 10
    assert result1 == result2

def test_cache_expiration():
    """Test that cache entries expire correctly"""
    
    # Set short TTL for test
    handler._cache_ttl = 1
    
    result1 = handler.get_data_cached()
    time.sleep(2)  # Wait for expiration
    result2 = handler.get_data_cached()
    
    # Should have made fresh database call
    assert handler.db_call_count == 2
```

### Load Testing

```python
def benchmark_endpoint_performance():
    """Benchmark cached vs uncached performance"""
    
    import concurrent.futures
    import statistics
    
    def make_request():
        start = time.time()
        response = client.get("/endpoint")
        return time.time() - start
    
    # Test with cache
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        cached_times = list(executor.map(lambda x: make_request(), range(100)))
    
    # Clear cache and test without
    handler.clear_cache()
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        uncached_times = list(executor.map(lambda x: make_request(), range(100)))
    
    print(f"Cached median: {statistics.median(cached_times):.3f}s")
    print(f"Uncached median: {statistics.median(uncached_times):.3f}s")
    print(f"Improvement: {statistics.median(uncached_times) / statistics.median(cached_times):.1f}x")
```

## Implementation Checklist

When adding caching to an endpoint:

- [ ] Identify cacheable data and access patterns
- [ ] Choose appropriate cache keys and TTL values
- [ ] Implement cache-enabled methods with fallback
- [ ] Add cache invalidation logic for data mutations
- [ ] Include performance logging and hit rate tracking
- [ ] Add unit tests for cache behavior
- [ ] Document cache behavior and maintenance requirements
- [ ] Consider memory usage and implement cleanup
- [ ] Validate security implications of cached data
- [ ] Monitor performance improvements in production

## Common Pitfalls

1. **Caching Mutable Data**: Don't cache references to mutable objects
2. **Missing Invalidation**: Always invalidate cache when underlying data changes
3. **Security Leaks**: Never cache sensitive data like passwords or tokens
4. **Memory Leaks**: Implement proper cache cleanup and size limits
5. **Cache Stampede**: Use cache warming or locking for expensive operations
6. **Stale Data**: Choose appropriate TTL values for data freshness requirements
7. **Key Collisions**: Use sufficiently unique cache keys with proper prefixing

## Future Enhancements

1. **Distributed Caching**: Consider Redis for multi-instance deployments
2. **Cache Warming**: Pre-populate cache with frequently accessed data
3. **Intelligent Prefetching**: Predict and cache likely-needed data
4. **Cache Partitioning**: Separate caches by data type and access patterns
5. **Metrics Integration**: Send cache metrics to monitoring systems
6. **Configuration Management**: Make cache settings configurable per environment
