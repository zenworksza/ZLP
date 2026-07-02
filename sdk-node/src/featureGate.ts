import type { NextApiHandler, NextApiRequest, NextApiResponse } from 'next';
import { DecodedToken } from './types';

export function requireFeature(feature: string, token: DecodedToken | null): boolean {
  if (!token) {
    return false;
  }
  return token.features.includes(feature);
}

export function withFeature(feature: string) {
  return (handler: NextApiHandler): NextApiHandler =>
    async (req: NextApiRequest, res: NextApiResponse) => {
      // Token must be injected into res.locals or passed via a custom property;
      // callers should attach the decoded token to req before invoking this HOC.
      const token: DecodedToken | null = (req as any).__zlpToken ?? null;
      if (!requireFeature(feature, token)) {
        res.status(402).json({ error: 'feature_not_licensed' });
        return;
      }
      return handler(req, res);
    };
}

export function assertFeature(feature: string, token: DecodedToken | null): void {
  if (!requireFeature(feature, token)) {
    throw new Error('feature_not_licensed');
  }
}
