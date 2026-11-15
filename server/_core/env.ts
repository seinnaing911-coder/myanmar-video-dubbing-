// Platform values are read at use time. See the Webdev service/authentication skills.
export const ENV = {
  get appId() { return process.env.MANUS_PROJECT_ID ?? ""; },
  get cookieSecret() { return process.env.MANUS_JWT_SECRET ?? ""; },
  get databaseUrl() { return process.env.DATABASE_URL ?? ""; },
  get oAuthServerUrl() { return process.env.MANUS_OAUTH_API_URL ?? ""; },
  // Preserve the legacy hint when supplied; otherwise roles remain application data.
  get ownerOpenId() { return process.env.OWNER_OPEN_ID ?? ""; },
  get isProduction() { return process.env.NODE_ENV === "production"; },
  // Manus-managed web projects inject the built-in LLM gateway values.
  // Keep the legacy MANUS_* names as a fallback for external deployments.
  get forgeApiUrl() { return process.env.BUILT_IN_FORGE_API_URL ?? process.env.MANUS_API_URL ?? ""; },
  get forgeApiKey() { return process.env.BUILT_IN_FORGE_API_KEY ?? process.env.MANUS_API_KEY ?? ""; },
};
