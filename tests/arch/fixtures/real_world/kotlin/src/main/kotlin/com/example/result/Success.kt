package com.example.result

import com.example.result.IResult

/**
 * Represents a successful result wrapping a value.
 */
data class Success<out T>(override val value: T) : IResult<T> {
    override val isSuccess: Boolean = true
    override val error: String? = null

    override fun toString(): String = "Success($value)"
}
