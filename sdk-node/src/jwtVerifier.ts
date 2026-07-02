import { jwtVerify, importSPKI } from 'jose';
import { DecodedToken, LicenseState } from './types';

const PUBLIC_KEY = `-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA6qKYVAq3Gx77hsPPbFJF
BkogBDo7wVnXamjANNMQDkzHg3kR1Maru+hpytiaYNG62ydhl7qjSFin/4n0saxq
gk2aHLzkG2xPJZl8MailMMQbjpCrVIi3cI9ARpVbwWuLPA5Zu1hfU2G0AKWWn7yE
xqzuUeoy07nu9s320Xzzsdd4zfOvwQvdvcFnWr3VwEbjjKB+dqpeLWYQ8cdYc66+
VW6PtrxLlg45ujIRThiXhJpc4QhV7GPSpAY/sW6UjKtmCbgvRxjfycxIvQoP3Au7
06PmicqsC/94A/g/tgNFfcy0RYqpM89OwCQjz4eC+Nygx0kgjZ0x+5da0ALUHfcz
XwIDAQAB
-----END PUBLIC KEY-----`;

let cachedKey: any = null;

async function getPublicKey() {
  if (!cachedKey) {
    cachedKey = await importSPKI(PUBLIC_KEY, 'RS256');
  }
  return cachedKey;
}

export async function verifyToken(token: string, productSlug: string): Promise<{ state: LicenseState; decoded: DecodedToken | null }> {
  try {
    const key = await getPublicKey();
    const verified = await jwtVerify(token, key, { algorithms: ['RS256'] });
    const decoded = verified.payload as unknown as DecodedToken;

    // Verify required claims
    if (!decoded.install_id || !decoded.product) {
      return { state: LicenseState.INVALID, decoded: null };
    }

    // Verify issuer
    if (decoded.iss !== 'zlp.yourdomain.com') {
      return { state: LicenseState.INVALID, decoded: null };
    }

    // Verify install_id matches this install (prevents token sharing between hosts)
    const localInstallId = process.env.ZLP_INSTALL_ID;
    if (localInstallId && decoded.install_id !== localInstallId) {
      return { state: LicenseState.INVALID, decoded: null };
    }

    // Check if product matches
    if (decoded.product !== productSlug) {
      return { state: LicenseState.INVALID, decoded: null };
    }

    // Check expiry (exp is in seconds, Date.now() is in milliseconds)
    const now = Math.floor(Date.now() / 1000);
    if (decoded.exp && decoded.exp < now) {
      return { state: LicenseState.EXPIRED, decoded: null };
    }

    // C1 — Clock manipulation: reject if local clock is more than 60s behind issuance time
    if (decoded.iat && now < decoded.iat - 60) {
      return { state: LicenseState.INVALID, decoded: null };
    }

    // C1 — Clock manipulation: reject if local clock deviates more than 1920s from server_time
    if (decoded.server_time && Math.abs(now - decoded.server_time) > 1920) {
      return { state: LicenseState.INVALID, decoded: null };
    }

    // Check revocation flag
    if (decoded.revoked === true) {
      return { state: LicenseState.REVOKED, decoded: null };
    }

    return { state: LicenseState.VALID, decoded };
  } catch (error) {
    return { state: LicenseState.INVALID, decoded: null };
  }
}
