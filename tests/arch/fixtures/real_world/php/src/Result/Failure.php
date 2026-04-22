<?php

declare(strict_types=1);

namespace Example\Result;

use Example\Result\IResult;

/**
 * Represents a failed result carrying an error message.
 */
final class Failure implements IResult
{
    public function __construct(private readonly string $error) {}

    public function isSuccess(): bool
    {
        return false;
    }

    /** @return null */
    public function getValue(): mixed
    {
        return null;
    }

    public function getError(): ?string
    {
        return $this->error;
    }

    public function __toString(): string
    {
        return sprintf('Failure(%s)', $this->error);
    }
}
