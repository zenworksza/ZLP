<?php

declare(strict_types=1);

namespace ZenPlatform\ZLF;

class FeatureException extends \RuntimeException
{
    public function __construct(string $feature)
    {
        parent::__construct("Feature not licensed: $feature", 402);
    }
}
