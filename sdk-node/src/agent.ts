import crypto from 'crypto';
import { TokenCache } from './tokenCache';
import { getMachineId } from './fingerprint';

const MAX_RETRIES = 3;
const BACKOFF_SECONDS = [10, 30, 60];

interface HeartbeatPayload {
  install_id: string;
  license_key: string;
  product: string;
  version: string;
  domain: string;
  fingerprint: string;
  timestamp: number;
  nonce: string;
  machine_id: string;
}

interface HeartbeatResponse {
  status: 'valid' | 'revoked' | 'error';
  token?: string;
  shared_secret?: string;
  reason?: string;
  error?: string;
}

export async function startLicenseAgent(options: {
  product: string;
  intervalMs?: number;
  authorityUrl?: string;
}): Promise<void> {
  const {
    product,
    intervalMs = 15 * 60 * 1000, // 15 minutes
    authorityUrl = process.env.ZLP_AUTHORITY_URL || 'https://license.yourdomain.com',
  } = options;

  console.log(`[ZLP Agent] Starting license agent for product: ${product} (interval: ${intervalMs}ms)`);

  // Run heartbeat immediately on startup
  await runHeartbeat(product, authorityUrl);

  // Then run every interval
  setInterval(async () => {
    await runHeartbeat(product, authorityUrl);
  }, intervalMs);
}

async function runHeartbeat(product: string, authorityUrl: string): Promise<void> {
  try {
    const installId = process.env.ZLP_INSTALL_ID;
    if (!installId) {
      console.log('[ZLP Agent] Missing ZLP_INSTALL_ID');
      return;
    }

    const cache = TokenCache.getInstance(product);

    // Check if blocked
    if (await cache.isBlocked()) {
      console.log('[ZLP Agent] Install is blocked - hard block in effect');
      return;
    }

    // Check if token exists
    const token = await cache.get();
    if (!token) {
      console.log('[ZLP Agent] No token found - activation required');
      return;
    }

    // Get shared_secret from cache
    const sharedSecret = await cache.getSharedSecret();
    if (!sharedSecret) {
      console.log('[ZLP Agent] ZLP_SHARED_SECRET not found in cache - may need re-activation');
      return;
    }

    // Build payload
    const payload = await buildPayload(installId);

    // Send with retry
    await sendHeartbeatWithRetry(payload, sharedSecret, cache, authorityUrl);
  } catch (error) {
    console.error('[ZLP Agent] Heartbeat error:', error);
  }
}

async function buildPayload(installId: string): Promise<HeartbeatPayload> {
  return {
    install_id: installId,
    license_key: process.env.ZLP_LICENSE_KEY || '',
    product: process.env.ZLP_PRODUCT || 'zenmsp',
    version: process.env.APP_VERSION || '1.0.0',
    domain: process.env.ZLP_DOMAIN || getDomain(),
    fingerprint: process.env.ZLP_FINGERPRINT || '',
    timestamp: Math.floor(Date.now() / 1000),
    nonce: crypto.randomBytes(4).toString('hex'),
    machine_id: await getMachineId(),
  };
}

function getDomain(): string {
  return process.env.VERCEL_URL ||
         process.env.HOSTNAME ||
         (typeof window !== 'undefined' && window.location?.hostname) ||
         'unknown';
}

async function sendHeartbeatWithRetry(
  payload: HeartbeatPayload,
  sharedSecret: string,
  cache: ReturnType<typeof TokenCache.getInstance>,
  authorityUrl: string,
): Promise<void> {
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      // Sign payload
      const payloadJson = JSON.stringify(payload);
      const signature = crypto
        .createHmac('sha256', sharedSecret)
        .update(payloadJson)
        .digest('hex');

      // Send request
      const response = await fetch(`${authorityUrl}/v1/heartbeat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-ZLF-Signature': signature,
          'X-ZLF-Timestamp': String(payload.timestamp),
        },
        body: payloadJson,
      });

      // Parse response
      const responseBody = (await response.json()) as HeartbeatResponse;

      if (responseBody.status === 'valid') {
        // Update token and secret in cache, preserving the existing machine_id
        if (responseBody.token && responseBody.shared_secret) {
          await cache.set(responseBody.token, responseBody.shared_secret, cache.getMachineId() ?? undefined);
        }

        console.log('[ZLP Agent] Heartbeat successful - install valid');
        return;
      } else if (responseBody.status === 'revoked') {
        // License is revoked - hard block
        await cache.writeBlocked();
        console.log('[ZLP Agent] Heartbeat revoked:', responseBody.reason);
        return;
      } else {
        // Other error
        console.error('[ZLP Agent] Heartbeat error:', responseBody.error);
        throw new Error(`Heartbeat error: ${responseBody.error}`);
      }
    } catch (error) {
      if (attempt < MAX_RETRIES) {
        const backoff = BACKOFF_SECONDS[attempt - 1];
        console.log(`[ZLP Agent] Heartbeat attempt ${attempt} failed, retrying in ${backoff}s`);
        await sleep(backoff * 1000);
      } else {
        // All retries exhausted - hard block
        console.error('[ZLP Agent] All heartbeat retries failed - blocking install');
        await cache.writeBlocked();
        throw new Error(`Heartbeat failed after ${MAX_RETRIES} attempts`);
      }
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
