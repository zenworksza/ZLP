import crypto from 'crypto';
import fs from 'fs/promises';
import path from 'path';
import readline from 'readline';
import { getMachineId, computeFingerprint } from './fingerprint';
import { TokenCache } from './tokenCache';

interface ActivationOptions {
  licenseKey?: string;
  product?: string;
  domain?: string;
  authorityUrl?: string;
}

interface ActivationResponse {
  shared_secret: string;
  registry_token: string;
  token: string;
}

interface ActivationErrorResponse {
  detail?: string;
  error?: string;
}

function prompt(rl: readline.Interface, question: string): Promise<string> {
  return new Promise(resolve => rl.question(question, resolve));
}

export async function activate(options: ActivationOptions = {}): Promise<void> {
  const authorityUrl =
    options.authorityUrl ||
    process.env.ZLP_AUTHORITY_URL ||
    'https://license.yourdomain.com';

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  let licenseKey = options.licenseKey || process.env.ZLP_LICENSE_KEY || '';
  let product = options.product || process.env.ZLP_PRODUCT || '';
  let domain = options.domain || process.env.ZLP_DOMAIN || '';

  try {
    if (!licenseKey) {
      licenseKey = await prompt(rl, 'License key (ZLP-XXXX-XXXX-XXXX): ');
    }
    if (!product) {
      product = await prompt(rl, 'Product slug (e.g. zenmsp): ');
    }
    if (!domain) {
      domain = await prompt(rl, 'Install domain (e.g. app.customer.com): ');
    }
  } finally {
    rl.close();
  }

  licenseKey = licenseKey.trim();
  product = product.trim();
  domain = domain.trim();

  if (!licenseKey || !product || !domain) {
    console.error('[ZLP] license_key, product, and domain are required');
    process.exit(1);
  }

  const installId = crypto.randomUUID();
  const machineId = await getMachineId();

  // Initial activation secret is local-only; server returns the real shared_secret.
  const initialSecret = crypto.randomBytes(32).toString('hex');
  const fingerprint = computeFingerprint(installId, domain, machineId, initialSecret);

  const body = {
    license_key: licenseKey,
    install_id: installId,
    domain,
    fingerprint,
    machine_id: machineId,
    product,
    version: process.env.APP_VERSION || '1.0.0',
  };

  let response: Response;
  try {
    response = await fetch(`${authorityUrl}/v1/activate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (err) {
    console.error('[ZLP] Activation request failed:', (err as Error).message);
    process.exit(1);
  }

  if (!response.ok) {
    let reason = `HTTP ${response.status}`;
    try {
      const errBody = (await response.json()) as ActivationErrorResponse;
      reason = errBody.detail || errBody.error || reason;
    } catch {
      // ignore parse error
    }
    console.error(`[ZLP] Activation failed: ${reason}`);
    process.exit(1);
  }

  const data = (await response.json()) as ActivationResponse;

  const cache = TokenCache.getInstance(product);
  await cache.set(data.token, data.shared_secret);

  // Persist install_id so middleware can validate JWT install_id binding
  const baseDir = process.env.DATA_DIR ?? '/var/lib/zlp';
  const installIdPath = path.join(baseDir, product, 'install.id');
  await fs.mkdir(path.dirname(installIdPath), { recursive: true, mode: 0o755 });
  await fs.writeFile(installIdPath, installId, { mode: 0o600 });

  console.log('[ZLP] Activation successful.');
  console.log(`[ZLP] install_id: ${installId}`);
  console.log('');
  console.log('[ZLP] Add the following to your .npmrc to access the package registry:');
  console.log(`//npm.yourdomain.com/:_authToken=${data.registry_token}`);
  console.log('@zenplatform:registry=https://npm.yourdomain.com');
  console.log('');
  console.log('[ZLP] Set these environment variables on your server:');
  console.log(`ZLP_INSTALL_ID=${installId}`);
  console.log(`ZLP_LICENSE_KEY=${licenseKey}`);
  console.log(`ZLP_PRODUCT=${product}`);
  console.log(`ZLP_DOMAIN=${domain}`);
}

// CLI entry point
if (import.meta.url === new URL(process.argv[1], 'file://').href) {
  const args = process.argv.slice(2);
  const command = args[0];

  if (command !== 'activate') {
    console.error(`[ZLP] Unknown command: ${command ?? '(none)'}`);
    console.error('[ZLP] Usage: zlp activate');
    process.exit(1);
  }

  activate().catch(err => {
    console.error('[ZLP] Fatal error:', err);
    process.exit(1);
  });
}
