import crypto from 'crypto';
import fs from 'fs/promises';
import path from 'path';

function getMachineIdPath(): string {
  const baseDir = process.env.DATA_DIR || '/var/lib/zlp';
  return path.join(baseDir, 'machine.id');
}

export async function getMachineId(): Promise<string> {
  if (process.env.ZLP_MACHINE_ID) {
    return process.env.ZLP_MACHINE_ID;
  }

  const machineIdPath = getMachineIdPath();

  try {
    const existing = await fs.readFile(machineIdPath, 'utf-8');
    return existing.trim();
  } catch {
    // File doesn't exist — generate and persist
  }

  const generated = crypto.randomUUID();

  const dir = path.dirname(machineIdPath);
  try {
    await fs.mkdir(dir, { recursive: true, mode: 0o755 });
  } catch {
    // Directory might already exist
  }
  await fs.writeFile(machineIdPath, generated, { mode: 0o600 });

  return generated;
}

export function computeFingerprint(
  installId: string,
  domain: string,
  machineId: string,
  activationSecret: string,
): string {
  return crypto
    .createHmac('sha256', activationSecret)
    .update(`${installId}:${domain}:${machineId}`)
    .digest('hex');
}
