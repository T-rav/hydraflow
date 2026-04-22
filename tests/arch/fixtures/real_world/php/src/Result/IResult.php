<?php

declare(strict_types=1);

namespace Example\Result;

/**
 * Marker interface for discriminated-union result values.
 */
interface IResult
{
    public function isSuccess(): bool;

    /** @return mixed */
    public function getValue();

    public function getError(): ?string;
}
