export enum LicenseState {
  PENDING = 'PENDING',
  VALID = 'VALID',
  EXPIRED = 'EXPIRED',
  INVALID = 'INVALID',
  REVOKED = 'REVOKED',
}

export interface DecodedToken {
  iss: string;
  sub: string;
  iat: number;
  exp: number;
  license_key: string;
  product: string;
  plan: string;
  seats: number;
  features: string[];
  domain: string;
  install_id: string;
  revoked: boolean;
  server_time?: number;
}

export interface ZLPConfig {
  product: string;
  publicPaths?: string[];
}
