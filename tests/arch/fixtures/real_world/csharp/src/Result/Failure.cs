using Example.Result.IResult;

namespace Example.Result;

/// <summary>Represents a failed result carrying an error message.</summary>
public sealed class Failure<T> : IResult<T>
{
    public Failure(string error) => Error = error;

    public bool IsSuccess => false;
    public T? Value => default;
    public string Error { get; }

    public override string ToString() => $"Failure({Error})";
}
