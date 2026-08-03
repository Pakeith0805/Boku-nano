"""固定入力集合の生成と読み書き（実装計画 §2.5, §3）。

改訂版 L536 はこう定めている。

> `behavior_hash`は、境界値と乱数を混ぜた固定の入力集合（例: 境界値20件＋ランダム50件）に対する
> 参照インタプリタの出力列を連結してハッシュ化すればよい。入力集合は全レコードで共通のものを使う。

入力は `(xs, k)` の対にする。opが `k` を参照するため、`xs` だけでは意味を同定できない。

## 識別力が要件である

この入力集合の目的は**意味の同定**であって、現実的な入力分布の再現ではない。したがって
「どのopとどのopを分けるために、どんな入力が要るか」から逆算して作る（実装計画 §2.5）。

分けたい組と、そのために要る条件はこうなる。

| 分けたい組 | 要る条件 |
| --- | --- |
| `gt` と `ge`／`lt` と `le` | `xs` に `k` と等しい値を含む |
| `mul_k` と `double` / `triple` | `k ∉ {2, 3}` |
| `multiple_of` と `even` | `k ≠ 2` |
| `ge` と `positive` | `k ≠ 1` |
| `lt` と `negative` | `k = 1` かつ `xs` に `0` を含む |
| `take_first` と `take_last` | `len(xs) > k` と `len(xs) < k` の両方 |
| `asc` と `desc` と `reverse` | 未整列で相異なる要素を含む |

これらを満たす境界値を手で書き、乱数で埋めたうえで、
**単一opのAST 24個の出力列が全て相異なる**ようになるまで増やす。

## `k` の網羅がリテラル版のカバーになる

`k` が 1〜10 を網羅していれば、リテラルに具体化した版の振る舞いもすべて覆われる。
改訂版 L269 の「リテラル版 ＝ 参照インタプリタを `k` ＝そのリテラル値で評価した結果」という
性質の帰結である。

ただし成立条件は**一様具体化**（全スロットを同じ値にする、実装計画 §2.4）である。
スロットごとに別の値を入れた版はどの `k` の評価とも一致しないため、この入力集合では覆えない。

## 出力列を返すところまでがこの層

`behavior_hash` そのもの（SHA-256）は `fingerprint.py` の担当である（実装計画 §2.5）。
ここは入力集合と、それに対する出力列までを持つ。分けておくと、この層が
`fingerprint.py` に依存せずに済み、入力集合を作る段階で識別力を確認できる。
"""

import json
import random
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from boku.interp.run import run
from boku.limits import ELEM_MAX, ELEM_MIN, K_MAX, K_MIN, XS_LEN_MAX, XS_LEN_MIN
from boku.semantics.registry import OP_NAMES

ProbeInput = tuple[tuple[int, ...], int]
"""固定入力集合の1件。`(xs, k)`。`xs` はハッシュ可能にするためタプル。"""

MAX_PROBES: Final[int] = 256
"""入力集合の上限（実装計画 §2.5）。

識別力が足りなければ増やすが、際限なく増やすと `behavior_hash` の算出コストが
267,744件×入力数に効いてくる。
"""

DEFAULT_RANDOM_COUNT: Final[int] = 50
"""乱数で足す件数の初期値（改訂版 L536 の「ランダム50件」）。"""

