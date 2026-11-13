namespace Orders.Domain;

public interface IOrderRepository
{
    Task SaveAsync(Order order);
    Task<Order?> FindAsync(string id);
}

public interface IOrderProcessLauncher
{
    Task StartAsync(string orderId);
}
