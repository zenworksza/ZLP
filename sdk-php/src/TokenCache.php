<?php

namespace ZenPlatform\ZLF;

class TokenCache
{
    private string $cachePath;
    private string $installId;

    public function __construct(string $product = 'zenmsp', string $installId = '')
    {
        $baseDir = getenv('ZLP_CACHE_DIR') ?: '/var/lib/zlp';
        $this->cachePath = $baseDir . '/' . $product . '/' . ($installId ?: 'token.cache');
        $this->installId = $installId;
    }

    public function get(): ?string
    {
        if (!file_exists($this->cachePath)) {
            return null;
        }

        $content = file_get_contents($this->cachePath);

        // Handle both old format (plain JWT) and new format (JSON with token and secret)
        if (strpos($content, '{') === 0) {
            // JSON format
            $data = json_decode($content, true);
            return $data['token'] ?? null;
        }

        return $content;
    }

    public function getSharedSecret(): ?string
    {
        if (!file_exists($this->cachePath)) {
            return null;
        }

        $content = file_get_contents($this->cachePath);

        // Only JSON format has shared_secret
        if (strpos($content, '{') === 0) {
            $data = json_decode($content, true);

            // C2: Decrypt shared_secret if stored in encrypted format (new format)
            if (isset($data['shared_secret_enc'])) {
                return $this->decryptSharedSecret(
                    $data['shared_secret_enc'],
                    $data['shared_secret_iv'] ?? '',
                    $data['shared_secret_tag'] ?? ''
                );
            }

            // Backward compat: plain shared_secret from old format
            return $data['shared_secret'] ?? null;
        }

        return null;
    }

    public function set(string $token, ?string $sharedSecret = null): void
    {
        $dir = dirname($this->cachePath);
        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }

        // C2: Encrypt shared_secret before storing
        $cacheData = [
            'token'      => $token,
            'cached_at'  => time(),
        ];

        if ($sharedSecret !== null) {
            $encrypted = $this->encryptSharedSecret($sharedSecret);
            if ($encrypted !== null) {
                $cacheData['shared_secret_enc'] = $encrypted['enc'];
                $cacheData['shared_secret_iv']  = $encrypted['iv'];
                $cacheData['shared_secret_tag'] = $encrypted['tag'];
            } else {
                // If encryption fails (e.g. missing machine_id), fall back to plain storage
                // but log a warning so it surfaces in monitoring
                error_log('ZLP TokenCache: failed to encrypt shared_secret — storing plain as fallback');
                $cacheData['shared_secret'] = $sharedSecret;
            }
        }

        // Preserve existing machine_id if already stored
        $existingMachineId = $this->getMachineId();
        if ($existingMachineId !== null) {
            $cacheData['machine_id'] = $existingMachineId;
        }

        $content = json_encode($cacheData);
        file_put_contents($this->cachePath, $content, LOCK_EX);
        chmod($this->cachePath, 0600);
    }

    // M3: Read the stored machine_id from the cache file
    public function getMachineId(): ?string
    {
        if (!file_exists($this->cachePath)) {
            return null;
        }

        $content = file_get_contents($this->cachePath);

        if (strpos($content, '{') === 0) {
            $data = json_decode($content, true);
            return $data['machine_id'] ?? null;
        }

        return null;
    }

    // M3: Persist the machine_id into the cache file (called at activation time)
    public function setMachineId(string $machineId): void
    {
        if (!file_exists($this->cachePath)) {
            return;
        }

        $content = file_get_contents($this->cachePath);

        $data = [];
        if (strpos($content, '{') === 0) {
            $data = json_decode($content, true) ?? [];
        } else {
            // Old plain-JWT format — convert to JSON, preserving the raw token
            $data = ['token' => trim($content)];
        }

        $data['machine_id'] = $machineId;

        file_put_contents($this->cachePath, json_encode($data), LOCK_EX);
        chmod($this->cachePath, 0600);
    }

    public function exists(): bool
    {
        return file_exists($this->cachePath);
    }

    public function writeBlocked(): void
    {
        $dir = dirname($this->cachePath);
        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }

        $blockedPath = $dir . '/BLOCKED';
        file_put_contents($blockedPath, "blocked_" . time(), LOCK_EX);
        chmod($blockedPath, 0600);
    }

    public function isBlocked(): bool
    {
        $dir = dirname($this->cachePath);
        $blockedPath = $dir . '/BLOCKED';
        return file_exists($blockedPath);
    }

    // -------------------------------------------------------------------------
    // C2: AES-256-GCM helpers for shared_secret encryption
    // Key = sha256(installId . machine_id) as raw binary (32 bytes)
    // -------------------------------------------------------------------------

    private function deriveEncryptionKey(): ?string
    {
        $machineId = getenv('ZLP_MACHINE_ID');
        if (!$machineId) {
            // Try reading from /etc/machine-id as a fallback
            if (is_readable('/etc/machine-id')) {
                $machineId = trim((string) file_get_contents('/etc/machine-id'));
            }
        }

        if (!$this->installId || !$machineId) {
            return null;
        }

        // Raw binary 32-byte key
        return hash('sha256', $this->installId . $machineId, true);
    }

    /**
     * @return array{enc: string, iv: string, tag: string}|null
     */
    private function encryptSharedSecret(string $plaintext): ?array
    {
        $key = $this->deriveEncryptionKey();
        if ($key === null) {
            return null;
        }

        $iv  = random_bytes(12); // 96-bit IV recommended for GCM
        $tag = '';

        $ciphertext = openssl_encrypt(
            $plaintext,
            'aes-256-gcm',
            $key,
            OPENSSL_RAW_DATA,
            $iv,
            $tag,
            '',
            16
        );

        if ($ciphertext === false) {
            return null;
        }

        return [
            'enc' => base64_encode($ciphertext),
            'iv'  => base64_encode($iv),
            'tag' => base64_encode($tag),
        ];
    }

    private function decryptSharedSecret(string $enc, string $iv, string $tag): ?string
    {
        $key = $this->deriveEncryptionKey();
        if ($key === null) {
            return null;
        }

        $plaintext = openssl_decrypt(
            base64_decode($enc),
            'aes-256-gcm',
            $key,
            OPENSSL_RAW_DATA,
            base64_decode($iv),
            base64_decode($tag)
        );

        return $plaintext !== false ? $plaintext : null;
    }
}
