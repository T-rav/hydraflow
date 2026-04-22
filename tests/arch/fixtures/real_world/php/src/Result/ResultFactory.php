<?php

declare(strict_types=1);

namespace Example\Result;

use Example\Result\IResult;
use Example\Result\Success;
use Example\Result\Failure;

/**
 * Factory helpers for creating typed result instances.
 */
final class ResultFactory
{
    /** @param mixed $value */
    public static function ok(mixed $value): IResult
    {
        return new Success($value);
    }

    public static function fail(string $error): IResult
    {
        return new Failure($error);
    }
}
