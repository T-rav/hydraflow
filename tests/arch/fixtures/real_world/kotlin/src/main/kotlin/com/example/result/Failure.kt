package com.example.result

import com.example.result.IResult

/**
 * Represents a failed result carrying an error message.
 */
data class Failure<out T>(override val error: String) : IResult<T> {
    override val isSuccess: Boolean = false
    override val value: T? = null

    override fun toString(): String = "Failure($error)"
}
