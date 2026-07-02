import fs from 'fs';
import path from 'path';
import { NextRequest, NextResponse } from 'next/server';
import { LicenseState, ZLPConfig } from './types';
import { TokenCache } from './tokenCache';
import { verifyToken } from './jwtVerifier';

let currentState: LicenseState = LicenseState.PENDING;
let decodedToken: any = null;

export async function zlpMiddleware(config: ZLPConfig) {
  return async (request: NextRequest) => {
    const pathname = request.nextUrl.pathname;

    // Skip license check for public paths
    if (config.publicPaths?.some(path => pathname.startsWith(path))) {
      return NextResponse.next();
    }

    // Get current license state
    const state = await getCurrentState(config.product);

    // Only VALID state is allowed
    if (state !== LicenseState.VALID) {
      return NextResponse.json(
        { error: 'license_required', state },
        { status: 402 }
      );
    }

    // M2 — Domain claim validation: compare Host header against token domain claim
    const decoded = getToken();
    if (decoded?.domain) {
      const rawHost = request.headers.get('host') ?? '';
      const requestHost = rawHost.split(':')[0].toLowerCase();
      const tokenDomain = decoded.domain.split(':')[0].toLowerCase();
      if (requestHost && tokenDomain && requestHost !== tokenDomain) {
        return NextResponse.json(
          { error: 'domain_mismatch' },
          { status: 402 }
        );
      }
    }

    // M3 — Machine ID validation: compare stored machine_id against current machine_id
    const cache = TokenCache.getInstance(config.product);
    const storedMachineId = cache.getMachineId();
    if (storedMachineId) {
      const currentMachineId = readCurrentMachineId();
      if (currentMachineId && currentMachineId !== storedMachineId) {
        return NextResponse.json(
          { error: 'machine_id_mismatch' },
          { status: 402 }
        );
      }
    }

    return NextResponse.next();
  };
}

async function getCurrentState(productSlug: string): Promise<LicenseState> {
  const cache = TokenCache.getInstance(productSlug);

  // Check if install is blocked (hard block from agent)
  if (await cache.isBlocked()) {
    currentState = LicenseState.REVOKED;
    return currentState;
  }

  // Check if token exists
  if (!(await cache.exists())) {
    currentState = LicenseState.PENDING;
    return currentState;
  }

  const tokenString = await cache.get();
  if (!tokenString) {
    currentState = LicenseState.PENDING;
    return currentState;
  }

  // Verify and decode token
  const { state, decoded } = await verifyToken(tokenString, productSlug);
  currentState = state;
  decodedToken = decoded;

  return state;
}

export function getState(): LicenseState {
  return currentState;
}

export function getToken(): any {
  return decodedToken;
}

function readCurrentMachineId(): string | null {
  // Prefer explicit env var (serverless / edge deployments)
  if (process.env.ZLP_MACHINE_ID) {
    return process.env.ZLP_MACHINE_ID;
  }

  const dataDir = process.env.DATA_DIR || '/var/lib/zlp';
  const machineIdPath = path.join(dataDir, 'machine.id');

  try {
    return fs.readFileSync(machineIdPath, 'utf-8').trim();
  } catch {
    return null;
  }
}

// Feature gate for API routes
export function requireFeature(feature: string) {
  return async (handler: (req: NextRequest) => Promise<NextResponse>) => {
    return async (req: NextRequest) => {
      if (currentState !== LicenseState.VALID) {
        return NextResponse.json(
          { error: 'license_required' },
          { status: 402 }
        );
      }

      const features = decodedToken?.features ?? [];
      if (!features.includes(feature)) {
        return NextResponse.json(
          { error: 'feature_not_licensed' },
          { status: 402 }
        );
      }

      return handler(req);
    };
  };
}

// RSC helper to check feature
export function assertFeature(feature: string): void {
  if (currentState !== LicenseState.VALID) {
    throw new Error('License required');
  }

  const features = decodedToken?.features ?? [];
  if (!features.includes(feature)) {
    throw new Error('Feature not licensed');
  }
}
