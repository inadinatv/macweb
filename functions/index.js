const { initializeApp } = require("firebase-admin/app");
const { getAuth } = require("firebase-admin/auth");
const { defineSecret } = require("firebase-functions/params");
const { HttpsError, onCall } = require("firebase-functions/v2/https");
const { isPasswordInput, matchesPassword } = require("./password-auth");
const { createLoginLimiter } = require("./login-limiter");

initializeApp();

const adminPassword = defineSecret("MACWEB_ADMIN_PASSWORD");
const loginLimiter = createLoginLimiter({ maxAttempts: 5, windowMs: 15 * 60 * 1000 });

exports.macwebAdminLogin = onCall(
  {
    region: "us-central1",
    enforceAppCheck: true,
    maxInstances: 1,
    secrets: [adminPassword],
  },
  async (request) => {
    if (!request.app) {
      throw new HttpsError("failed-precondition", "App verification required.");
    }

    const suppliedPassword = request.data && request.data.password;
    const expectedPassword = adminPassword.value();
    const callerIp = String(request.rawRequest && request.rawRequest.ip || "unknown").slice(0, 128);
    if (loginLimiter.isBlocked(callerIp)) {
      throw new HttpsError("resource-exhausted", "Too many login attempts.");
    }
    if (!isPasswordInput(suppliedPassword) || !matchesPassword(suppliedPassword, expectedPassword)) {
      loginLimiter.recordFailure(callerIp);
      throw new HttpsError("unauthenticated", "Admin credentials are invalid.");
    }

    loginLimiter.clear(callerIp);
    const token = await getAuth().createCustomToken("macweb-admin", { admin: true });
    return { token };
  }
);
