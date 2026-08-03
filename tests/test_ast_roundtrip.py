"""`SemanticAST` の直列化と派生値の検査（実装計画 §7）。

`canonical_json` は `semantic_hash` の入力であり、分割の単位（改訂版 L465）と
漏洩検査第1項（L520）がこれに乗っている。安定していないと、同一seedでの再実行が
別のハッシュになり再現性の確認ができなくなる。
"""

import json
from pathlib import Path

import pytest

from boku.semantics.registry import OP_NAMES, OP_REGISTRY
from boku.semantics.semantic_ast import SCHEMA_VERSION, SemanticAST

SAMPLES: tuple[tuple[str, ...], ...] = (
    ("ge", "double", "asc"),          # 改訂版 L251 の例
    ("even",),                        # difficulty 1
    ("even", "desc"),                 # difficulty 2
    ("desc", "even"),                 # 上と同じop集合で順序違い
    ("even", "add_k", "desc", "take_first"),   # L309 の例。difficulty 4
    ("square", "abs"),                # 縮退するが構造は正当
    ("even", "odd"),                  # 常に空になるが構造は正当
    ("ge", "multiple_of", "mul_k"),   # k参照3スロット。共通部分が最小になる
    ("asc", "reverse"),               # desc と振る舞いが同じ
    ("negate", "abs", "square"),      # k を使わない
)


@pytest.mark.parametrize("ops", SAMPLES)
def test_roundtrip(ops: tuple[str, ...]) -> None:
    """`from_dict(to_dict(ast)) == ast`。"""
    ast = SemanticAST(ops)
    assert SemanticAST.from_dict(ast.to_dict()) == ast


@pytest.mark.parametrize("ops", SAMPLES)
def test_roundtrip_through_json(ops: tuple[str, ...]) -> None:
    """JSONL に書いて読み戻しても等しい（コーパスの往復）。"""
    ast = SemanticAST(ops)
    restored = SemanticAST.from_dict(json.loads(json.dumps(ast.to_dict())))
    assert restored == ast


def test_from_dict_needs_only_semantic_ast() -> None:
    """派生値が無くても復元できる（派生値は出力であって入力ではない）。"""
    ast = SemanticAST.from_dict({"semantic_ast": ["ge", "double", "asc"]})
    assert ast.ops == ("ge", "double", "asc")
    assert ast.difficulty == 3


def test_from_dict_rejects_inconsistent_derived_value() -> None:
    """派生値がop列と食い違うレコードを拒否する。

    レジストリ改訂後に古いコーパスを読むと起きる。黙って捨てると気づけない。
    """
    data = SemanticAST(("ge", "double", "asc")).to_dict()
    data["difficulty"] = 99
    with pytest.raises(ValueError, match="difficulty"):
        SemanticAST.from_dict(data)


def test_from_dict_requires_semantic_ast() -> None:
    """`semantic_ast` が無ければ `KeyError`。"""
    with pytest.raises(KeyError):
        SemanticAST.from_dict({"difficulty": 3})


def test_ops_are_normalized_to_tuple() -> None:
    """リストで渡してもタプルに正規化され、ハッシュ可能になる。

    `semantic_hash` の算出や集合演算でハッシュ可能性が要る。
    """
    ast = SemanticAST(["ge", "double"])  # type: ignore[arg-type]
    assert ast.ops == ("ge", "double")
    assert hash(ast) == hash(SemanticAST(("ge", "double")))
    assert len({ast, SemanticAST(("ge", "double"))}) == 1


def test_canonical_json_is_stable() -> None:
    """同じop列からは常に同じ文字列が出る。"""
    ast = SemanticAST(("ge", "double", "asc"))
    assert ast.canonical_json() == '["ge","double","asc"]'
    assert ast.canonical_json() == SemanticAST(["ge", "double", "asc"]).canonical_json()  # type: ignore[arg-type]


def test_canonical_json_distinguishes_order() -> None:
    """順序が違えば違う文字列になる（改訂版 L297）。

    ここが潰れると、順序違いのASTが同じ `semantic_hash` になり、分割の単位が壊れる。
    """
    assert (
        SemanticAST(("asc", "take_first")).canonical_json()
        != SemanticAST(("take_first", "asc")).canonical_json()
    )


def test_canonical_json_excludes_derived_values() -> None:
    """正準表現にop列以外が混ざらない。

    派生値を入れるとレジストリ改訂で `semantic_hash` まで動いてしまう。
    """
    ast = SemanticAST(("ge", "double", "asc"))
    assert json.loads(ast.canonical_json()) == ["ge", "double", "asc"]


