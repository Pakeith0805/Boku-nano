"""既知の可換対と意味的縮退を `behavior_hash` が捕まえることの検査（実装計画 §7, §2.5）。

改訂版 L529-534 が挙げている例をそのまま検査する。**課題文が名指ししている縮退を検出できない
なら、漏洩検査第5項（L524）は機能しない。**したがってこれは固定入力集合の受け入れ条件でもある
（実装計画 §7）。

同時に「別の関数は別の指紋になる」ことも見る。片側だけだと、全部同じ値を返す壊れた実装でも
通ってしまう。
"""

from itertools import permutations
from pathlib import Path

import pytest

from boku.probes.behavior_probes import default_probe_set_path, load_probe_set
from boku.semantics.fingerprint import (
    behavior_hash,
    fingerprint,
    group_by_behavior,
    semantic_hash,
)
from boku.semantics.registry import OP_NAMES
from boku.semantics.semantic_ast import SemanticAST

ROOT = Path(__file__).resolve().parents[1]
PROBES = load_probe_set(default_probe_set_path(ROOT, "v1"))

# 改訂版 L529-534 が挙げている全例。
KNOWN_COLLISIONS: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("even", "positive"), ("positive", "even"), "フィルタ同士は可換（L529）"),
    (("even", "desc"), ("desc", "even"), "フィルタと整列も可換（L530）"),
    (("double", "triple"), ("triple", "double"), "どちらも ×6（L531）"),
    (("square", "abs"), ("square",), "二乗は常に非負なので abs が恒等（L534）"),
)


@pytest.mark.parametrize(("left", "right", "reason"), KNOWN_COLLISIONS)
def test_known_collision_shares_behavior_hash(
    left: tuple[str, ...], right: tuple[str, ...], reason: str
) -> None:
    """課題文が挙げる縮退が同一の `behavior_hash` になる。"""
    assert behavior_hash(SemanticAST(left), PROBES) == behavior_hash(
        SemanticAST(right), PROBES
    ), reason


@pytest.mark.parametrize(("left", "right", "reason"), KNOWN_COLLISIONS)
def test_known_collision_has_different_semantic_hash(
    left: tuple[str, ...], right: tuple[str, ...], reason: str
) -> None:
    """同じ縮退が `semantic_hash` では**別物**になる。

    これが漏洩検査に第5項が要る理由そのものである。第1項（`semantic_hash` の重複なし）は
    通ってしまうので、第5項がないと訓練とテストに同じ関数が分かれて入る（L534）。
    """
    assert semantic_hash(SemanticAST(left)) != semantic_hash(SemanticAST(right)), reason


def test_desc_equals_asc_then_reverse() -> None:
    """`desc` と `[asc, reverse]` は振る舞いが同一（実装計画 §2.6）。

    生成コードが違うのでパース衝突ではないが、関数としては同じ。`behavior_hash` が拾う。
    """
    assert behavior_hash(SemanticAST(("desc",)), PROBES) == behavior_hash(
        SemanticAST(("asc", "reverse")), PROBES
    )


def test_order_sensitive_pairs_do_not_collide() -> None:
    """可換でない組は別の指紋になる（改訂版 L297-302 の例）。

    ここが同じになる実装は、順序を無視しているか、指紋が壊れている。
    """
    assert behavior_hash(SemanticAST(("asc", "take_first")), PROBES) != behavior_hash(
        SemanticAST(("take_first", "asc")), PROBES
    )
    assert behavior_hash(SemanticAST(("add_k", "square")), PROBES) != behavior_hash(
        SemanticAST(("square", "add_k")), PROBES
    )


def test_all_single_ops_have_distinct_behavior_hash() -> None:
    """単一opのAST 24個の `behavior_hash` が全て相異なる。

    #5 の識別力の検査を、出力列ではなくハッシュの側で確認する。
    ハッシュ化の段で潰れていないことの確認になる。
    """
    hashes = {name: behavior_hash(SemanticAST((name,)), PROBES) for name in OP_NAMES}
    assert len(set(hashes.values())) == 24


def test_always_empty_is_detected() -> None:
    """常に空になるASTを検出する（除去はしない、実装計画 §2.5）。"""
    assert fingerprint(SemanticAST(("even", "odd")), PROBES).always_empty is True
    assert fingerprint(SemanticAST(("zero", "positive")), PROBES).always_empty is True
    assert fingerprint(SemanticAST(("even",)), PROBES).always_empty is False


def test_always_empty_asts_share_one_behavior_hash() -> None:
    """常に空になるASTはすべて同じ指紋になる（出力が全て空列で一致するため）。

    自明だが、選抜段が「always_empty のグループが1つの巨大な衝突塊になる」ことを
    知っておく必要がある。
    """
    assert behavior_hash(SemanticAST(("even", "odd")), PROBES) == behavior_hash(
        SemanticAST(("zero", "positive")), PROBES
    )


def test_is_identity_detects_a_constructed_case() -> None:
    """`is_identity` の判定そのものを、恒等になる入力集合で確認する。

    実際の固定入力集合には負数が含まれるので `abs` は恒等にならない。判定ロジックを
    検査するために、非負だけの入力集合を別に作って当てる。
    """
    non_negative = [((0, 1, 2, 3), 2), ((100,), 5), ((), 1)]
    assert fingerprint(SemanticAST(("abs",)), non_negative).is_identity is True
    assert fingerprint(SemanticAST(("negate",)), non_negative).is_identity is False


def test_is_identity_is_false_on_the_real_probe_set() -> None:
    """実際の固定入力集合では `abs` は恒等にならない（負数を含むため）。"""
    assert fingerprint(SemanticAST(("abs",)), PROBES).is_identity is False


def test_difficulty_1_has_no_collisions() -> None:
    """difficulty 1 の24件は全て別の指紋（衝突グループが24個）。"""
    asts = [SemanticAST((name,)) for name in OP_NAMES]
    groups = group_by_behavior(asts, PROBES)
    assert len(groups) == 24
    assert max(len(members) for members in groups.values()) == 1


def test_difficulty_2_collision_groups_contain_the_known_pairs() -> None:
    """difficulty 2 の552件を全数評価し、既知の可換対が同一グループに入る。

    実装計画 §9 の期待出力「既知の可換対が同一グループに入っていること」を、
    コーパス構築を待たずにこの規模で先に確認しておく。
    """
    asts = [SemanticAST(ops) for ops in permutations(OP_NAMES, 2)]
    groups = group_by_behavior(asts, PROBES)

    lookup = {
        ast.ops: digest for digest, members in groups.items() for ast in members
    }
    for left, right, reason in KNOWN_COLLISIONS:
        if len(left) == 2 and len(right) == 2:
            assert lookup[left] == lookup[right], reason

    # 衝突は実在し、かつ全部が1つに潰れてはいない。
    assert len(groups) < len(asts), "衝突が1件も検出されていない"
    assert len(groups) > 1, "全ASTが同じ指紋になっている（指紋が壊れている）"
