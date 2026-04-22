package com.example.result

/**
 * Marker interface for discriminated-union result values.
 * Inspired by kotlin-result (michaelbull/kotlin-result, Apache-2.0).
 */
interface IResult<out T> {
    val isSuccess: Boolean
    val value: T?
    val error: String?
}
