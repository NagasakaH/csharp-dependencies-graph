using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace CsharpDependencyGraph;

/// <summary>
/// パース 1 周目: 型とメンバーの宣言だけを収集し、名前インデックスの材料を作る。
/// 参照関係の解決は ReferenceScanner（2 周目）が行う。
/// </summary>
public static class DeclarationScanner
{
    public static readonly CSharpParseOptions ParseOptions = new(LanguageVersion.Preview);

    public static FileResult ScanFile(string absolutePath, string relPath)
    {
        var result = new FileResult { RelPath = relPath };
        SyntaxNode root;
        try
        {
            var text = File.ReadAllText(absolutePath);
            root = CSharpSyntaxTree.ParseText(text, ParseOptions, relPath).GetRoot();
        }
        catch (Exception)
        {
            result.ParseFailed = true;
            return result;
        }

        CollectUsings(root, result);

        foreach (var node in root.ChildNodes().OfType<MemberDeclarationSyntax>())
        {
            if (node is BaseNamespaceDeclarationSyntax nsDecl)
            {
                foreach (var member in nsDecl.Members) Dispatch(member, nsDecl.Name.ToString(), result);
                continue;
            }
            Dispatch(node, "", result);
        }

        return result;
    }

    public static void CollectUsings(SyntaxNode root, FileResult result)
    {
        foreach (var usingDirective in root.DescendantNodes().OfType<UsingDirectiveSyntax>())
        {
            if (usingDirective.Alias is not null)
            {
                var alias = usingDirective.Alias.Name.ToString();
                var target = usingDirective.Name?.ToString() ?? "";
                if (alias.Length > 0 && target.Length > 0)
                {
                    if (!result.Aliases.ContainsKey(alias)) result.Aliases[alias] = target;
                }
            }
            else
            {
                var ns = usingDirective.Name?.ToString() ?? "";
                if (ns.Length == 0) continue;
                if (!result.Usings.Contains(ns)) result.Usings.Add(ns);
                // `global using X;` は宣言したファイルだけでなくプロジェクト全体に見える
                if (usingDirective.GlobalKeyword.IsKind(SyntaxKind.GlobalKeyword)
                    && !result.GlobalUsings.Contains(ns))
                {
                    result.GlobalUsings.Add(ns);
                }
            }
        }
    }

    /// <summary>宣言中の型パラメータの数。デリゲートにも適用する。</summary>
    static int ArityOf(MemberDeclarationSyntax decl) => decl switch
    {
        TypeDeclarationSyntax t => t.TypeParameterList?.Parameters.Count ?? 0,
        DelegateDeclarationSyntax d => d.TypeParameterList?.Parameters.Count ?? 0,
        _ => 0,
    };

    public static void Dispatch(MemberDeclarationSyntax member, string ns, FileResult file)
    {
        switch (member)
        {
            case TypeDeclarationSyntax typeDecl:
                ScanType(typeDecl, ns, file);
                break;
            case EnumDeclarationSyntax enumDecl:
                GetOrAddType(BuildQualified(ns, enumDecl), enumDecl, ns, file);
                break;
            case DelegateDeclarationSyntax del:
                GetOrAddType(BuildQualified(ns, del), del, ns, file);
                break;
        }
    }

    public static void ScanType(BaseTypeDeclarationSyntax baseDecl, string ns, FileResult file)
    {
        if (baseDecl is not TypeDeclarationSyntax decl)
        {
            GetOrAddType(BuildQualified(ns, baseDecl), baseDecl, ns, file);
            return;
        }
        ScanTypeInner(decl, ns, file);
    }

    static void ScanTypeInner(TypeDeclarationSyntax decl, string ns, FileResult file)
    {
        var symbol = GetOrAddType(BuildQualified(ns, decl), decl, ns, file);

        foreach (var member in ((TypeDeclarationSyntax)decl).Members)
        {
            switch (member)
            {
                case TypeDeclarationSyntax nested:
                    ScanType(nested, ns, file);
                    continue;
                case EnumDeclarationSyntax nestedEnum:
                    GetOrAddType(BuildQualified(ns, nestedEnum), nestedEnum, ns, file);
                    continue;
                case DelegateDeclarationSyntax nestedDelegate:
                    GetOrAddType(BuildQualified(ns, nestedDelegate), nestedDelegate, ns, file);
                    continue;
            }

            foreach (var info in MemberNaming.Of(member, symbol.Simple))
            {
                AddMember(symbol, info, file);
            }
        }
    }

