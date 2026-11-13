using Amazon.Lambda.Core;
using Amazon.SQS;
using Amazon.SQS.Model;
using Orders.Domain;

namespace Orders.Infrastructure;

public class NotifyHandler
{
    private readonly IAmazonSQS _sqs;
    private readonly IOrderRepository _repository;

    public NotifyHandler(IAmazonSQS sqs, IOrderRepository repository)
    {
        _sqs = sqs;
        _repository = repository;
    }

    public async Task FunctionHandler(Dictionary<string, string> message, ILambdaContext context)
    {
        var orderId = message["orderId"];
        var order = await _repository.FindAsync(orderId);
        if (order is null) return;
        order.MarkValidated();
        await _repository.SaveAsync(order);
        await _sqs.SendMessageAsync(new SendMessageRequest { QueueUrl = Environment.GetEnvironmentVariable("FULFIL_QUEUE_URL"), MessageBody = orderId });
    }
}
