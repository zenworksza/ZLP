export { zlpMiddleware, getState, getToken, requireFeature, assertFeature } from './middleware';
export { LicenseState, type DecodedToken, type ZLPConfig } from './types';
export { TokenCache } from './tokenCache';
export { verifyToken } from './jwtVerifier';
export { startLicenseAgent } from './agent';
export { getMachineId, computeFingerprint } from './fingerprint';
export {
  requireFeature as checkFeature,
  withFeature,
  assertFeature as guardFeature,
} from './featureGate';
export { activate } from './activation';
