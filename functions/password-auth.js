const { createHash, timingSafeEqual } = require("node:crypto");

const MIN_PASSWORD_LENGTH = 16;
const MAX_PASSWORD_LENGTH = 512;

function isPasswordInput(value) {
  return typeof value === "string"
    && value.length >= MIN_PASSWORD_LENGTH
    && value.length <= MAX_PASSWORD_LENGTH
    && !/[\u0000-\u001f\u007f]/.test(value);
}

function matchesPassword(candidate, expected) {
  if (!isPasswordInput(candidate) || !isPasswordInput(expected)) return false;
  const candidateDigest = createHash("sha256").update(candidate, "utf8").digest();
  const expectedDigest = createHash("sha256").update(expected, "utf8").digest();
  return timingSafeEqual(candidateDigest, expectedDigest);
}

module.exports = { isPasswordInput, matchesPassword };