    public static TypeSymbol GetOrAddType(string qualified, MemberDeclarationSyntax decl, string ns, FileResult file)
    {
        foreach (var existing in file.Types)
        {
            if (string.Equals(existing.Qualified, qualified, StringComparison.Ordinal))
            {
                existing.DeclarationCount++;
                return existing;
            }
        }

        var symbol = new TypeSymbol
        {
            Qualified = qualified,
            Simple = declName(decl),
            Namespace = ns,
            RelPath = file.RelPath,
            Kind = KindOf(decl),
            Line = decl.GetLocation().GetLineSpan().StartLinePosition.Line + 1,
            IsGeneric = (decl as TypeDeclarationSyntax)?.TypeParameterList?.Parameters.Count > 0,
            Arity = ArityOf(decl),
            DeclarationCount = 1,
        };
        var modifiers = decl switch
        {
            BaseTypeDeclarationSyntax b => b.Modifiers,
            DelegateDeclarationSyntax d => d.Modifiers,
            _ => default,
        };
        symbol.IsStatic = HasModifier(modifiers, "static");
        symbol.IsAbstract = HasModifier(modifiers, "abstract");
        symbol.IsSealed = HasModifier(modifiers, "sealed");
        foreach (var m in modifiers) symbol.Modifiers.Add(m.Text);
        if (decl is BaseTypeDeclarationSyntax withBase && withBase.BaseList is not null)
        {
            foreach (var baseType in withBase.BaseList.Types)
            {
                var raw = baseType.Type.ToString();
                if (raw.Length > 0) symbol.BaseRaw.Add(raw);
            }
        }
        file.Types.Add(symbol);
        return symbol;
    }

    static void AddMember(TypeSymbol owner, MemberInfo info, FileResult file)
    {
        if (info.Name.Length == 0) return;
        if (owner.MembersByName.TryGetValue(info.Name, out var existing))
        {
            // partial クラスの再宣言やオーバーロードは 1 ノードに束ねる
            if (existing.Line == info.Line) return;
            existing.OverloadCount++;
            if (existing.ExtraSignatures.Count < 8) existing.ExtraSignatures.Add(info.Signature);
            return;
        }

        var member = new MemberSymbol
        {
            Owner = owner,
            Name = info.Name,
            Kind = info.Kind,
            Signature = info.Signature,
            ReturnType = info.ReturnType,
            Line = info.Line,
            IsStatic = info.IsStatic,
            IsAsync = info.IsAsync,
            Visibility = info.Visibility,
            OverloadCount = 1,
        };
        owner.MembersByName[info.Name] = member;
        file.Members.Add(member);
    }

    public static string BuildQualified(string ns, SyntaxNode decl)
    {
        var parts = new List<string>();
        SyntaxNode? current = decl;
        while (current is BaseTypeDeclarationSyntax or DelegateDeclarationSyntax)
        {
            parts.Insert(0, declName(current));
            current = current.Parent;
        }
        var nesting = string.Join("/", parts);
        return ns.Length > 0 ? ns + "." + nesting : nesting;
    }

    static string declName(SyntaxNode node) => node switch
    {
        BaseTypeDeclarationSyntax t => t.Identifier.Text,
        DelegateDeclarationSyntax d => d.Identifier.Text,
        _ => "",
    };

    public static string KindOf(SyntaxNode decl) => decl switch
    {
        InterfaceDeclarationSyntax => "interface",
        StructDeclarationSyntax => "struct",
        EnumDeclarationSyntax => "enum",
        DelegateDeclarationSyntax => "delegate",
        RecordDeclarationSyntax r when r.ClassOrStructKeyword.IsKind(SyntaxKind.StructKeyword) => "record struct",
        RecordDeclarationSyntax => "record",
        _ => "class",
    };

    public static bool HasModifier(SyntaxTokenList modifiers, string text)
    {
        foreach (var m in modifiers) if (m.Text == text) return true;
        return false;
    }

    public static string VisibilityOf(SyntaxTokenList modifiers)
    {
        foreach (var m in modifiers)
        {
            switch (m.Text)
            {
                case "public": return "public";
                case "internal": return "internal";
                case "protected": return "protected";
                case "private": return "private";
                case "file": return "file";
            }
        }
        return "implicit";
    }
}
