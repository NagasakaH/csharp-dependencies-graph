namespace Orders.Domain;

public class Order
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Payload { get; set; } = "";
    public OrderStatus Status { get; set; }

    public static Order Create(string payload) => new() { Payload = payload, Status = OrderStatus.Pending };

    public void MarkValidated() => Status = OrderStatus.Validated;
    public void MarkFulfilled() => Status = OrderStatus.Fulfilled;
}

public enum OrderStatus { Pending, Validated, Fulfilled, Rejected }
