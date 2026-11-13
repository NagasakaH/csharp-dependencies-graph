using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace CsharpDependencyGraph;

/// <summary>
/// パース 2 周目: 名前インデックスを使い、呼び出し・生成・参照のエッジを抽出する。
/// 意味解析（SemanticModel）は使わず、構文と命名規則から解決するため
/// ビルド不能なリポジトリや部分克隆でも動作する。
/// </summary>
public sealed class ReferenceScanner
{
    readonly AnalyzerOptions _opt;
    readonly TypeIndex _index;
    readonly Dictionary<string, GraphEdge> _edges = new(StringComparer.Ordinal);
    readonly object _gate = new();
    int _unresolvedCount;
    int _resolvedRefTypeCount;

    public ReferenceScanner(AnalyzerOptions opt, TypeIndex index)
    {
        _opt = opt;
        _index = index;
    }

    public IReadOnlyDictionary<string, GraphEdge> Edges => _edges;
    public int UnresolvedCount => _unresolvedCount;
    public int ResolvedTypeRefCount => _resolvedRefTypeCount;

    public void ScanFile(string absolutePath, FileResult file)
    {
        SyntaxNode root;
        try
        {
            root = CSharpSyntaxTree
                .ParseText(File.ReadAllText(absolutePath), DeclarationScanner.ParseOptions, file.RelPath)
                .GetRoot();
        }
        catch (Exception)
        {
            return;
        }

        {
            foreach (var node in root.ChildNodes().OfType<MemberDeclarationSyntax>())
            {
                if (node is BaseNamespaceDeclarationSyntax nsDecl)
                {
                    foreach (var member in nsDecl.Members) WalkMember(member, nsDecl.Name.ToString(), file, null);
                    continue;
                }
                WalkMember(node, "", file, null);
            }
        }
    }

    void WalkMember(MemberDeclarationSyntax member, string ns, FileResult file, TypeSymbol? owner)
    {
        switch (member)
        {
            case TypeDeclarationSyntax typeDecl:
                WalkType(typeDecl, ns, file);
                break;
            default:
                if (owner is not null) WalkMemberBody(member, ns, file, owner);
                break;
        }
    }

    void WalkType(TypeDeclarationSyntax decl, string ns, FileResult file)
    {
        var qualified = DeclarationScanner.BuildQualified(ns, decl);
        if (!_index.ByQualified.TryGetValue(qualified, out var ts)) return;

        foreach (var list in decl.AttributeLists)
        {
            foreach (var attr in list.Attributes) EmitAttribute(ts.Id, attr, ns, file);
        }

        if (decl.BaseList is not null)
        {
            foreach (var baseType in decl.BaseList.Types)
            {
                var raw = baseType.Type.ToString();
                var candidates = _index.Resolve(raw, ts.Namespace, file);
                if (candidates.Count == 0)
                {
                    NoteUnresolvedType(file, raw);
                    continue;
                }
                foreach (var candidate in candidates)
                {
                    var kind = candidate.Kind == "interface" ? "implements" : "inherits";
                    Emit(ts.Id, candidate.Id, kind,
                        candidates.Count > 1 ? "ambiguous: " + raw : raw, ts.Line);
                }
            }
        }

        foreach (var member in decl.Members) WalkMember(member, ns, file, ts);
    }

    void WalkMemberBody(MemberDeclarationSyntax member, string ns, FileResult file, TypeSymbol ts)
    {
        List<MemberSymbol>? symbols = null;
        foreach (var info in MemberNaming.Of(member, ts.Simple))
        {
            if (!ts.MembersByName.TryGetValue(info.Name, out var found)) continue;
            symbols ??= new List<MemberSymbol>(2);
            if (!symbols.Contains(found)) symbols.Add(found);
        }
        if (symbols is null) return;
        foreach (var symbol in symbols) AnalyzeMemberBody(symbol, member, ts, ns, file);
    }

