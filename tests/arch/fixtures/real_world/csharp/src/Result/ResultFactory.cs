using Example.Result.IResult;
using Example.Result.Success;
using Example.Result.Failure;

namespace Example.Result;

/// <summary>Factory helpers for creating typed result instances.</summary>
public static class ResultFactory
{
    public static IResult<T> Ok<T>(T value) => new Success<T>(value);
    public static IResult<T> Fail<T>(string error) => new Failure<T>(error);
}
