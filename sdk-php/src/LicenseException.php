<?php

namespace ZenPlatform\ZLF;

class LicenseException extends \Exception
{
    public function __construct(
        public LicenseState $state,
        string $message = '',
        ?\Throwable $previous = null,
    ) {
        parent::__construct($message ?: $state->value, previous: $previous);
    }
}
