namespace Fix.Regress.Core;

// 同じ名前空間に `Activity` と `Activity<T>` が同居する形（elsa-core の実在パターン）。
// ノード ID は型パラメータ数を含まないので、両者は同じ ID に畳まれる
public abstract class Activity { }

public abstract class Activity<T> : Activity { }

public interface IModule { void Configure(); }
