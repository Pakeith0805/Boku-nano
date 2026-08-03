"""構造検証の検査（実装計画 §7）。

検証は3項目だけであること、そして**それ以上のことをしないこと**の両方を固定する。
「やらない」側が重要で、代数的な書き換えを足すと正解データを汚染する（実装計画 §2.7）。
"""

import pytest

from boku.semantics.semantic_ast import SemanticAST
from boku.semantics.validate import ValidationError, is_valid, problems, validate

VALID: tuple[tuple[str, ...], ...] = (
    ("even",),
    ("ge", "double", "asc"),
    ("even", "add_k", "desc", "take_first"),
    ("take_first", "asc"),
    ("asc", "take_first"),
)


@pytest.mark.parametrize("ops", VALID)
def test_valid_asts_pass(ops: tuple[str, ...]) -> None:
    """正当なASTは通る。"""
    ast = SemanticAST(ops)
    assert problems(ast) == []
    assert is_valid(ast)
    validate(ast)


def test_rejects_difficulty_0() -> None:
    """操作数0を弾く（改訂版 L111「1〜4個」）。"""
    ast = SemanticAST(())
    assert not is_valid(ast)
    with pytest.raises(ValidationError, match="操作数が0"):
        validate(ast)


def test_rejects_difficulty_5() -> None:
    """操作数5を弾く（上限は `MAX_OPS` = 4）。"""
    ast = SemanticAST(("even", "odd", "asc", "desc", "reverse"))
    with pytest.raises(ValidationError, match="操作数が5"):
        validate(ast)


def test_rejects_duplicate_op() -> None:
    """同一opの重複を弾く（L111「同一の操作を2回以上使用しない」）。"""
    ast = SemanticAST(("even", "asc", "even"))
    with pytest.raises(ValidationError, match="重複"):
        validate(ast)


def test_rejects_unknown_op() -> None:
    """未知のop名を弾く（L113-157 の表にない名前）。"""
    ast = SemanticAST(("even", "sort_descending"))
    with pytest.raises(ValidationError, match="未知のop名"):
        validate(ast)


def test_reports_all_problems_at_once() -> None:
    """問題を1件で打ち切らず全件返す。

    コーパス構築で「何件がどの理由で落ちたか」を集計するために要る。
    """
    ast = SemanticAST(("even", "even", "nope", "asc", "desc"))
    found = problems(ast)
    assert len(found) == 3
    assert any("操作数が5" in message for message in found)
    assert any("重複" in message for message in found)
    assert any("未知のop名" in message for message in found)


def test_error_message_includes_the_ast() -> None:
    """失敗メッセージにAST自体が入る（どのレコードで落ちたか分かる）。"""
    with pytest.raises(ValidationError, match=r"\[even, even\]"):
        validate(SemanticAST(("even", "even")))


# ---- ここから「やらない」ことの検査（実装計画 §2.7）----


def test_accepts_always_empty_ast() -> None:
    """常に空になるASTも構造としては正当なので通す。

    `[even, odd]` は偶数を残してから奇数を残すので必ず空になる。除去するかどうかは
    選抜段の判断であり、検証器は口を出さない（実装計画 §8 確認事項⑦）。
    """
    validate(SemanticAST(("even", "odd")))


def test_accepts_semantically_degenerate_asts() -> None:
    """意味的に縮退するASTも通す。

    これらを弾いたり書き換えたりすると、手書きの代数則で正解データを汚染する。
    縮退の検出は `behavior_hash` の担当（実装計画 §2.5）。
    """
    validate(SemanticAST(("square", "abs")))     # 二乗は非負なので abs が恒等（L534）
    validate(SemanticAST(("negate", "abs")))     # abs 単体と同じ
    validate(SemanticAST(("asc", "desc")))       # desc 単体と同じ
    validate(SemanticAST(("asc", "reverse")))    # desc と同じ振る舞い


def test_accepts_both_orders_of_commutative_pairs() -> None:
    """可換な操作対の両方の順序を通す。

    `[even, positive]` と `[positive, even]` は同じ関数だが、意味ASTとしては別物である
    （改訂版 L297）。同一視するのは `behavior_hash` の仕事であって検証器の仕事ではない。
    """
    validate(SemanticAST(("even", "positive")))
    validate(SemanticAST(("positive", "even")))


def test_does_not_rewrite_the_ast() -> None:
    """検証がASTを書き換えない（`validate` は何も返さない）。"""
    ast = SemanticAST(("square", "abs"))
    assert validate(ast) is None
    assert ast.ops == ("square", "abs")


def test_does_not_sort_filters() -> None:
    """filter を並べ替えない（順序が意味を持つ表現で並べ替えると情報が壊れる）。"""
    ast = SemanticAST(("positive", "even"))
    validate(ast)
    assert ast.ops == ("positive", "even")