# 境界値。改訂版 L536 の「境界値20件」にあたる。
# 上の表の条件を満たすように手で選んである。順序は固定（出力列の順序がハッシュに効くため）。
_BOUNDARY: Final[tuple[tuple[tuple[int, ...], int, str], ...]] = (
    ((), 1, "空リスト・k下限（L102の長さ下限0は正当な入力）"),
    ((), 10, "空リスト・k上限"),
    ((0,), 1, "長さ1・ゼロのみ・k=1（lt と negative を分ける）"),
    ((0, 0, 0), 5, "全ゼロ・長さ3"),
    ((5,), 5, "長さ1・x==k（gt と ge を分ける）・len(xs) < k"),
    ((1, 2), 2, "長さ2・x==k・len(xs) == k"),
    ((-1, -2, -3), 1, "全負・長さ3・k=1"),
    ((1, 2, 3), 3, "全正・x==k・len(xs) == k"),
    ((7, 7, 7, 7, 7), 7, "重複値・長さ5・x==k・len(xs) < k"),
    ((-100, 100), 10, "要素の境界（L103の±100）・長さ2"),
    ((-100, -50, 0, 50, 100), 5, "正負混在＋ゼロ・長さ5"),
    ((5, 1, 9, 3), 2, "未整列（asc・desc・reverse を分ける）"),
    ((2, 4, 6, 8, 10), 2, "全偶数・k=2（multiple_of が even と一致する側）"),
    ((3, 6, 9, 12), 3, "3の倍数・k=3（mul_k が triple と一致する側）"),
    ((1, 2, 3, 4, 5, 6, 7, 8, 9, 10), 7, "k=7（multiple_of と even を分ける）・len(xs) > k"),
    ((0, 1, -1), 1, "k=1・ゼロ含む（lt と negative を分ける）"),
    ((4, 8, 12, 16), 4, "k=4（mul_k と double/triple を分ける、k∉{2,3}）"),
    ((1, 2, 3), 9, "len(xs) < k・k=9"),
    ((-5, -4, -3, -2, -1), 6, "全負・len(xs) < k・k=6"),
    (
        (10, 20, 30, 40, 50, 60, 70, 80, 90, 100,
         -10, -20, -30, -40, -50, -60, -70, -80, -90, -100),
        8,
        "長さ20（L102の上限）・len(xs) > k・k=8",
    ),
)


def boundary_inputs() -> list[ProbeInput]:
    """手書きの境界値（20件）。"""
    return [(xs, k) for xs, k, _ in _BOUNDARY]


def boundary_notes() -> list[str]:
    """境界値それぞれの意図。`build_probe_set` が出力ファイルに残す。"""
    return [note for _, _, note in _BOUNDARY]


def random_input(rng: random.Random) -> ProbeInput:
    """L102-104 の範囲から `(xs, k)` を1件引く。"""
    length = rng.randint(XS_LEN_MIN, XS_LEN_MAX)
    xs = tuple(rng.randint(ELEM_MIN, ELEM_MAX) for _ in range(length))
    return xs, rng.randint(K_MIN, K_MAX)


def probe_outputs(
    ops: Sequence[str], probes: Sequence[ProbeInput]
) -> tuple[tuple[int, ...], ...]:
    """意味AST `ops` を入力集合の全件で評価した出力列。

    `fingerprint.py` はこれをハッシュして `behavior_hash` にする（実装計画 §2.5）。
    順序が意味を持つので、`probes` の並びを変えると出力列も変わる。だから入力集合は凍結する。
    """
    return tuple(tuple(run(ops, xs, k)) for xs, k in probes)


def single_op_outputs(
    probes: Sequence[ProbeInput],
) -> dict[str, tuple[tuple[int, ...], ...]]:
    """単一opのAST 24個それぞれの出力列。"""
    return {name: probe_outputs((name,), probes) for name in OP_NAMES}


def indistinguishable_pairs(probes: Sequence[ProbeInput]) -> list[tuple[str, str]]:
    """この入力集合では区別できない単一opの組を返す。空なら識別力が足りている。

    単一opすら分けられない入力集合では、複合ASTの `behavior_hash` も信用できない。
    したがってこれが空になることが入力集合の受け入れ条件になる（実装計画 §2.5）。
    """
    outputs = single_op_outputs(probes)
    names = sorted(outputs)
    return [
        (left, right)
        for i, left in enumerate(names)
        for right in names[i + 1:]
        if outputs[left] == outputs[right]
    ]


