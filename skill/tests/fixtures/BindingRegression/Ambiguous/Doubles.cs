namespace Fix.Regress.Ambiguous;

// 名前空間直下の `Probe` と、別ファイルの別クラスにネストされた同名の `Probe`。
// C# は単純名を名前空間直下の型として解決するので、アナライザも単独決定できる
// （以前は同名候補を張り分けていた）。本当に決まらない同名（C# でも曖昧）は `ambiguous` 印で残る
public class Probe
{
}

public class OtherHost
{
    public class Probe
    {
    }
}