    void AnalyzeMemberBody(MemberSymbol symbol, MemberDeclarationSyntax member, TypeSymbol ts, string ns, FileResult file)
    {

        var scope = BuildScope(member, ts, ns, file);
        if (_opt.DeclarationTypeRefs) EmitDeclarationRefs(symbol, member, ts, ns, file);

        foreach (var node in member.DescendantNodes())
        {
            switch (node)
            {
                case InvocationExpressionSyntax inv:
                    HandleInvocation(symbol, ts, ns, file, inv, scope);
                    break;
                case ObjectCreationExpressionSyntax creation:
                    HandleObjectCreation(symbol, ts, ns, file, creation);
                    break;
                case MemberAccessExpressionSyntax access when !IsInvocationTarget(access):
                    if (_opt.AccessEdges) HandleMemberAccess(symbol, ts, ns, file, access, scope);
                    break;
                case AttributeSyntax attr:
                    EmitAttribute(symbol.Id, attr, ns, file);
                    break;
                case TypeOfExpressionSyntax typeOf:
                    EmitTypeRef(symbol.Id, typeOf.Type.ToString(), "references", ns, file, "typeof", LineOf(typeOf));
                    break;
                case BinaryExpressionSyntax asBinary when asBinary.IsKind(SyntaxKind.AsExpression):
                    EmitTypeRef(symbol.Id, asBinary.Right.ToString(), "references", ns, file, "as", LineOf(asBinary));
                    break;
                case DeclarationPatternSyntax declarationPattern:
                    EmitTypeRef(symbol.Id, declarationPattern.Type.ToString(), "references", ns, file, "is pattern", LineOf(declarationPattern));
                    break;
                case TypePatternSyntax typePattern:
                    EmitTypeRef(symbol.Id, typePattern.Type.ToString(), "references", ns, file, "is pattern", LineOf(typePattern));
                    break;
                case CatchClauseSyntax catchClause when catchClause.Declaration is not null:
                    EmitTypeRef(symbol.Id, catchClause.Declaration.Type.ToString(), "references", ns, file, "catch", LineOf(catchClause));
                    break;
            }
        }
    }

    // ---------------------------------------------------------------- 呼び出し

    void HandleInvocation(MemberSymbol symbol, TypeSymbol ts, string ns, FileResult file,
        InvocationExpressionSyntax inv, Scope scope)
    {
        string? name;
        ExpressionSyntax? receiver;
        switch (inv.Expression)
        {
            case MemberAccessExpressionSyntax access:
                name = (access.Name as SimpleNameSyntax)?.Identifier.Text;
                receiver = access.Expression;
                break;
            case SimpleNameSyntax simple:
                name = simple.Identifier.Text;
                receiver = null;
                break;
            default:
                return;
        }
        if (string.IsNullOrEmpty(name)) return;

        var line = LineOf(inv);
        var raw = Truncate(inv.Expression.ToString());

        if (receiver is null)
        {
            // 名前のない receiver の呼び出しは self / this を仮定する。
            // ただしその名前が局所変数・パラメータ・デリゲード型メンバーを指しているなら、
            // それはメソッド呼び出しではなく変数のデリゲート実行なので断定しない。
            if (scope.IsShadowed(name!, inv) || IsNonInvocableMember(ts, name!))
            {
                Unresolved(symbol, file, raw);
                return;
            }

            var own = _index.FindMember(ts, name!);
            if (own is not null)
            {
                Emit(symbol.Id, own.Id, "calls", ReferenceEquals(own, symbol) ? "self" : "this." + name, line);
            }
            else
            {
                Unresolved(symbol, file, raw);
            }
            return;
        }

        var exprType = ResolveExpr(receiver, ts, ns, file, scope, 0);
        var typeRaw = exprType.TypeRaw ?? exprType.StaticTypeName;
        if (typeRaw is null)
        {
            Unresolved(symbol, file, raw);
            return;
        }

        var candidates = _index.Resolve(typeRaw, ns, file);
        if (candidates.Count == 0)
        {
            NoteUnresolvedType(file, TypeText.Normalize(typeRaw));
            Unresolved(symbol, file, raw);
            return;
        }

        foreach (var candidate in candidates)
        {
            var target = _index.FindMember(candidate, name!);
            var detail = candidates.Count > 1 ? "ambiguous: " + Truncate(raw) : Truncate(raw);
            if (target is not null) Emit(symbol.Id, target.Id, "calls", detail, line);
            else Emit(symbol.Id, candidate.Id, "references", name + "() (member 未解決)", line);
        }
    }

    void HandleObjectCreation(MemberSymbol symbol, TypeSymbol ts, string ns, FileResult file,
        ObjectCreationExpressionSyntax creation)
    {
        var raw = Truncate(creation.Type.ToString());
        var candidates = _index.Resolve(creation.Type.ToString(), ns, file);
        if (candidates.Count == 0)
        {
            NoteUnresolvedType(file, TypeText.Normalize(creation.Type.ToString()));
            return;
        }
        foreach (var candidate in candidates)
        {
            Emit(symbol.Id, candidate.Id, "creates", candidates.Count > 1 ? "ambiguous: new " + raw : "new " + raw,
                LineOf(creation));
            var ctor = _index.FindMember(candidate, ".ctor");
            if (ctor is not null) Emit(symbol.Id, ctor.Id, "calls", "new " + candidate.Simple, LineOf(creation));
        }
    }

