import fs from 'fs/promises';
import path from 'path';

interface CacheData {
  token: string;
  shared_secret?: string;
  cached_at: number;
  machine_id?: string;
}

export class TokenCache {
  private static instance: TokenCache;
  private cachedToken: string | null = null;
  private cachedSecret: string | null = null;
  private cachedMachineId: string | null = null;
  private cachePath: string;

  private constructor(product: string = 'zenmsp') {
    const baseDir = process.env.DATA_DIR || '/var/lib/zlp';
    this.cachePath = path.join(baseDir, product, 'token.cache');
  }

  static getInstance(product: string = 'zenmsp'): TokenCache {
    if (!TokenCache.instance) {
      TokenCache.instance = new TokenCache(product);
    }
    return TokenCache.instance;
  }

  async get(): Promise<string | null> {
    if (this.cachedToken) {
      return this.cachedToken;
    }

    try {
      const content = await fs.readFile(this.cachePath, 'utf-8');

      // Handle both old format (plain JWT) and new format (JSON)
      if (content.trim().startsWith('{')) {
        const data: CacheData = JSON.parse(content);
        this.cachedToken = data.token;
        this.cachedSecret = data.shared_secret || null;
        this.cachedMachineId = data.machine_id || null;
        return data.token;
      }

      this.cachedToken = content;
      return content;
    } catch {
      return null;
    }
  }

  async getSharedSecret(): Promise<string | null> {
    if (this.cachedSecret) {
      return this.cachedSecret;
    }

    try {
      const content = await fs.readFile(this.cachePath, 'utf-8');

      // Only JSON format has shared_secret
      if (content.trim().startsWith('{')) {
        const data: CacheData = JSON.parse(content);
        this.cachedSecret = data.shared_secret || null;
        return data.shared_secret || null;
      }

      return null;
    } catch {
      return null;
    }
  }

  getMachineId(): string | null {
    return this.cachedMachineId;
  }

  setMachineId(machineId: string): void {
    this.cachedMachineId = machineId;
  }

  async set(token: string, sharedSecret?: string, machineId?: string): Promise<void> {
    const dir = path.dirname(this.cachePath);
    try {
      await fs.mkdir(dir, { recursive: true, mode: 0o755 });
    } catch {
      // Directory might already exist
    }

    const cacheData: CacheData = {
      token,
      shared_secret: sharedSecret,
      cached_at: Date.now(),
      machine_id: machineId,
    };

    const content = JSON.stringify(cacheData);
    await fs.writeFile(this.cachePath, content, { mode: 0o600 });
    this.cachedToken = token;
    this.cachedSecret = sharedSecret || null;
    this.cachedMachineId = machineId || null;
  }

  async exists(): Promise<boolean> {
    try {
      await fs.access(this.cachePath);
      return true;
    } catch {
      return false;
    }
  }

  clear(): void {
    this.cachedToken = null;
  }

  async writeBlocked(): Promise<void> {
    const dir = path.dirname(this.cachePath);
    try {
      await fs.mkdir(dir, { recursive: true, mode: 0o755 });
    } catch {
      // Directory might already exist
    }

    const blockedPath = path.join(dir, 'BLOCKED');
    await fs.writeFile(blockedPath, `blocked_${Date.now()}`, { mode: 0o600 });
  }

  async isBlocked(): Promise<boolean> {
    try {
      const dir = path.dirname(this.cachePath);
      const blockedPath = path.join(dir, 'BLOCKED');
      await fs.access(blockedPath);
      return true;
    } catch {
      return false;
    }
  }
}
