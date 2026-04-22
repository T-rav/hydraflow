// Package lru implements a simple LRU cache.
// Structure inspired by golang/groupcache/lru.
package lru

import "container/list"

// Cache is a fixed-size LRU cache.
type Cache struct {
	maxEntries int
	ll         *list.List
	cache      map[interface{}]*list.Element
}

// Entry is a key-value pair stored in the cache.
type Entry struct {
	Key   interface{}
	Value interface{}
}

// New creates a new Cache with the given maximum number of entries.
func New(maxEntries int) *Cache {
	return &Cache{
		maxEntries: maxEntries,
		ll:         list.New(),
		cache:      make(map[interface{}]*list.Element),
	}
}

// Add adds a value to the cache, evicting the oldest entry if at capacity.
func (c *Cache) Add(key, value interface{}) {
	if c.cache == nil {
		c.cache = make(map[interface{}]*list.Element)
		c.ll = list.New()
	}
	if ee, ok := c.cache[key]; ok {
		c.ll.MoveToFront(ee)
		ee.Value.(*Entry).Value = value
		return
	}
	ele := c.ll.PushFront(&Entry{key, value})
	c.cache[key] = ele
	if c.maxEntries != 0 && c.ll.Len() > c.maxEntries {
		c.removeOldest()
	}
}

// Get returns the value for the given key, or nil if absent.
func (c *Cache) Get(key interface{}) (value interface{}, ok bool) {
	if c.cache == nil {
		return
	}
	if ele, hit := c.cache[key]; hit {
		c.ll.MoveToFront(ele)
		return ele.Value.(*Entry).Value, true
	}
	return
}

// Len returns the number of items currently in the cache.
func (c *Cache) Len() int {
	if c.cache == nil {
		return 0
	}
	return c.ll.Len()
}

func (c *Cache) removeOldest() {
	if c.cache == nil {
		return
	}
	ele := c.ll.Back()
	if ele != nil {
		c.ll.Remove(ele)
		kv := ele.Value.(*Entry)
		delete(c.cache, kv.Key)
	}
}