    void HandleMemberAccess(MemberSymbol symbol, TypeSymbol ts, string ns, FileResult file,
        MemberAccessExpressionSyntax access, Scope scope)
    {
        var name = (access.Name as SimpleNameSyntax)?.Identifier.Text;
        if (string.IsNullOrEmpty(name)) return;

        var exprType = ResolveExpr(access.Expression, ts, ns, file, scope, 0);
        var typeRaw = exprType.TypeRaw ?? exprType.StaticTypeName;
        if (typeRaw is null) return;

        var candidates = _index.Resolve(typeRaw, ns, file);
        foreach (var candidate in candidates)
        {
            var target = _index.FindMember(candidate, name!);
            if (target is null) continue;
            var kind = target.Kind switch
            {
                "field" or "property" or "event" or "indexer" => "accesses",
                _ => "references",
            };
            Emit(symbol.Id, target.Id, kind, Truncate(access.ToString()), LineOf(access));
        }
    }

    // ---------------------------------------------------------------- 型参照

    void EmitDeclarationRefs(MemberSymbol symbol, MemberDeclarationSyntax member, TypeSymbol ts, string ns, FileResult file)
    {
        foreach (var parameter in DeclaredParameters(member))
        {
            if (parameter.Type is null) continue;
            EmitTypeRef(symbol.Id, parameter.Type.ToString(), "references", ns, file, "param", symbol.Line);
        }
        if (symbol.ReturnType is not null && symbol.Kind is "method" or "property" or "field")
        {
            EmitTypeRef(symbol.Id, symbol.ReturnType, "references", ns, file,
                symbol.Kind == "method" ? "return" : symbol.Kind, symbol.Line);
        }
    }

    static readonly HashSet<string> PredefinedTypes = new(StringComparer.Ordinal)
    {
        "string", "object", "int", "long", "short", "byte", "sbyte", "uint", "ulong", "ushort",
        "bool", "char", "double", "float", "decimal", "void", "var", "dynamic", "nint", "nuint",
    };

    void EmitTypeRef(string sourceId, string raw, string kind, string ns, FileResult file, string detail, int line)
    {
        if (PredefinedTypes.Contains(TypeText.Normalize(raw))) return;
        var candidates = _index.Resolve(raw, ns, file);
        if (candidates.Count == 0)
        {
            NoteUnresolvedType(file, TypeText.Normalize(raw));
            return;
        }
        foreach (var candidate in candidates)
        {
            Emit(sourceId, candidate.Id, kind, candidates.Count > 1 ? detail + " (ambiguous)" : detail, line);
            _resolvedRefTypeCount++;
        }
    }

    void EmitAttribute(string sourceId, AttributeSyntax attr, string ns, FileResult file)
    {
        var raw = attr.Name.ToString();
        var candidates = _index.Resolve(raw, ns, file);
        if (candidates.Count == 0) candidates = _index.Resolve(raw + "Attribute", ns, file);
        foreach (var candidate in candidates)
        {
            Emit(sourceId, candidate.Id, "attribute", raw, LineOf(attr));
        }
    }

    // ---------------------------------------------------------------- 型推論

    readonly struct ExprType
    {
        public readonly string? TypeRaw;
        public readonly string? StaticTypeName;

        /// <summary>ジェネリック引数を畳む前の型表記。`List&lt;Worker&gt;` の要素型を取り出すときに使う。</summary>
        public readonly string? RawType;
        public ExprType(string? typeRaw, string? staticTypeName, string? rawType = null)
        {
            TypeRaw = typeRaw;
            StaticTypeName = staticTypeName;
            RawType = rawType;
        }
        public static readonly ExprType Unknown = new(null, null);
    }

