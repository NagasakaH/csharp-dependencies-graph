using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace CsharpDependencyGraph;

public readonly record struct MemberInfo(string Name, string Kind, string Signature, string? ReturnType,
    int Line, bool IsStatic, bool IsAsync, string Visibility);

/// <summary>
/// メンバー宣言から (名前, 種別, 詳細) を導く共通規則。
/// 宣言収集（1 周目）と参照解決（2 周目）が必ず同じ名前を使うようにするための唯一の情報源。
/// </summary>
public static class MemberNaming
{
    public static IEnumerable<MemberInfo> Of(MemberDeclarationSyntax decl, string ownerSimple)
    {
        var line = decl.GetLocation().GetLineSpan().StartLinePosition.Line + 1;
        var visibility = DeclarationScanner.VisibilityOf(decl.Modifiers);
        var isStatic = DeclarationScanner.HasModifier(decl.Modifiers, "static");

        switch (decl)
        {
            case MethodDeclarationSyntax method:
                yield return new MemberInfo(method.Identifier.Text, "method",
                    $"{visibility} {method.ReturnType} {method.Identifier.Text}({Parameters(method.ParameterList)})",
                    TypeText.UnwrapTask(method.ReturnType.ToString()), line, isStatic,
                    DeclarationScanner.HasModifier(method.Modifiers, "async"), visibility);
                break;

            case ConstructorDeclarationSyntax ctor:
                yield return new MemberInfo(".ctor", "constructor",
                    $"{visibility} {ctor.Identifier.Text}({Parameters(ctor.ParameterList)})", null,
                    line, false, false, visibility);
                break;

            case DestructorDeclarationSyntax dtor:
                yield return new MemberInfo("~" + ownerSimple, "destructor", "~" + ownerSimple + "()", null,
                    line, false, false, "public");
                break;

            case PropertyDeclarationSyntax property:
                yield return new MemberInfo(property.Identifier.Text, "property",
                    $"{visibility} {property.Type} {property.Identifier.Text} {{ {(property.ExpressionBody is not null ? "get" : Accessors(property.AccessorList))} }}",
                    property.Type.ToString(), line, isStatic, false, visibility);
                break;

            case IndexerDeclarationSyntax indexer:
                yield return new MemberInfo("Item", "indexer",
                    $"{visibility} {indexer.Type} this[{Parameters(indexer.ParameterList)}]",
                    indexer.Type.ToString(), line, isStatic, false, visibility);
                break;

            case FieldDeclarationSyntax field:
                foreach (var variable in field.Declaration.Variables)
                {
                    yield return new MemberInfo(variable.Identifier.Text, "field",
                        $"{visibility} {field.Declaration.Type} {variable.Identifier.Text}",
                        field.Declaration.Type.ToString(), line, isStatic, false, visibility);
                }
                break;

            case EventFieldDeclarationSyntax evt:
                foreach (var variable in evt.Declaration.Variables)
                {
                    yield return new MemberInfo(variable.Identifier.Text, "event",
                        $"{visibility} {evt.Declaration.Type} {variable.Identifier.Text}",
                        evt.Declaration.Type.ToString(), line, isStatic, false, visibility);
                }
                break;

            case EventDeclarationSyntax evt2:
                yield return new MemberInfo(evt2.Identifier.Text, "event",
                    $"{visibility} {evt2.Type} {evt2.Identifier.Text}", evt2.Type.ToString(), line, isStatic, false, visibility);
                break;

            case EnumMemberDeclarationSyntax enumMember:
                yield return new MemberInfo(enumMember.Identifier.Text, "enum-member",
                    enumMember.Identifier.Text, ownerSimple, line, true, false, "public");
                break;

            case OperatorDeclarationSyntax op:
                yield return new MemberInfo("operator" + op.OperatorToken.Text, "operator",
                    $"{visibility} {op.ReturnType} operator {op.OperatorToken.Text}({Parameters(op.ParameterList)})",
                    op.ReturnType.ToString(), line, isStatic, false, visibility);
                break;

            case ConversionOperatorDeclarationSyntax conv:
                yield return new MemberInfo("operator" + conv.ImplicitOrExplicitKeyword.Text, "operator",
                    $"{visibility} {conv.Type} operator {conv.ImplicitOrExplicitKeyword.Text}",
                    conv.Type.ToString(), line, isStatic, false, visibility);
                break;
        }
    }

    static string Accessors(AccessorListSyntax? list)
    {
        if (list is null) return "...";
        var parts = new List<string>();
        foreach (var a in list.Accessors) parts.Add(a.Keyword.Text);
        return string.Join(" ", parts);
    }

    static string Parameters(BracketedParameterListSyntax list)
    {
        var parts = new List<string>();
        foreach (var p in list.Parameters) parts.Add((p.Type?.ToString() ?? "var") + " " + p.Identifier.Text);
        return string.Join(", ", parts);
    }

    public static string Parameters(ParameterListSyntax list)
    {
        var parts = new List<string>();
        foreach (var p in list.Parameters) parts.Add((p.Type?.ToString() ?? "var") + " " + p.Identifier.Text);
        return string.Join(", ", parts);
    }
}
