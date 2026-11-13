using Amazon.Lambda.APIGatewayEvents;
using Amazon.Lambda.Core;
using Orders.Domain;
using Orders.Infrastructure;

namespace Orders.Api;

public class Functions
{
    private readonly IOrderRepository _repository;
    private readonly IOrderProcessLauncher _launcher;

    public Functions(IOrderRepository repository, IOrderProcessLauncher launcher)
    {
        _repository = repository;
        _launcher = launcher;
    }

    public async Task<APIGatewayProxyResponse> CreateOrder(APIGatewayProxyRequest request, ILambdaContext context)
    {
        var order = Order.Create(request.Body);
        await _repository.SaveAsync(order);
        context.Logger.LogInformation("order created {Id}", order.Id);
        await _launcher.StartAsync(order.Id);
        return Respond(201, order);
    }

    public async Task<APIGatewayProxyResponse> GetOrder(APIGatewayProxyRequest request, ILambdaContext context)
    {
        var id = request.PathParameters["id"];
        var order = await _repository.FindAsync(id);
        return order is null ? Respond(404, null) : Respond(200, order);
    }

    private static APIGatewayProxyResponse Respond(int status, object? body)
        => new() { StatusCode = status, Body = body?.ToString() };
}