    ExprType ResolveExpr(ExpressionSyntax expr, TypeSymbol ts, string ns, FileResult file,
        Scope scope, int depth)
    {
        if (depth > 10) return ExprType.Unknown;

        switch (expr)
        {
            case ParenthesizedExpressionSyntax paren:
                return ResolveExpr(paren.Expression, ts, ns, file, scope, depth + 1);
            case AwaitExpressionSyntax awaitExpr:
            {
                var inner = ResolveExpr(awaitExpr.Expression, ts, ns, file, scope, depth + 1);
                // Task<List<A>> を畳む前に剥がさないと内側のジェネリックが消える
                return FromType(TypeText.UnwrapTask(inner.RawType ?? inner.TypeRaw));
            }
            // `new Holder().Items` のように new の結果をそのまま使う式
            case ObjectCreationExpressionSyntax creation:
                return FromType(creation.Type.ToString());
            case CastExpressionSyntax cast:
                return FromType(cast.Type.ToString());
            case BinaryExpressionSyntax asBinary when asBinary.IsKind(SyntaxKind.AsExpression):
                return ResolveExpr(asBinary.Right, ts, ns, file, scope, depth + 1);
            case BinaryExpressionSyntax binary
                when binary.IsKind(SyntaxKind.CoalesceExpression) || binary.IsKind(SyntaxKind.EqualsExpression):
                return ResolveExpr(binary.Left, ts, ns, file, scope, depth + 1);
            case ConditionalExpressionSyntax conditional:
                return ResolveExpr(conditional.WhenTrue, ts, ns, file, scope, depth + 1);
            case AssignmentExpressionSyntax assignment:
                return ResolveExpr(assignment.Right, ts, ns, file, scope, depth + 1);
            case InterpolatedStringExpressionSyntax:
                return FromType("string");
            case LiteralExpressionSyntax literal:
                return FromType(LiteralType(literal));
            case DefaultExpressionSyntax defaultExpr:
                return FromType(defaultExpr.Type.ToString());
            case ThisExpressionSyntax:
                return FromType(ts.Qualified);
            case BaseExpressionSyntax:
                return FromType(ClassBaseOf(ts));
            case PredefinedTypeSyntax predefined:
                return new ExprType(null, predefined.Keyword.Text);
            case IdentifierNameSyntax identifier:
                return ResolveIdentifier(identifier.Identifier.Text, identifier, ts, scope);
            case GenericNameSyntax generic:
            {
                var resolved = ResolveIdentifier(generic.Identifier.Text, generic, ts, scope);
                if (resolved.TypeRaw is not null || resolved.StaticTypeName is not null) return resolved;
                return new ExprType(null, generic.Identifier.Text);
            }
            case MemberAccessExpressionSyntax access:
                return ResolveMemberAccess(access, ts, ns, file, scope, depth);
            case InvocationExpressionSyntax inv:
                return ResolveInvocationType(inv, ts, ns, file, scope, depth);
            case ElementAccessExpressionSyntax element:
            {
                var inner = ResolveExpr(element.Expression, ts, ns, file, scope, depth + 1);
                var raw = inner.TypeRaw ?? inner.StaticTypeName;
                if (raw is null) return ExprType.Unknown;
                var args = TypeText.GenericArgs(raw);
                return args.Count > 0 ? FromType(args[^1]) : ExprType.Unknown;
            }
            case ConditionalAccessExpressionSyntax conditionalAccess:
                return ResolveExpr(conditionalAccess.WhenNotNull, ts, ns, file, scope, depth + 1);
            case PostfixUnaryExpressionSyntax postfix:
                return ResolveExpr(postfix.Operand, ts, ns, file, scope, depth + 1);
            case PrefixUnaryExpressionSyntax prefix when prefix.IsKind(SyntaxKind.LogicalNotExpression):
                return FromType("bool");
            case PrefixUnaryExpressionSyntax prefix:
                return ResolveExpr(prefix.Operand, ts, ns, file, scope, depth + 1);
            case WithExpressionSyntax withExpr:
                return ResolveExpr(withExpr.Expression, ts, ns, file, scope, depth + 1);
            case ImplicitObjectCreationExpressionSyntax:
                return ExprType.Unknown;
            default:
                return ExprType.Unknown;
        }
    }

    ExprType ResolveIdentifier(string id, SyntaxNode node, TypeSymbol ts, Scope scope)
    {
        if (id == "this") return FromType(ts.Qualified);
        if (id == "base") return FromType(ClassBaseOf(ts));
        var scopeType = scope.TypeOf(id, node);
        if (scopeType is not null) return FromType(scopeType);
        // 型は決まらないが名前はローカル（var x = 何か / 型を省略したラムダ引数など）。
        // ここで this.X に落とすと誤った static エッジになるので未解決で止める。
        if (scope.IsShadowed(id, node)) return ExprType.Unknown;
        var member = _index.FindMember(ts, id);
        if (member is not null && member.Kind is "field" or "property" or "event")
        {
            return member.ReturnType is null ? ExprType.Unknown : FromType(member.ReturnType);
        }
        return new ExprType(null, id);
    }

