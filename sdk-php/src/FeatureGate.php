<?php

declare(strict_types=1);

namespace ZenPlatform\ZLF;

use Firebase\JWT\JWT;
use Firebase\JWT\Key;

class FeatureGate
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

    public static function hasFeature(array $payload, string $feature): bool
    {
        $features = $payload['features'] ?? [];
        return in_array($feature, $features, true);
    }

    public static function requireFeature(string $product, string $feature): void
    {
        $cache = new TokenCache($product);
        $tokenString = $cache->get();

        if ($tokenString === null) {
            throw new FeatureException($feature);
        }

        try {
            $decoded = JWT::decode($tokenString, new Key(self::PUBLIC_KEY, 'RS256'));
            $features = (array) ($decoded->features ?? []);

            if (!in_array($feature, $features, true)) {
                throw new FeatureException($feature);
            }
        } catch (FeatureException $e) {
            throw $e;
        } catch (\Exception) {
            throw new FeatureException($feature);
        }
    }
}
