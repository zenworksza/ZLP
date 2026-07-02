<?php

namespace ZenPlatform\ZLF;

use GuzzleHttp\Client;
use GuzzleHttp\Exception\RequestException;

class AgentDaemon
{
    private string $product;
    private string $authorityUrl;
    private int $retryCount = 0;
    private const MAX_RETRIES = 3;
    private const BACKOFF_SECONDS = [10, 30, 60];

    public function __construct(string $product = 'zenmsp')
    {
        $this->product = $product;
        $this->authorityUrl = getenv('ZLP_AUTHORITY_URL') ?: 'https://license.yourdomain.com';
    }

    public function run(): int
    {
        try {
            $this->heartbeat();
            return 0;
        } catch (\Exception $e) {
            error_log("ZLP Agent Error: " . $e->getMessage());
            return 1;
        }
    }

    private function heartbeat(): void
    {
        // Get install_id from environment (must be set during activation)
        $installId = getenv('ZLP_INSTALL_ID');
        if (!$installId) {
            error_log("ZLP Agent: ZLP_INSTALL_ID not set");
            return;
        }

        $cache = new TokenCache($this->product, $installId);

        // Check if token exists
        if (!$cache->exists()) {
            error_log("ZLP Agent: No token found - activation required");
            return;
        }

        // Parse current token to validate it exists
        $tokenString = $cache->get();
        if (!$tokenString) {
            error_log("ZLP Agent: Failed to read token from cache");
            return;
        }

        // Get shared_secret from cache
        $sharedSecret = $cache->getSharedSecret();
        if (!$sharedSecret) {
            error_log("ZLP Agent: ZLP_SHARED_SECRET not found in cache - may need re-activation");
            return;
        }

        // Build heartbeat request
        $payload = $this->buildPayload($installId);

        // Try heartbeat with retries
        $this->sendHeartbeatWithRetry($payload, $sharedSecret, $cache);
    }

    private function buildPayload(string $installId): array
    {
        return [
            'install_id' => $installId,
            'license_key' => getenv('ZLP_LICENSE_KEY') ?: '',
            'product' => $this->product,
            'version' => getenv('APP_VERSION') ?: '1.0.0',
            'domain' => $this->getDomain(),
            'fingerprint' => getenv('ZLP_FINGERPRINT') ?: '',
            'machine_id' => Fingerprint::getMachineId(),
            'timestamp' => time(),
            'nonce' => bin2hex(random_bytes(4)),
        ];
    }

    private function getDomain(): string
    {
        return $_SERVER['HTTP_HOST'] ?? php_uname('n') ?? 'unknown';
    }

    private function sendHeartbeatWithRetry(array $payload, string $sharedSecret, TokenCache $cache): void
    {
        $client = new Client(['verify' => true]);

        for ($attempt = 1; $attempt <= self::MAX_RETRIES; $attempt++) {
            try {
                // Sign payload
                $payloadJson = json_encode($payload, JSON_UNESCAPED_SLASHES);
                $signature = hash_hmac('sha256', $payloadJson, $sharedSecret, false);

                // Send request
                $response = $client->post(
                    $this->authorityUrl . '/v1/heartbeat',
                    [
                        'headers' => [
                            'Content-Type' => 'application/json',
                            'X-ZLF-Signature' => $signature,
                            'X-ZLF-Timestamp' => (string)$payload['timestamp'],
                        ],
                        'body' => $payloadJson,
                        'timeout' => 10,
                    ]
                );

                // Parse response
                $responseBody = json_decode((string)$response->getBody(), true);

                if ($responseBody['status'] === 'valid') {
                    // Update token cache with new JWT and shared secret
                    if (isset($responseBody['token']) && isset($responseBody['shared_secret'])) {
                        $cache->set($responseBody['token'], $responseBody['shared_secret']);
                    }

                    error_log("ZLP Agent: Heartbeat successful - install valid");
                    return;
                } else if ($responseBody['status'] === 'revoked') {
                    // License is revoked - hard block
                    $cache->writeBlocked();
                    error_log("ZLP Agent: Heartbeat revoked - " . ($responseBody['reason'] ?? 'unknown'));
                    return;
                } else {
                    // Other error status
                    error_log("ZLP Agent: Heartbeat error - " . ($responseBody['error'] ?? 'unknown'));
                    throw new \Exception("Heartbeat error: " . ($responseBody['error'] ?? 'unknown'));
                }
            } catch (RequestException $e) {
                // Network error - retry with backoff
                if ($attempt < self::MAX_RETRIES) {
                    $backoff = self::BACKOFF_SECONDS[$attempt - 1];
                    error_log("ZLP Agent: Heartbeat attempt $attempt failed, retrying in {$backoff}s");
                    sleep($backoff);
                } else {
                    // All retries exhausted - hard block
                    error_log("ZLP Agent: All heartbeat retries failed - blocking install");
                    $cache->writeBlocked();
                    throw new \Exception("Heartbeat failed after " . self::MAX_RETRIES . " attempts");
                }
            }
        }
    }
}
