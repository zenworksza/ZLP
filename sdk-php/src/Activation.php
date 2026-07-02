<?php

declare(strict_types=1);

namespace ZenPlatform\ZLF;

class Activation
{
    public static function run(): void
    {
        $authorityUrl = getenv('ZLP_AUTHORITY_URL') ?: 'https://license.yourdomain.com';

        $licenseKey = getenv('ZLP_LICENSE_KEY') ?: self::prompt('License key (ZLP-XXXX-XXXX-XXXX): ');
        $product = getenv('ZLP_PRODUCT') ?: self::prompt('Product slug (e.g. zenmsp): ');
        $domain = getenv('ZLP_DOMAIN') ?: self::prompt('Install domain (e.g. app.customer.com): ');

        $installId = self::generateUuid();
        $machineId = Fingerprint::getMachineId();
        $activationSecret = bin2hex(random_bytes(32));
        $fingerprint = Fingerprint::compute($installId, $domain, $machineId, $activationSecret);

        $payload = json_encode([
            'license_key' => $licenseKey,
            'install_id'  => $installId,
            'domain'      => $domain,
            'fingerprint' => $fingerprint,
            'machine_id'  => $machineId,
            'product'     => $product,
            'version'     => getenv('APP_VERSION') ?: '1.0.0',
        ]);

        $response = self::httpPost($authorityUrl . '/v1/activate', (string) $payload);

        if ($response === false) {
            fwrite(STDERR, "Activation failed: could not reach license authority at $authorityUrl\n");
            exit(1);
        }

        $data = json_decode($response, true);

        if (!isset($data['token'], $data['shared_secret'])) {
            $reason = $data['detail'] ?? $data['error'] ?? 'unknown error';
            fwrite(STDERR, "Activation failed: $reason\n");
            exit(1);
        }

        $cache = new TokenCache($product, $installId);
        $cache->set($data['token'], $data['shared_secret']);

        $baseDir = getenv('ZLP_CACHE_DIR') ?: '/var/lib/zlp';
        $installIdPath = $baseDir . '/' . $product . '/install.id';
        $dir = dirname($installIdPath);
        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }
        file_put_contents($installIdPath, $installId);
        chmod($installIdPath, 0600);

        echo "\nActivation successful!\n\n";
        echo "Set these environment variables on your server:\n";
        echo "  ZLP_INSTALL_ID=$installId\n";
        echo "  ZLP_LICENSE_KEY=$licenseKey\n";
        echo "  ZLP_PRODUCT=$product\n";
        echo "  ZLP_DOMAIN=$domain\n";
        echo "  ZLP_AUTHORITY_URL=$authorityUrl\n";

        if (isset($data['registry_token'])) {
            echo "\nAdd to composer.json to pull SDK updates:\n";
            echo '  "repositories": [{"type":"composer","url":"https://packages.yourdomain.com"}]' . "\n";
            echo '  "config": {"bearer": {"packages.yourdomain.com": "' . $data['registry_token'] . '"}}' . "\n";
        }

        echo "\nAdd to crontab:\n";
        echo "  */15 * * * * php " . ($_SERVER['argv'][0] ?? 'vendor/bin/zlp-agent') . " heartbeat >> /var/log/zlp-agent.log 2>&1\n";
    }

    private static function prompt(string $label): string
    {
        fwrite(STDOUT, $label);
        $value = fgets(STDIN);
        if ($value === false) {
            fwrite(STDERR, "Activation aborted.\n");
            exit(1);
        }
        return trim($value);
    }

    private static function generateUuid(): string
    {
        return sprintf(
            '%s-%s-4%s-%s-%s',
            bin2hex(random_bytes(4)),
            bin2hex(random_bytes(2)),
            substr(bin2hex(random_bytes(2)), 1),
            bin2hex(random_bytes(2)),
            bin2hex(random_bytes(6)),
        );
    }

    private static function httpPost(string $url, string $body): string|false
    {
        if (function_exists('curl_init')) {
            $ch = curl_init($url);
            curl_setopt_array($ch, [
                CURLOPT_POST           => true,
                CURLOPT_POSTFIELDS     => $body,
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_TIMEOUT        => 15,
                CURLOPT_HTTPHEADER     => ['Content-Type: application/json'],
            ]);
            $result = curl_exec($ch);
            $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
            curl_close($ch);

            if ($result === false || ($httpCode !== 200 && $httpCode !== 201)) {
                return false;
            }

            return (string) $result;
        }

        $context = stream_context_create([
            'http' => [
                'method'  => 'POST',
                'header'  => "Content-Type: application/json\r\n",
                'content' => $body,
                'timeout' => 15,
                'ignore_errors' => true,
            ],
        ]);

        $result = file_get_contents($url, false, $context);

        if ($result === false) {
            return false;
        }

        $statusLine = $http_response_header[0] ?? '';
        if (!preg_match('#HTTP/\d+\.\d+\s+(2\d\d)#', $statusLine)) {
            return false;
        }

        return $result;
    }
}
