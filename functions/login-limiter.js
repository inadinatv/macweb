function createLoginLimiter({ maxAttempts, windowMs, now = Date.now }) {
  if (!Number.isInteger(maxAttempts) || maxAttempts < 1) throw new TypeError("maxAttempts must be a positive integer");
  if (!Number.isFinite(windowMs) || windowMs < 1) throw new TypeError("windowMs must be positive");

  const failures = new Map();

  function pruneExpired(at) {
    for (const [key, entry] of failures) {
      if (entry.expiresAt <= at) failures.delete(key);
    }
  }

  function boundedStore(at) {
    if (failures.size <= 2048) return;
    pruneExpired(at);
    while (failures.size > 2048) failures.delete(failures.keys().next().value);
  }

  return {
    isBlocked(key) {
      const at = now();
      const entry = failures.get(String(key));
      if (!entry) return false;
      if (entry.expiresAt <= at) {
        failures.delete(String(key));
        return false;
      }
      return entry.count >= maxAttempts;
    },
    recordFailure(key) {
      const at = now();
      const normalizedKey = String(key);
      const current = failures.get(normalizedKey);
      const next = current && current.expiresAt > at
        ? { count: current.count + 1, expiresAt: at + windowMs }
        : { count: 1, expiresAt: at + windowMs };
      failures.set(normalizedKey, next);
      boundedStore(at);
      return next.count;
    },
    clear(key) {
      failures.delete(String(key));
    },
  };
}

module.exports = { createLoginLimiter };
