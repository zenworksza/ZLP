<?php

namespace ZenPlatform\ZLF;

use Firebase\JWT\JWT;
use Firebase\JWT\Key;

class LicenseMiddleware
{
    private const PUBLIC_KEY = <<<'EOK'
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA6qKYVAq3Gx77hsPPbFJF
BkogBDo7wVnXamjANNMQDkzHg3kR1Maru+hpytiaYNG62ydhl7qjSFin/4n0saxq
gk2aHLzkG2xPJZl8MailMMQbjpCrVIi3cI9ARpVbwWuLPA5Zu1hfU2G0AKWWn7yE
xqzuUeoy07nu9s320Xzzsdd4zfOvwQvdvcFnWr3VwEbjjKB+dqpeLWYQ8cdYc66+
VW6PtrxLlg45ujIRThiXhJpc4QhV7GPSpAY/sW6UjKtmCbgvRxjfycxIvQoP3Au7
06PmicqsC/94A/g/tgNFfcy0RYqpM89OwCQjz4eC+Nygx0kgjZ0x+5da0ALUHfcz
XwIDAQAB
-----END PUBLIC KEY-----
EOK;

    // JWT_TTL is 1800 s (30 min) per spec — used in clock-skew validation (C1)
    private const JWT_TTL = 1800;

    private static ?LicenseState $currentState = null;
    private static ?object $decodedToken = null;
    private static string $installId = '';

    public static function check(string $productSlug): void
    {
        try {
            self::$currentState = self::getCurrentState($productSlug);

            if (self::$currentState !== LicenseState::VALID) {
                http_response_code(402);
                exit(json_encode([
                    'error' => 'license_required',
                    'state' => self::$currentState->value,
                ]));
            }
        } catch (LicenseException $e) {
            http_response_code(402);
            exit(json_encode([
                'error' => 'license_required',
                'state' => $e->state->value,
            ]));
        }
    }

    public static function getState(): LicenseState
    {
        if (self::$currentState !== null) {
            return self::$currentState;
        }

        return LicenseState::PENDING;
    }

    public static function getToken(): ?object
    {
        return self::$decodedToken;
    }

    private static function getCurrentState(string $productSlug): LicenseState
    {
        $cache = new TokenCache($productSlug);

        // Check if install is blocked (hard block from agent)
        if ($cache->isBlocked()) {
            return LicenseState::REVOKED;
        }

        // Check if token exists
        if (!$cache->exists()) {
            return LicenseState::PENDING;
        }

        $tokenString = $cache->get();
        if (!$tokenString) {
            return LicenseState::PENDING;
        }

        try {
            // M1 — Algorithm confusion guard: firebase/php-jwt pins the algorithm
            // via the Key constructor second argument. Passing 'RS256' here means
            // the library will ONLY accept RS256-signed tokens and will throw if
            // the token header specifies any other algorithm (including 'none' or
            // 'HS256'). No additional alg-whitelist step is required because the
            // Key object itself encodes the allowed algorithm.
            self::$decodedToken = JWT::decode($tokenString, new Key(self::PUBLIC_KEY, 'RS256'));
        } catch (\Firebase\JWT\ExpiredException) {
            return LicenseState::EXPIRED;
        } catch (\Exception) {
            return LicenseState::INVALID;
        }

        // C1 — Clock manipulation: reject tokens issued in the future (clock rolled back).
        // Allow 60 s of legitimate skew; anything beyond that is suspicious.
        $iat = (int)(self::$decodedToken->iat ?? 0);
        if (time() < $iat - 60) {
            return LicenseState::INVALID;
        }

        // C1 — Clock manipulation: if the authority embeds a server_time claim,
        // verify that the local clock is within JWT_TTL (1800 s) + 120 s skew buffer.
        // A larger deviation means the local clock has been manipulated to extend token
        // validity or the token is being replayed far outside its intended window.
        if (isset(self::$decodedToken->server_time)
            && abs(time() - (int)self::$decodedToken->server_time) > self::JWT_TTL + 120
        ) {
            return LicenseState::INVALID;
        }

        if (empty(self::$decodedToken->install_id) || empty(self::$decodedToken->product)) {
            return LicenseState::INVALID;
        }

        if ((self::$decodedToken->iss ?? '') !== 'zlp.yourdomain.com') {
            return LicenseState::INVALID;
        }

        $localInstallId = self::readInstallId($productSlug);
        if ($localInstallId !== null && self::$decodedToken->install_id !== $localInstallId) {
            return LicenseState::INVALID;
        }

        self::$installId = self::$decodedToken->install_id;

        if (isset(self::$decodedToken->revoked) && self::$decodedToken->revoked === true) {
            return LicenseState::REVOKED;
        }

        if (self::$decodedToken->product !== $productSlug) {
            return LicenseState::INVALID;
        }

        // M2 — Domain claim: compare the domain in the JWT against the HTTP_HOST header.
        // Only enforced in HTTP context (HTTP_HOST is absent in CLI/cron contexts).
        // Port numbers are stripped before comparison; matching is case-insensitive.
        $httpHost    = strtolower(preg_replace('/:\d+$/', '', $_SERVER['HTTP_HOST'] ?? ''));
        $tokenDomain = strtolower(preg_replace('/:\d+$/', '', self::$decodedToken->domain ?? ''));
        if ($httpHost !== '' && $tokenDomain !== '' && $httpHost !== $tokenDomain) {
            return LicenseState::INVALID;
        }

        // M3 — Local fingerprint: verify that the machine_id recorded at activation
        // matches the machine_id of the current host. A mismatch means the token cache
        // has been copied to a different machine.
        $storedMachineId  = $cache->getMachineId();
        $currentMachineId = self::readCurrentMachineId();
        if ($storedMachineId !== null
            && $currentMachineId !== null
            && $storedMachineId !== $currentMachineId
        ) {
            return LicenseState::INVALID;
        }

        return LicenseState::VALID;
    }

    private static function readInstallId(string $productSlug): ?string
    {
        $baseDir = getenv('ZLP_CACHE_DIR') ?: '/var/lib/zlp';
        $path = $baseDir . '/' . $productSlug . '/install.id';
        if (is_file($path)) {
            return trim((string) file_get_contents($path));
        }
        return null;
    }

    // M3 — Read the current host's machine identifier.
    // Primary source: /etc/machine-id (bare-metal and most Linux distros).
    // Fallback:       ZLP_MACHINE_ID env var (Docker / serverless where
    //                 /etc/machine-id either doesn't exist or maps to the host).
    private static function readCurrentMachineId(): ?string
    {
        if (is_readable('/etc/machine-id')) {
            $id = trim((string) file_get_contents('/etc/machine-id'));
            if ($id !== '') {
                return $id;
            }
        }

        $envId = getenv('ZLP_MACHINE_ID');
        return ($envId !== false && $envId !== '') ? $envId : null;
    }

    public static function requireFeature(string $feature): void
    {
        self::check(self::$decodedToken->product ?? '');

        if (self::$currentState !== LicenseState::VALID) {
            http_response_code(402);
            exit(json_encode(['error' => 'license_required']));
        }

        $features = self::$decodedToken->features ?? [];
        if (!in_array($feature, $features, true)) {
            http_response_code(402);
            exit(json_encode(['error' => 'feature_not_licensed']));
        }
    }
}
