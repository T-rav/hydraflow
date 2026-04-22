using Example.Result.IResult;

namespace Example.Result;

/// <summary>Represents a successful result wrapping a value.</summary>
public sealed class Success<T> : IResult<T>
{
    public Success(T value) => Value = value;

    public bool IsSuccess => true;
    public T Value { get; }
    public string? Error => null;

    public override string ToString() => $"Success({Value})";
}
