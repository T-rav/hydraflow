package com.example.result

import com.example.result.IResult
import com.example.result.Success
import com.example.result.Failure

/**
 * Factory functions for creating typed result instances.
 */
object ResultFactory {
    fun <T> ok(value: T): IResult<T> = Success(value)
    fun <T> fail(error: String): IResult<T> = Failure(error)
}
