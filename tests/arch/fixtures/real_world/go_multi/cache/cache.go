// Package cache provides a higher-level caching layer built on top of the lru package.
// Structure inspired by golang/groupcache.
package cache

import "sync"
import "github.com/example/groupcache/lru"

// Stats holds cache statistics.
type Stats struct {
	Gets  int64
	Hits  int64
	Bytes int64
}

// Cache is a thread-safe wrapper around an LRU cache.
type Cache struct {
	mu         sync.Mutex
	lru        *lru.Cache
	nhit, nget int64
	nbytes     int64
	maxBytes   int64
}

// New creates a new Cache with the given byte capacity.
func New(maxBytes int64) *Cache {
	return &Cache{maxBytes: maxBytes}
}

// Add inserts a key-value pair into the cache.
func (c *Cache) Add(key string, value []byte) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.lru == nil {
		c.lru = lru.New(0)
	}
	c.lru.Add(key, value)
	c.nbytes += int64(len(key)) + int64(len(value))
}

// Get retrieves a value from the cache.
func (c *Cache) Get(key string) ([]byte, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.nget++
	if c.lru == nil {
		return nil, false
	}
	v, ok := c.lru.Get(key)
	if !ok {
		return nil, false
	}
	c.nhit++
	return v.([]byte), true
}

// Stats returns a snapshot of cache statistics.
func (c *Cache) Stats() Stats {
	c.mu.Lock()
	defer c.mu.Unlock()
	return Stats{Gets: c.nget, Hits: c.nhit, Bytes: c.nbytes}
}