    ExprType ResolveMemberAccess(MemberAccessExpressionSyntax access, TypeSymbol ts, string ns, FileResult file,
        Scope scope, int depth)
    {
        var inner = ResolveExpr(access.Expression, ts, ns, file, scope, depth + 1);
        var name = (access.Name as SimpleNameSyntax)?.Identifier.Text;
        if (string.IsNullOrEmpty(name)) return ExprType.Unknown;

        if (inner.StaticTypeName is not null)
        {
            foreach (var candidate in _index.Resolve(inner.StaticTypeName, ns, file))
            {
                if (_index.TryGetNested(candidate, name!, out var nested)) return FromType(nested.Qualified);
                var member = _index.FindMember(candidate, name!);
                if (member is not null)
                {
                    if (member.Kind is "field" or "property" or "event")
                    {
                        return member.ReturnType is null ? ExprType.Unknown : FromType(member.ReturnType);
                    }
                    if (member.Kind is "method")
                    {
                        return member.ReturnType is null ? ExprType.Unknown : FromType(TypeText.UnwrapTask(member.ReturnType));
                    }
                }
            }
            // 途中が解決できなくてもルート型名は保持（静的メンバーの多段アクセス）
            return new ExprType(null, inner.StaticTypeName);
        }

        if (inner.TypeRaw is null) return ExprType.Unknown;
        foreach (var candidate in _index.Resolve(inner.TypeRaw, ns, file))
        {
            if (_index.TryGetNested(candidate, name!, out var nested)) return FromType(nested.Qualified);
            var member = _index.FindMember(candidate, name!);
            if (member is null) continue;
            if (member.Kind is "field" or "property" or "event")
            {
                return member.ReturnType is null ? ExprType.Unknown : FromType(member.ReturnType);
            }
            if (member.Kind is "method" && member.ReturnType is not null)
            {
                return FromType(TypeText.UnwrapTask(member.ReturnType));
            }
        }
        return ExprType.Unknown;
    }

    ExprType ResolveInvocationType(InvocationExpressionSyntax inv, TypeSymbol ts, string ns, FileResult file,
        Scope scope, int depth)
    {
        string? name;
        ExpressionSyntax? receiver;
        switch (inv.Expression)
        {
            case MemberAccessExpressionSyntax access:
                name = (access.Name as SimpleNameSyntax)?.Identifier.Text;
                receiver = access.Expression;
                break;
            case SimpleNameSyntax simple:
                name = simple.Identifier.Text;
                receiver = null;
                break;
            default:
                return ExprType.Unknown;
        }
        if (string.IsNullOrEmpty(name)) return ExprType.Unknown;

        if (receiver is null)
        {
            // receiver なしでも、名前が局所変数やデリゲード型メンバーなら this のメソッドではない。
            if (scope.IsShadowed(name!, inv) || IsNonInvocableMember(ts, name!)) return ExprType.Unknown;

            var own = _index.FindMember(ts, name!);
            if (own?.ReturnType is not null) return FromType(TypeText.UnwrapTask(own.ReturnType));
            return ExprType.Unknown;
        }

        var exprType = ResolveExpr(receiver, ts, ns, file, scope, depth + 1);
        var typeRaw = exprType.TypeRaw ?? exprType.StaticTypeName;
        if (typeRaw is null) return ExprType.Unknown;

        foreach (var candidate in _index.Resolve(typeRaw, ns, file))
        {
            var member = _index.FindMember(candidate, name!);
            if (member?.ReturnType is not null) return FromType(TypeText.UnwrapTask(member.ReturnType));
        }
        return ExprType.Unknown;
    }

    string ClassBaseOf(TypeSymbol ts)
    {
        foreach (var baseRaw in ts.BaseRaw)
        {
            foreach (var candidate in _index.Resolve(baseRaw, ts.Namespace, ts.DeclaringFile))
            {
                if (candidate.Kind != "interface") return candidate.Qualified;
            }
        }
        return "";
    }

    static ExprType FromType(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return ExprType.Unknown;
        var normalized = TypeText.Normalize(raw!);
        return normalized.Length == 0 ? ExprType.Unknown : new ExprType(normalized, null, raw);
    }

    static string LiteralType(LiteralExpressionSyntax literal) => literal.Kind() switch
    {
        SyntaxKind.StringLiteralExpression => "string",
        SyntaxKind.TrueLiteralExpression or SyntaxKind.FalseLiteralExpression => "bool",
        SyntaxKind.CharacterLiteralExpression => "char",
        SyntaxKind.NumericLiteralExpression when literal.Token.ValueText.Contains('.') => "double",
        SyntaxKind.NumericLiteralExpression => "int",
        _ => "",
    };

