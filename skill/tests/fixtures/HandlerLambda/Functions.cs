namespace HandlerNs;

public class A
{
    public void Handle() { }

    public class Inner
    {
        public void Handle() { }
    }
}

public class B
{
    public void Handle() { }
}

// handler の `Outer+Middle+Inner`（2 段以上の入れ子）が解決できること
public class Outer
{
    public class Middle
    {
        public class Inner
        {
            public void Handle() { }
        }
    }
}
