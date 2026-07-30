"""リテラル値域が改訂版 L269-277 の規定に一致することの検査（実装計画 §7）。

期待値は `_domain()` を経由せず**明示的なタプルで直接書く**。レジストリと同じ式で計算すると
式の誤りを検出できないため、独立した書き下しにしている。
"""

from boku.semantics.registry import (
    LITERAL_MAX,
    LITERAL_MIN,
    OP_REGISTRY,
)

# 改訂版 L269-277 から書き下したリテラル値域。
#   L269      使える値は `k` と同じ 1〜10 の整数に限る
#   L273      恒等変換になる値：`mul_k` に 1
#   L274      恒真になる値：`multiple_of` に 1
#   L275      他の操作と同一になる値：`multiple_of` に 2、`mul_k` に 2 と 3、`ge` に 1
#   L277      `lt` に 1 は `negative` と異なるため除外しない
EXPECTED_DOMAINS: dict[str, tuple[int, ...]] = {
    "gt": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "ge": (2, 3, 4, 5, 6, 7, 8, 9, 10),
    "lt": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "le": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "multiple_of": (3, 4, 5, 6, 7, 8, 9, 10),
    "add_k": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "sub_k": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "mul_k": (4, 5, 6, 7, 8, 9, 10),
    "take_first": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "take_last": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
}


def test_literal_range_is_1_to_10() -> None:
    """リテラルの範囲は 1〜10（改訂版 L269）。`k` の値域 L104 と同一。"""
    assert LITERAL_MIN == 1
    assert LITERAL_MAX == 10


def test_domains_match_spec() -> None:
    """`k` 参照opの値域が改訂版 L269-277 のとおり。"""
    actual = {
        name: spec.literal_domain
        for name, spec in OP_REGISTRY.items()
        if spec.uses_k
    }
    assert actual == EXPECTED_DOMAINS


def test_non_k_ops_have_empty_domain() -> None:
    """`k` を参照しないopは空の値域を持つ（実装計画 §2.8 の `OpSpec`）。"""
    for name, spec in OP_REGISTRY.items():
        if not spec.uses_k:
            assert spec.literal_domain == (), name


def test_ge_excludes_1() -> None:
    """`ge`@1 は要素が整数なので `positive` と同一（改訂版 L275）。"""
    assert 1 not in OP_REGISTRY["ge"].literal_domain
    assert 2 in OP_REGISTRY["ge"].literal_domain


def test_multiple_of_excludes_1_and_2() -> None:
    """`multiple_of`@1 は恒真、@2 は `even` と同一（改訂版 L274-275）。"""
    domain = OP_REGISTRY["multiple_of"].literal_domain
    assert 1 not in domain
    assert 2 not in domain
    assert 3 in domain


def test_mul_k_excludes_1_2_3() -> None:
    """`mul_k`@1 は恒等、@2 は `double`、@3 は `triple` と同一（改訂版 L273-275）。"""
    domain = OP_REGISTRY["mul_k"].literal_domain
    assert 1 not in domain
    assert 2 not in domain
    assert 3 not in domain
    assert 4 in domain


def test_lt_includes_1() -> None:
    """`lt`@1（x < 1）は `negative`（x < 0）とゼロの扱いが違うので**除外しない**（改訂版 L277）。

    除外しがちな値をわざと保持している箇所なので、明示的に固定する。
    """
    assert 1 in OP_REGISTRY["lt"].literal_domain


def test_gt_and_le_have_no_exclusions() -> None:
    """`gt` と `le` に除外規定はない（改訂版 L273-277 に記載がない）。"""
    full = tuple(range(1, 11))
    assert OP_REGISTRY["gt"].literal_domain == full
    assert OP_REGISTRY["le"].literal_domain == full


def test_add_k_and_sub_k_have_no_exclusions() -> None:
    """`add_k`・`sub_k` の @0 は値域外なので除外規定を要しない（改訂版 L277）。"""
    full = tuple(range(1, 11))
    assert OP_REGISTRY["add_k"].literal_domain == full
    assert OP_REGISTRY["sub_k"].literal_domain == full


def test_take_ops_have_no_exclusions() -> None:
    """`take_first`・`take_last` に除外規定はない。"""
    full = tuple(range(1, 11))
    assert OP_REGISTRY["take_first"].literal_domain == full
    assert OP_REGISTRY["take_last"].literal_domain == full


def test_all_domains_within_1_to_10() -> None:
    """すべての値域が 1〜10 に収まる（改訂版 L269。値域外は検証不能になる）。"""
    for name, spec in OP_REGISTRY.items():
        for value in spec.literal_domain:
            assert LITERAL_MIN <= value <= LITERAL_MAX, (name, value)


def test_domains_are_sorted_and_unique() -> None:
    """値域が昇順で重複を持たない（レコードに出す `uniform_literal_domain` の前提）。"""
    for name, spec in OP_REGISTRY.items():
        domain = spec.literal_domain
        assert list(domain) == sorted(domain), name
        assert len(set(domain)) == len(domain), name


def test_smallest_domain_has_7_values() -> None:
    """最小の値域は `mul_k` の7値（実装計画 §2.4）。

    「複数スロットASTでも共通部分は最小7、空にはならない」という §2.4 の主張は、
    除外がすべて下限側にあり最大の除外集合が `mul_k` の {1, 2, 3} であることに乗っている。
    ここが崩れたら §2.4 の主張を再検証する必要がある。
    """
    sizes = [
        len(spec.literal_domain) for spec in OP_REGISTRY.values() if spec.uses_k
    ]
    assert min(sizes) == 7
    assert max(sizes) == 10
    assert len(OP_REGISTRY["mul_k"].literal_domain) == 7


def test_all_exclusions_are_low_end_prefixes() -> None:
    """除外はすべて下限側にあり、値域は連続区間である（実装計画 §2.4、`_domain()` の前提）。

    途中に穴があく除外が現れたら `_domain()` では表せなくなるため、その検出を兼ねる。
    """
    for name, spec in OP_REGISTRY.items():
        if not spec.uses_k:
            continue
        domain = spec.literal_domain
        assert domain[-1] == LITERAL_MAX, name
        assert domain == tuple(range(domain[0], LITERAL_MAX + 1)), name
