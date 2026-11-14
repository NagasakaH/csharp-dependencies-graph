using System.Collections.Generic;

// 行コメントの終端は LF だけじゃない。C# が改行と扱う CR 単独・NEL（U+0085）の後もコメント扱いを
// 続けると、`// comment` の後続（`, Item>` の部分）を丸ごと消して値型を取り出せない。
namespace Fix.EolComment
{
    public class Item { public int Id { get; set; } }

    public class Consumer
    {
        public int DictLF(Dictionary<int // comment
            , Item> p) => p[0].Id;

        public int DictCR(Dictionary<int // comment            , Item> p) => p[0].Id;

        public int DictNEL(Dictionary<int // comment            , Item> p) => p[0].Id;
    }
}