    // ---------------------------------------------------------------- スコープ

    /// <summary>その名前のメンバーが呼び出し可能でない（フィールド／プロパティ／イベント）か。</summary>
    bool IsNonInvocableMember(TypeSymbol ts, string name)
    {
        var member = _index.FindMember(ts, name);
        return member is not null && member.Kind is "field" or "property" or "event" or "constant";
    }

    /// <summary>
    /// メンバ内の宣言を「出現位置つき」で集める。解決は常に「その識別子の直前に見えた宣言」で
    /// 行う。メソッド全体で 1 つの辞書に畳むと、兄弟ブロックの同名 var が混同される。
    /// </summary>
    Scope BuildScope(MemberDeclarationSyntax member, TypeSymbol ts, string ns, FileResult file)
    {
        var scope = new Scope();
        var deferred = new List<(string Name, ExpressionSyntax Value, int Pos)>();
        var deferredElements = new List<(string Name, ExpressionSyntax Expr, int Pos)>();

        foreach (var parameter in DeclaredParameters(member))
        {
            if (parameter.Type is not null)
            {
                scope.Declare(parameter.Identifier.Text, parameter.Type.ToString(), parameter.Identifier.SpanStart,
                    DeclarationSpace(parameter, member));
            }
        }

        foreach (var node in member.DescendantNodes())
        {
            switch (node)
            {
                case ParameterSyntax parameter:
                    // 型を省略したラムダ引数も「その名前はローカル」として塞ぐ。
                    // 型は決まらないので、this.X との混同だけを止める。
                    scope.Declare(parameter.Identifier.Text, parameter.Type?.ToString() ?? "", parameter.Identifier.SpanStart,
                        DeclarationSpace(parameter, member));
                    break;

                case LocalFunctionStatementSyntax local:
                    // ローカル関数は宣言より前でも呼べる。メンバ全体で同名の型メンバを遮蔽し、
                    // 型は決めない（決まらないまま this.X に落とすのが最も危険な誤り）。
                    scope.DeclareAnywhere(local.Identifier.Text, "");
                    break;

                case CatchDeclarationSyntax catchDecl:
                    scope.Declare(catchDecl.Identifier.Text, catchDecl.Type.ToString(), catchDecl.Identifier.SpanStart,
                        DeclarationSpace(catchDecl, member));
                    break;

                case DeclarationPatternSyntax pattern when pattern.Designation is SingleVariableDesignationSyntax patternName:
                    scope.Declare(patternName.Identifier.Text, pattern.Type.ToString(), patternName.Identifier.SpanStart,
                        DeclarationSpace(pattern, member));
                    break;

                case DeclarationExpressionSyntax declaration when declaration.Designation is SingleVariableDesignationSyntax outName:
                    scope.Declare(outName.Identifier.Text, declaration.Type.ToString(), outName.Identifier.SpanStart,
                        DeclarationSpace(declaration, member));
                    break;

                // LINQ の範囲変数（from x in … / let y = …）。型は決めないが名前は塞ぐ
                case FromClauseSyntax range:
                    scope.Declare(range.Identifier.Text, "", range.Identifier.SpanStart, DeclarationSpace(range, member));
                    break;

                case LetClauseSyntax ranged:
                    scope.Declare(ranged.Identifier.Text, "", ranged.Identifier.SpanStart, DeclarationSpace(ranged, member));
                    break;

                case ForEachStatementSyntax forEach:
                {
                    if (IsVar(forEach.Type))
                    {
                        var element = ElementOf(forEach.Expression, ts, ns, file, scope);
                        if (element is not null) scope.Declare(forEach.Identifier.Text, element, forEach.Identifier.SpanStart, forEach);
                        else
                        {
                            // コレクション側が `var items = Build()` の遅延推論待ちのことがある。
                            // 名前だけ塞いでおき、2 ラウンド目で要素型を埋める
                            scope.Declare(forEach.Identifier.Text, "", forEach.Identifier.SpanStart, forEach);
                            deferredElements.Add((forEach.Identifier.Text, forEach.Expression, forEach.Identifier.SpanStart));
                        }
                    }
                    else
                    {
                        scope.Declare(forEach.Identifier.Text, forEach.Type.ToString(), forEach.Identifier.SpanStart, forEach);
                    }

                    break;
                }

                case VariableDeclaratorSyntax variable:
                {
                    if (variable.Parent is not VariableDeclarationSyntax declaration) break;
                    if (declaration.Parent is FieldDeclarationSyntax or EventFieldDeclarationSyntax) break;

                    // `var (a, b) = ...` の要素名はこの Roslyn API では declarator にならない
                    // （Identifier が空）。名前はここで打ち切り、要素名は塞がない。
                    var name = variable.Identifier.Text;
                    if (name.Length == 0) break;
                    var pos = variable.Identifier.SpanStart;
                    var space = DeclarationSpace(variable, member);

                    if (!IsVar(declaration.Type))
                    {
                        scope.Declare(name, declaration.Type.ToString(), pos, space);
                    }
                    else if (variable.Initializer?.Value is ObjectCreationExpressionSyntax creation)
                    {
                        scope.Declare(name, creation.Type.ToString(), pos, space);
                    }
                    else
                    {
                        scope.Declare(name, "", pos, space);
                        if (variable.Initializer is not null) deferred.Add((name, variable.Initializer.Value, pos));
                    }

                    break;
                }
            }
        }

        // 2 ラウンド目: `var x = Foo.Bar()` の型を、宣言位置までに見える宣言で推論する
        foreach (var (name, value, pos) in deferred)
        {
            var resolved = ResolveExpr(value, ts, ns, file, scope, 0);
            var raw = resolved.RawType ?? resolved.TypeRaw ?? resolved.StaticTypeName;
            if (raw is not null) scope.Declare(name, raw, pos, DeclarationSpace(value, member));
        }

        // 3 ラウンド目: 2 ラウンド目で型が決まったコレクションの foreach 要素型
        foreach (var (name, expr, pos) in deferredElements)
        {
            var element = ElementOf(expr, ts, ns, file, scope);
            if (element is not null) scope.Declare(name, element, pos, null);
        }

        return scope;
    }

