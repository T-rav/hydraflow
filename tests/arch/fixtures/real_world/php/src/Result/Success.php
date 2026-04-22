<?php

declare(strict_types=1);

namespace Example\Result;

use Example\Result\IResult;

/**
 * Represents a successful result wrapping a value.
 */
final class Success implements IResult
{
    /** @param mixed $value */
    public function __construct(private readonly mixed $value) {}

    public function isSuccess(): bool
    {
        return true;
    }

    /** @return mixed */
    public function getValue(): mixed
    {
        return $this->value;
    }

    public function getError(): ?string
    {
        return null;
    }

    public function __toString(): string
    {
        return sprintf('Success(%s)', $this->value);
    }
}
