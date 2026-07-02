<?php

namespace ZenPlatform\ZLF;

enum LicenseState: string
{
    case PENDING = 'PENDING';
    case VALID = 'VALID';
    case EXPIRED = 'EXPIRED';
    case INVALID = 'INVALID';
    case REVOKED = 'REVOKED';
}