    /// <summary>`foreach (var x in expr)` の要素型。ジェネリック引数を畳む前の表記から取る。</summary>
    string? ElementOf(ExpressionSyntax expr, TypeSymbol ts, string ns, FileResult file, Scope scope)
    {
        var collection = ResolveExpr(expr, ts, ns, file, scope, 0);
        var raw = collection.RawType ?? collection.TypeRaw ?? collection.StaticTypeName;
        var args = raw is null ? new List<string>() : TypeText.GenericArgs(raw);
        return args.Count > 0 ? args[0] : null;
    }

    /// <summary>
    /// メンバ内のローカル名の集まり。各宣言は「有効になる位置」と「宣言領域（ブロック）」を持つ。
    /// 見え方は両方で見極める —— 位置だけだと内側ブロックの宣言が外側の後続に漏れ、
    /// 後続で触る同名のフィールドを誤って隠してしまう。
    /// </summary>
    sealed class Scope
    {
        /// <summary>メンバ内のどこからでも見える宣言を示す、先頭の位置。</summary>
        public const int Anywhere = -1;

        readonly Dictionary<string, List<(int Pos, string Type, SyntaxNode? Space)>> _map = new(StringComparer.Ordinal);

        /// <summary>メンバ全体で有効な宣言。C# のローカル関数は宣言より前でも呼べる。</summary>
        public void DeclareAnywhere(string name, string type) => Declare(name, type, Anywhere, null);

        public void Declare(string name, string type, int pos, SyntaxNode? space)
        {
            if (!_map.TryGetValue(name, out var entries)) _map[name] = entries = new List<(int, string, SyntaxNode?)>();

            // 列は必ず Pos の昇順に保つ。順が崩れると「識別子の直前に見えた宣言」を間違える
            var at = entries.Count;
            for (var i = 0; i < entries.Count; i++)
            {
                if (entries[i].Pos > pos)
                {
                    at = i;
                    break;
                }

                if (entries[i].Pos == pos)
                {
                    // 同じ宣言位置の書き換え（型決めラウンド）。型なし → 具体的な型へだけ更新
                    if (entries[i].Type.Length == 0 && type.Length > 0) entries[i] = (pos, type, entries[i].Space);
                    return;
                }
            }

            entries.Insert(at, (pos, type, space));
        }

        /// <summary>node の位置で name がローカル名として見えているか（型が不明でも塞ぐ）。</summary>
        public bool IsShadowed(string name, SyntaxNode node)
        {
            if (!_map.TryGetValue(name, out var entries)) return false;
            for (var i = entries.Count - 1; i >= 0; i--) if (Visible(entries[i], node)) return true;
            return false;
        }

