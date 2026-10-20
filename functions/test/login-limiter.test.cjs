const test = require("node:test");
const assert = require("node:assert/strict");
const { createLoginLimiter } = require("../login-limiter");

test("login limiter five wrong attempts block the IP for the current window", () => {
  let now = 1_000;
  const limiter = createLoginLimiter({ maxAttempts: 5, windowMs: 15 * 60 * 1000, now: () => now });
  for (let i = 0; i < 5; i++) {
    assert.equal(limiter.isBlocked("203.0.113.4"), false);
    limiter.recordFailure("203.0.113.4");
  }
  assert.equal(limiter.isBlocked("203.0.113.4"), true);
  assert.equal(limiter.isBlocked("203.0.113.5"), false, "different IPs have separate counters");
  now += 15 * 60 * 1000 + 1;
  assert.equal(limiter.isBlocked("203.0.113.4"), false, "expired window allows retry");
});

test("successful login clears that IP's failed-attempt counter", () => {
  const limiter = createLoginLimiter({ maxAttempts: 2, windowMs: 60_000, now: () => 10_000 });
  limiter.recordFailure("test-ip");
  limiter.recordFailure("test-ip");
  assert.equal(limiter.isBlocked("test-ip"), true);
  limiter.clear("test-ip");
  assert.equal(limiter.isBlocked("test-ip"), false);
});
