// 変更したファイルに「含まれるメンバー」から自動で起点を作り、
// Lambda → API Gateway までが本命として出ることを見る fixture。
namespace ReportImpact;

public class Order
{
    public string Id { get; set; } = string.Empty;

    public static Order Create(string body) => new Order { Id = body };
}

public interface IOrderRepository
{
    void Save(Order order);
}

public class Handler
{
    private readonly IOrderRepository _repository;

    public Handler(IOrderRepository repository) => _repository = repository;

    public string Handle(string body)
    {
        var order = Order.Create(body);
        _repository.Save(order);
        return order.Id;
    }
}