def test_derived_values_of_the_documented_example() -> None:
    """実装計画 §4 のレコード例と一致する（`["ge", "double", "asc"]`）。"""
    ast = SemanticAST(("ge", "double", "asc"))
    assert ast.difficulty == 3
    assert ast.categories == ("filter", "map", "order")
    assert ast.op_set == ("asc", "double", "ge")
    assert ast.canonical_order is True
    assert ast.uses_k is True
    assert ast.uniform_literal_domain == (2, 3, 4, 5, 6, 7, 8, 9, 10)
    assert [slot.to_dict() for slot in ast.binding_slots] == [
        {"index": 0, "op": "ge", "literal_domain": [2, 3, 4, 5, 6, 7, 8, 9, 10]}
    ]


def test_op_set_is_order_independent() -> None:
    """`op_set` が順序に依存しない（予約ペアの引き当てキー、改訂版 L472）。"""
    assert SemanticAST(("even", "desc")).op_set == SemanticAST(("desc", "even")).op_set


def test_canonical_order_detection() -> None:
    """カテゴリ順（抽出→変換→並べ替え→切り出し）に従うかの判定。"""
    assert SemanticAST(("ge", "double", "asc")).canonical_order is True
    assert SemanticAST(("even", "add_k", "desc", "take_first")).canonical_order is True
    assert SemanticAST(("even", "even")).canonical_order is True  # 同カテゴリ内は問わない
    assert SemanticAST(("asc", "even")).canonical_order is False  # 並べ替え→抽出
    assert SemanticAST(("take_first", "double")).canonical_order is False
    assert SemanticAST(("even",)).canonical_order is True  # 単一opは常に真


def test_categories_follow_ast_order_and_may_repeat() -> None:
    """`categories` はAST順で、重複し得る。"""
    assert SemanticAST(("even", "odd")).categories == ("filter", "filter")
    assert SemanticAST(("asc", "even")).categories == ("order", "filter")


def test_non_k_ast_has_no_slots() -> None:
    """`k` を使わないASTはスロットも共通部分も空。"""
    ast = SemanticAST(("negate", "abs", "square"))
    assert ast.uses_k is False
    assert ast.binding_slots == ()
    assert ast.uniform_literal_domain == ()


def test_str_is_readable() -> None:
    """失敗メッセージ用の表示。"""
    assert str(SemanticAST(("ge", "double", "asc"))) == "[ge, double, asc]"


def test_schema_json_is_valid_json() -> None:
    """`schema.json` が壊れていない。"""
    path = Path(__file__).resolve().parents[1] / "boku" / "semantics" / "schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema["type"] == "object"


def test_to_dict_keys_are_declared_in_schema() -> None:
    """`to_dict()` が出す全キーが `schema.json` に宣言されている。

    スキーマは実装計画 §4 のレコード全体を覆うので、`to_dict()` のキーはその部分集合になる。
    残りは `fingerprint.py`（#6）と `corpus.py`（#8）が足す。
    """
    path = Path(__file__).resolve().parents[1] / "boku" / "semantics" / "schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    declared = set(schema["properties"])
    produced = set(SemanticAST(("ge", "double", "asc")).to_dict())

    assert produced <= declared, produced - declared

    # 後段が足すフィールド。ここが変わったらスキーマか計画のどちらかがずれている。
    remaining = declared - produced
    assert remaining == {
        "ast_id",
        "semantic_hash",
        "behavior_hash",
        "always_empty",
        "is_identity",
        "source",
        "created_at",
        "generator_version",
        "schema_version",
        "registry_version",
        "probe_set_version",
    }


def test_schema_op_names_match_registry() -> None:
    """スキーマの操作数の上限がレジストリと整合する。"""
    path = Path(__file__).resolve().parents[1] / "boku" / "semantics" / "schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema["properties"]["semantic_ast"]["maxItems"] == 4
    assert schema["properties"]["difficulty"]["maximum"] == 4
    assert set(schema["properties"]["categories"]["items"]["enum"]) == {
        spec.category for spec in OP_REGISTRY.values()
    }
    assert len(OP_NAMES) == 24


def test_schema_version_is_declared() -> None:
    """`SCHEMA_VERSION` が定義されている（実装計画 §4）。"""
    assert SCHEMA_VERSION == 1
