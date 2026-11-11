// .NET 8+ typed HttpClient. Register via AddHttpClient<RecommendationClient> below.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Net.Http.Json;
using System.Text.Json.Serialization;

public sealed class RecommendationClient(HttpClient http)
{
    public async Task<RecommendationResponse> GetAsync(
        long userId, string category, IEnumerable<long>? recentListingIds = null,
        string? city = null, CancellationToken cancellationToken = default)
    {
        var recent = string.Join(",", (recentListingIds ?? []).TakeLast(10));
        var path = $"recommendations/{userId.ToString(CultureInfo.InvariantCulture)}" +
            $"?category={Uri.EscapeDataString(category)}" +
            $"&recent_listing_ids={Uri.EscapeDataString(recent)}";
        if (!string.IsNullOrWhiteSpace(city))
            path += $"&city={Uri.EscapeDataString(city)}";
        using var response = await http.GetAsync(path, cancellationToken);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<RecommendationResponse>(
            cancellationToken: cancellationToken)
            ?? throw new InvalidOperationException("Recommendation service returned an empty body.");
    }
}

public sealed record RecommendationResponse(
    [property: JsonPropertyName("user_id")] long UserId,
    [property: JsonPropertyName("category")] string Category,
    [property: JsonPropertyName("source")] string Source,
    [property: JsonPropertyName("session_boost_applied")] bool SessionBoostApplied,
    [property: JsonPropertyName("model_version")] string ModelVersion,
    [property: JsonPropertyName("items")] IReadOnlyList<RecommendedListing> Items);

public sealed record RecommendedListing(
    [property: JsonPropertyName("listing_id")] long ListingId,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("city")] string City,
    [property: JsonPropertyName("price")] decimal Price,
    [property: JsonPropertyName("currency")] string Currency,
    [property: JsonPropertyName("score")] double Score,
    [property: JsonPropertyName("reason")] string Reason);

// In Program.cs (your authenticated .NET backend derives userId from claims, not client input):
// builder.Services.AddHttpClient<RecommendationClient>(client =>
// {
//     client.BaseAddress = new Uri(builder.Configuration["Recommendations:BaseUrl"]
//         ?? "http://localhost:8000/");
//     client.Timeout = TimeSpan.FromSeconds(3);
// });
// var picks = await recommendations.GetAsync(userId, "chalet", [12, 47], cancellationToken: ct);
// In production, handle timeout/service failure with a catalog fallback at the .NET boundary.
