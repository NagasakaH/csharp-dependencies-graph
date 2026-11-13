using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.DataModel;
using Orders.Domain;

namespace Orders.Infrastructure;

public class DynamoDbOrderRepository : IOrderRepository
{
    private readonly IAmazonDynamoDB _dynamoDb;
    private readonly DynamoDBContext _context;

    public DynamoDbOrderRepository(IAmazonDynamoDB dynamoDb)
    {
        _dynamoDb = dynamoDb;
        _context = new DynamoDBContext(dynamoDb);
    }

    public async Task SaveAsync(Order order) => await _context.SaveAsync(order, "orders");

    public async Task<Order?> FindAsync(string id) => await _context.LoadAsync<Order>(id, "orders");
}
