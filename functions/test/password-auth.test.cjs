const test = require("node:test");
const assert = require("node:assert/strict");
const { isPasswordInput, matchesPassword } = require("../password-auth");

const TEST_PASSWORD = "unit-test-only-passphrase-123";

test("admin password validation enforces bounds and rejects control characters", () => {
  assert.equal(isPasswordInput(TEST_PASSWORD), true);
  assert.equal(isPasswordInput("too-short"), false);
  assert.equal(isPasswordInput("x".repeat(513)), false);
  assert.equal(isPasswordInput("valid-length\n-invalid"), false);
  assert.equal(isPasswordInput(null), false);
});

test("admin password comparison accepts only exact matching secret", () => {
  assert.equal(matchesPassword(TEST_PASSWORD, TEST_PASSWORD), true);
  assert.equal(matchesPassword(TEST_PASSWORD, "different-test-password-456"), false);
  assert.equal(matchesPassword(TEST_PASSWORD, ""), false);
  assert.equal(matchesPassword("short", TEST_PASSWORD), false);
});
