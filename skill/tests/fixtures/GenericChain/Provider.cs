using System.Collections.Generic;
using Fix.Chain.Models;

namespace Fix.Chain.Services;

public class Provider
{
    // 戻り値の型引数の中身が Models.Box<int> である、という事実だけを持つ
    public List<Box<int>> All() => new List<Box<int>>();
}
