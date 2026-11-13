using System;

namespace Fixtures.StaticAccuracy
{
    public class Worker
    {
        public void Go() { Console.WriteLine("worker"); }
    }

    public class Caller
    {
        // このクラス自身にも Go がある。名前の解決を間違えると誤エッジが出る。
        public void Go() { Console.WriteLine("own"); }

        public void DelegateInVariable(Worker other)
        {
            // ローカル変数 Go が this.Go を隠している。Go() は this.Go() ではない。
            Action Go = other.Go;
            Go();
        }

        public void DelegateField()
        {
            // デリゲート型フィールドの呼び出しも this のメソッド扱いにしてはいけない。
            _handler();
        }

        private Action _handler = () => { };

        public void RealCalls()
        {
            Go();                      // this.Go() が正しい
            var w = new Worker();      // var の型を復元できるか
            w.Go();
            Worker t = new Worker();   // 明示型
            t.Go();
        }
    }
}