        /// <summary>node の位置で見える型。型が決まらないローカルなら null を返す。</summary>
        public string? TypeOf(string name, SyntaxNode node)
        {
            if (!_map.TryGetValue(name, out var entries)) return null;
            for (var i = entries.Count - 1; i >= 0; i--)
            {
                if (!Visible(entries[i], node)) continue;
                return entries[i].Type.Length == 0 ? null : entries[i].Type;
            }

            return null;
        }

        static bool Visible((int Pos, string Type, SyntaxNode? Space) entry, SyntaxNode node)
            => entry.Pos <= node.SpanStart && (entry.Space is null || entry.Space.Contains(node));
    }

    /// <summary>
    /// 宣言の有効領域。C# の宣言領域に合わせた節まで上る（メソッド本体のブロック、
    /// `for` / `if` / `foreach` のような節、クエリ式、アクセサなど）。
    /// </summary>
    static SyntaxNode DeclarationSpace(SyntaxNode node, MemberDeclarationSyntax member)
    {
        for (var current = node; current is not null && current != member; current = current.Parent)
        {
            if (current is BlockSyntax or ForStatementSyntax or IfStatementSyntax or UsingStatementSyntax
                or ForEachStatementSyntax or WhileStatementSyntax or DoStatementSyntax or LockStatementSyntax
                or SwitchStatementSyntax or SwitchExpressionSyntax or LocalFunctionStatementSyntax
                or QueryExpressionSyntax or AccessorDeclarationSyntax or ConstructorInitializerSyntax)
            {
                return current;
            }
        }

        return member;
    }

    static IEnumerable<ParameterSyntax> DeclaredParameters(MemberDeclarationSyntax member)
    {
        switch (member)
        {
            case MethodDeclarationSyntax m: return m.ParameterList.Parameters;
            case ConstructorDeclarationSyntax c: return c.ParameterList.Parameters;
            case IndexerDeclarationSyntax i: return i.ParameterList.Parameters;
            case OperatorDeclarationSyntax o: return o.ParameterList.Parameters;
            case ConversionOperatorDeclarationSyntax c: return c.ParameterList.Parameters;
            default: return Array.Empty<ParameterSyntax>();
        }
    }

    /// <summary>
    /// 暗黙的型指定（var）か。構文木では PredefinedTypeSyntax として現れない形があるため、
    /// IdentifierName の "var" もここに通す。ここを取り逃すと var 変数の型が復元できず、
    /// `var x = new Foo(); x.Bar();` の calls エッジが黙って落ちる。
    /// </summary>
    static bool IsVar(TypeSyntax type) => type switch
    {
        PredefinedTypeSyntax predefined => predefined.Keyword.IsKind(SyntaxKind.VarKeyword),
        IdentifierNameSyntax identifier => identifier.Identifier.Text == "var",
        _ => false,
    };

    // ---------------------------------------------------------------- 出力

    void Emit(string source, string target, string kind, string? detail, int line)
    {
        if (source == target) return;
        var id = GraphEdge.MakeId(source, target, kind);
        lock (_gate)
        {
        if (_edges.TryGetValue(id, out var existing))
        {
            existing.Count = (existing.Count ?? 1) + 1;
            return;
        }
        _edges[id] = new GraphEdge
        {
            Id = id,
            Source = source,
            Target = target,
            Kind = kind,
            Detail = detail,
            Provenance = "static",
            Count = 1,
            Line = line == 0 ? null : line,
        };
        }
    }

    void Unresolved(MemberSymbol symbol, FileResult file, string raw)
    {
        lock (_gate)
        {
            _unresolvedCount++;
            symbol.UnresolvedTotal++;
        }
        if (symbol.Unresolved.Count >= _opt.MaxUnresolvedPerMember) return;
        if (!symbol.Unresolved.Contains(raw)) symbol.Unresolved.Add(raw);
    }

    void NoteUnresolvedType(FileResult file, string raw)
    {
        if (string.IsNullOrEmpty(raw)) return;
        file.UnresolvedTypes.TryGetValue(raw, out var count);
        file.UnresolvedTypes[raw] = count + 1;
    }

    static bool IsInvocationTarget(MemberAccessExpressionSyntax access) =>
        access.Parent is InvocationExpressionSyntax inv && ReferenceEquals(inv.Expression, access);

    static int LineOf(SyntaxNode node) => node.GetLocation().GetLineSpan().StartLinePosition.Line + 1;

    static string Truncate(string text)
    {
        text = text.Replace('\r', ' ').Replace('\n', ' ');
        while (text.Contains("  ")) text = text.Replace("  ", " ");
        return text.Length <= 120 ? text : text[..120] + "…";
    }
}
