"""下流のインタフェース宣言と、その前提の検査（実装計画 §7, §10）。

`codegen` と `ja` は宣言のみで実装しない。ここで見るのは「宣言が壊れていないか」と、
**将来の実装が守るべき制約が型として表現されているか**である。

特に `Binding` は、改訂版 L269 の検証等価性を守るための制約を型で表している。
スロットごとに別の値を持てる形にすると、展開層が検証不能なコードを作れてしまう
（実装計画 §2.4）。
"""

import inspect
from pathlib import Path

import pytest

from boku.codegen import CodeGenerator
from boku.ja import InstructionRenderer
from boku.semantics.semantic_ast import Binding, SemanticAST

ROOT = Path(__file__).resolve().parents[1]


def test_protocols_declare_the_planned_signatures() -> None:
    """実装計画 §5 が定めるシグネチャどおり。

        codegen : emit(ast, binding, style) -> str
        ja      : render(ast, binding, rng) -> str
    """
    emit = inspect.signature(CodeGenerator.emit)
    assert list(emit.parameters) == ["self", "ast", "binding", "style"]

    render = inspect.signature(InstructionRenderer.render)
    assert list(render.parameters) == ["self", "ast", "binding", "rng"]


def test_protocols_are_not_implemented() -> None:
    """実装が無い（今回のスコープ外、実装計画 §1）。

    中身を書き始めたらこのテストが落ちる。そのときはスコープを見直すこと。
    """
    for module_name in ("boku.codegen", "boku.ja"):
        module = __import__(module_name, fromlist=["_"])
        source = inspect.getsource(module)
        assert "..." in source, f"{module_name} に実装が入っている"


def test_binding_is_a_single_value_or_none() -> None:
    """`Binding` が「全スロット共通の1値」または `None` しか表せない。

    **これが §2.4 の制約の本体である。**辞書やリストを許すと、スロットごとに別の値を
    入れる形が表現できてしまう。
    """
    assert Binding == int | None


def test_valid_bindings_are_accepted() -> None:
    """パラメータ版と、共通部分の各値が通る。"""
    ast = SemanticAST(("ge", "multiple_of", "mul_k"))
    assert ast.uniform_literal_domain == (4, 5, 6, 7, 8, 9, 10)
    assert ast.is_valid_binding(None)
    for value in ast.uniform_literal_domain:
        assert ast.is_valid_binding(value)


def test_bindings_outside_the_uniform_domain_are_rejected() -> None:
    """共通部分の外の値は弾く。

    `[ge, multiple_of, mul_k]` に 3 を入れると `mul_k`@3 が `triple` と同一になり
    （改訂版 L275）、別のopとして書けてしまう。
    """
    ast = SemanticAST(("ge", "multiple_of", "mul_k"))
    for value in (0, 1, 2, 3, 11, -5):
        assert not ast.is_valid_binding(value)


def test_non_k_ast_accepts_only_the_parameter_version() -> None:
    """`k` を使わないASTはリテラル版を持たない。"""
    ast = SemanticAST(("negate", "abs", "square"))
    assert ast.uniform_literal_domain == ()
    assert ast.is_valid_binding(None)
    assert not ast.is_valid_binding(5)


@pytest.mark.parametrize(
    "name", ["canonical_forms.md", "open_questions.md", "dev_ai_usage.md"]
)
def test_required_docs_exist(name: str) -> None:
    """実装計画 §5 が求める文書が揃っている。"""
    path = ROOT / "docs" / name
    assert path.exists(), path
    assert len(path.read_text(encoding="utf-8")) > 500, f"{name} が中身に乏しい"


def test_canonical_forms_states_the_round_trip_caveat() -> None:
    """`canonical_forms.md` の冒頭に往復の但し書きがある（実装計画 §2.6 が明示的に要求）。

    > **`docs/canonical_forms.md` の冒頭に明記すること**：往復はASTの同一性としては閉じない。

    将来パーサを書く人がここを読み飛ばすと、AST一致を受け入れ条件にしてしまう。
    """
    text = (ROOT / "docs" / "canonical_forms.md").read_text(encoding="utf-8")
    head = text[:1200]
    assert "往復" in head
    assert "意味的等価性" in head
    assert "run(parse(emit(ast))" in text


def test_canonical_forms_covers_every_shadow_relation() -> None:
    """`shadows` に宣言した対応が文書にも書かれている。

    レジストリと文書が食い違うと、どちらが正しいか判断できなくなる。
    """
    from boku.semantics.registry import OP_REGISTRY

    text = (ROOT / "docs" / "canonical_forms.md").read_text(encoding="utf-8")
    for name, spec in OP_REGISTRY.items():
        for shadowed in spec.shadows:
            assert name in text, name
            assert shadowed in text, shadowed


def test_dev_ai_usage_states_the_output_is_not_data() -> None:
    """`dev_ai_usage.md` が「出力は生成器のソースであって合成データではない」と明記する。

    実装計画 §5 が要求している。改訂版 L808 の但し書きにあたる。
    """
    text = (ROOT / "docs" / "dev_ai_usage.md").read_text(encoding="utf-8")
    assert "合成データそのものではない" in text
