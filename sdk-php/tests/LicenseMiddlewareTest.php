<?php

declare(strict_types=1);

namespace ZenPlatform\ZLF\Tests;

use Firebase\JWT\JWT;
use PHPUnit\Framework\TestCase;
use ReflectionClass;
use ZenPlatform\ZLF\LicenseMiddleware;
use ZenPlatform\ZLF\LicenseState;

class LicenseMiddlewareTest extends TestCase
{
    private string $tempDir;
    private string $privateKey;

    private const PRIVATE_KEY_PATH = '/home/mdb/workspaces/ZLP/infra/keys/zlp_private.pem';
    private const PRODUCT = 'zenmsp';
    private const INSTALL_ID = 'a3f9c821-1234-5678-abcd-000000000001';
    private const ISS = 'zlp.yourdomain.com';

    protected function setUp(): void
    {
        $this->tempDir = sys_get_temp_dir() . '/zlp-test-' . uniqid('', true);
        mkdir($this->tempDir, 0755, true);
        putenv('ZLP_CACHE_DIR=' . $this->tempDir);

        $this->privateKey = (string) file_get_contents(self::PRIVATE_KEY_PATH);

        $this->resetMiddlewareState();
    }

    protected function tearDown(): void
    {
        $this->removeDirectory($this->tempDir);
        putenv('ZLP_CACHE_DIR');
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private function resetMiddlewareState(): void
    {
        $ref = new ReflectionClass(LicenseMiddleware::class);

        $ref->getProperty('currentState')->setValue(null, null);
        $ref->getProperty('decodedToken')->setValue(null, null);
        $ref->getProperty('installId')->setValue(null, '');
    }

    /** Invoke the private getCurrentState method via reflection. */
    private function resolveState(string $product): LicenseState
    {
        $ref = new ReflectionClass(LicenseMiddleware::class);
        $method = $ref->getMethod('getCurrentState');

        /** @var LicenseState $state */
        $state = $method->invoke(null, $product);

        // Mirror what check() does so getState() returns the same value.
        $stateProp = $ref->getProperty('currentState');
        $stateProp->setValue(null, $state);

        return $state;
    }

    private function makeToken(array $overrides = []): string
    {
        $defaults = [
            'iss'         => self::ISS,
            'sub'         => 'install:' . self::INSTALL_ID,
            'iat'         => time() - 60,
            'exp'         => time() + 1800,
            'license_key' => 'ZLP-TEST-AAAA-BBBB',
            'product'     => self::PRODUCT,
            'plan'        => 'professional',
            'seats'       => 10,
            'features'    => ['ms365', 'contracts'],
            'domain'      => 'app.customer.com',
            'install_id'  => self::INSTALL_ID,
            'revoked'     => false,
        ];

        $payload = array_merge($defaults, $overrides);

        return JWT::encode($payload, $this->privateKey, 'RS256');
    }

    private function writeCacheFile(string $token, string $product = self::PRODUCT): void
    {
        $dir = $this->tempDir . '/' . $product;
        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }

        $data = json_encode([
            'token'         => $token,
            'shared_secret' => base64_encode(random_bytes(32)),
            'cached_at'     => time() * 1000,
        ]);

        file_put_contents($dir . '/token.cache', $data, LOCK_EX);
    }

    private function writeInstallId(string $installId, string $product = self::PRODUCT): void
    {
        $dir = $this->tempDir . '/' . $product;
        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }

        file_put_contents($dir . '/install.id', $installId);
    }

    private function writeBlockedFile(string $product = self::PRODUCT): void
    {
        $dir = $this->tempDir . '/' . $product;
        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }

        file_put_contents($dir . '/BLOCKED', 'blocked_' . time(), LOCK_EX);
    }

    private function removeDirectory(string $path): void
    {
        if (!is_dir($path)) {
            return;
        }

        foreach ((array) scandir($path) as $entry) {
            if ($entry === '.' || $entry === '..') {
                continue;
            }

            $full = $path . '/' . $entry;
            is_dir($full) ? $this->removeDirectory($full) : unlink($full);
        }

        rmdir($path);
    }

    // -------------------------------------------------------------------------
    // Tests
    // -------------------------------------------------------------------------

    /** @test */
    public function test_pending_state_when_no_cache_file(): void
    {
        // Empty temp dir — no cache file exists.
        $state = $this->resolveState(self::PRODUCT);

        $this->assertSame(LicenseState::PENDING, $state);
    }

    /** @test */
    public function test_valid_state_with_good_token(): void
    {
        $this->writeCacheFile($this->makeToken());
        $this->writeInstallId(self::INSTALL_ID);

        $state = $this->resolveState(self::PRODUCT);

        $this->assertSame(LicenseState::VALID, $state);
        $this->assertSame(LicenseState::VALID, LicenseMiddleware::getState());
    }

    /** @test */
    public function test_expired_state_with_expired_token(): void
    {
        // firebase/php-jwt v6 throws ExpiredException which LicenseMiddleware catches
        // explicitly and maps to LicenseState::EXPIRED.
        $token = $this->makeToken([
            'iat' => time() - 3600,
            'exp' => time() - 1800,
        ]);

        $this->writeCacheFile($token);

        $state = $this->resolveState(self::PRODUCT);

        $this->assertSame(LicenseState::EXPIRED, $state);
    }

    /** @test */
    public function test_invalid_state_with_bad_signature(): void
    {
        // Generate a token with a different (throwaway) key so the signature won't
        // verify against the embedded public key.
        $badKey = openssl_pkey_new([
            'digest_alg'       => 'sha256',
            'private_key_bits' => 2048,
            'private_key_type' => OPENSSL_KEYTYPE_RSA,
        ]);

        openssl_pkey_export($badKey, $badPrivateKeyPem);

        $tampered = JWT::encode([
            'iss'        => self::ISS,
            'sub'        => 'install:' . self::INSTALL_ID,
            'iat'        => time() - 60,
            'exp'        => time() + 1800,
            'product'    => self::PRODUCT,
            'install_id' => self::INSTALL_ID,
            'revoked'    => false,
        ], $badPrivateKeyPem, 'RS256');

        $this->writeCacheFile($tampered);

        $state = $this->resolveState(self::PRODUCT);

        $this->assertSame(LicenseState::INVALID, $state);
    }

    /** @test */
    public function test_revoked_state_with_blocked_file(): void
    {
        // Even with a valid token present, BLOCKED file wins.
        $this->writeCacheFile($this->makeToken());
        $this->writeBlockedFile();

        $state = $this->resolveState(self::PRODUCT);

        $this->assertSame(LicenseState::REVOKED, $state);
    }

    /** @test */
    public function test_revoked_flag_in_token(): void
    {
        $token = $this->makeToken(['revoked' => true]);
        $this->writeCacheFile($token);

        $state = $this->resolveState(self::PRODUCT);

        $this->assertSame(LicenseState::REVOKED, $state);
    }

    /** @test */
    public function test_invalid_iss_claim(): void
    {
        $token = $this->makeToken(['iss' => 'evil.attacker.com']);
        $this->writeCacheFile($token);

        $state = $this->resolveState(self::PRODUCT);

        $this->assertSame(LicenseState::INVALID, $state);
    }

    /** @test */
    public function test_install_id_mismatch(): void
    {
        // install.id on disk differs from the install_id claim in the JWT.
        $this->writeInstallId('ffffffff-0000-0000-0000-000000000000');
        $this->writeCacheFile($this->makeToken());

        $state = $this->resolveState(self::PRODUCT);

        $this->assertSame(LicenseState::INVALID, $state);
    }
}
