namespace Example.Result;

/// <summary>Marker interface for discriminated-union result values.</summary>
public interface IResult<T>
{
    bool IsSuccess { get; }
    T? Value { get; }
    string? Error { get; }
}