def build_probe_set(
    seed: int,
    random_count: int = DEFAULT_RANDOM_COUNT,
    max_probes: int = MAX_PROBES,
) -> list[ProbeInput]:
    """境界値＋乱数で入力集合を作り、識別力が足りるまで乱数を足す。

    単一opのAST 24個の出力列が全て相異なるまで増やす（実装計画 §2.5）。

    Args:
        seed: 乱数の種。**固定入力集合専用の名前空間**として使う（実装計画 §3）。
            hidden test 生成器とは別の種を使い、両者が同じ入力を引かないようにする。
        random_count: 最初に足す乱数の件数。
        max_probes: 全体の上限。

    Returns:
        重複のない `(xs, k)` のリスト。境界値が先、乱数が後。

    Raises:
        RuntimeError: 上限まで増やしても単一opを区別できないとき。
            入力集合の設計そのものを見直す必要がある。
    """
    rng = random.Random(seed)
    probes = boundary_inputs()
    seen = set(probes)

    def add_random(count: int) -> None:
        added = 0
        attempts = 0
        while added < count and len(probes) < max_probes:
            attempts += 1
            if attempts > count * 1000:
                raise RuntimeError("乱数入力が重複ばかりで増やせない")
            candidate = random_input(rng)
            if candidate in seen:
                continue
            seen.add(candidate)
            probes.append(candidate)
            added += 1

    add_random(random_count)

    while indistinguishable_pairs(probes):
        if len(probes) >= max_probes:
            pairs = indistinguishable_pairs(probes)
            raise RuntimeError(
                f"上限 {max_probes} 件でも単一opを区別できない: {pairs}"
            )
        add_random(min(10, max_probes - len(probes)))

    return probes


def save_probe_set(path: Path, probes: Sequence[ProbeInput], version: str) -> None:
    """入力集合を JSONL で保存する（1行1件）。

    境界値には意図の説明を添える。後から「なぜこの入力が要るのか」を追えるようにするため。
    """
    notes = boundary_notes()
    lines = []
    for index, (xs, k) in enumerate(probes):
        record: dict[str, object] = {
            "index": index,
            "xs": list(xs),
            "k": k,
            "kind": "boundary" if index < len(notes) else "random",
            "probe_set_version": version,
        }
        if index < len(notes):
            record["note"] = notes[index]
        lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_probe_set(path: Path) -> list[ProbeInput]:
    """保存した入力集合を**順序を保って**読み戻す。

    順序が変わると出力列も変わり、`behavior_hash` が全件変わってしまう。
    """
    probes: list[ProbeInput] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        probes.append((tuple(record["xs"]), record["k"]))
    return probes


def load_probe_inputs(path: Path) -> set[ProbeInput]:
    """入力集合を**集合として**返す（実装計画 §3）。

    将来の hidden test 生成器がこれを読み、衝突する `(xs, k)` を除外するための入口。
    固定入力集合と hidden test が同じ入力を共有すると、「意味の同定に使った入力で評価する」
    ことになり、評価が甘くなる。

    順序は捨てる。衝突判定にしか使わないため。
    """
    return set(load_probe_set(path))


def default_probe_set_path(root: Path, version: str) -> Path:
    """凍結ファイルの既定の置き場所（実装計画 §5）。"""
    return root / "probes" / f"behavior_probe_set_{version}.jsonl"


def describe(probes: Iterable[ProbeInput]) -> dict[str, object]:
    """入力集合の要約。ビルド時の報告と `manifest.json` に使う。"""
    items = list(probes)
    lengths = sorted({len(xs) for xs, _ in items})
    ks = sorted({k for _, k in items})
    return {
        "count": len(items),
        "k_values": ks,
        "k_covers_full_range": ks == list(range(K_MIN, K_MAX + 1)),
        "xs_lengths": lengths,
        "has_empty_xs": 0 in lengths,
        "has_max_length_xs": XS_LEN_MAX in lengths,
        "has_x_equal_to_k": any(k in xs for xs, k in items),
        "has_len_greater_than_k": any(len(xs) > k for xs, k in items),
        "has_len_less_than_k": any(len(xs) < k for xs, k in items),
    }
