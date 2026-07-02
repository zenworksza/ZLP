<?php

declare(strict_types=1);

namespace ZenPlatform\ZLF;

class Fingerprint
{
    private const MACHINE_ID_SYSTEM = '/etc/machine-id';
    private const MACHINE_ID_VOLUME = '/var/lib/zlp/machine.id';

    public static function getMachineId(): string
    {
        if (is_file(self::MACHINE_ID_SYSTEM)) {
            return trim((string) file_get_contents(self::MACHINE_ID_SYSTEM));
        }

        if (is_file(self::MACHINE_ID_VOLUME)) {
            return trim((string) file_get_contents(self::MACHINE_ID_VOLUME));
        }

        $uuid = self::generateUuid();
        $dir = dirname(self::MACHINE_ID_VOLUME);

        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }

        file_put_contents(self::MACHINE_ID_VOLUME, $uuid);
        chmod(self::MACHINE_ID_VOLUME, 0600);

        return $uuid;
    }

    public static function compute(
        string $installId,
        string $domain,
        string $machineId,
        string $activationSecret,
    ): string {
        $data = $installId . ':' . $domain . ':' . $machineId;
        return hash_hmac('sha256', $data, $activationSecret);
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
}
