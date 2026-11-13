using Amazon.StepFunctions;
using Amazon.StepFunctions.Model;
using Orders.Domain;

namespace Orders.Infrastructure;

public class StepFunctionsOrderProcessLauncher : IOrderProcessLauncher
{
    private readonly IAmazonStepFunctions _stepFunctions;

    public StepFunctionsOrderProcessLauncher(IAmazonStepFunctions stepFunctions) => _stepFunctions = stepFunctions;

    public async Task StartAsync(string orderId)
    {
        var request = new StartExecutionRequest
        {
            StateMachineArn = Environment.GetEnvironmentVariable("ORDER_PROCESS_ARN")!,
            Input = $"{{\"orderId\":\"{orderId}\"}}"
        };
        await _stepFunctions.StartExecutionAsync(request);
    }
}
