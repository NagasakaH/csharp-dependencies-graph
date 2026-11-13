using Microsoft.Extensions.DependencyInjection;
using Orders.Domain;
using Orders.Infrastructure;

namespace Orders.Api;

public static class Startup
{
    public static IServiceProvider Build()
    {
        var services = new ServiceCollection();
        services.AddSingleton<IOrderRepository, DynamoDbOrderRepository>();
        services.AddSingleton<IOrderProcessLauncher, StepFunctionsOrderProcessLauncher>();
        services.AddSingleton<Functions>();
        return services.BuildServiceProvider();
    }
}
