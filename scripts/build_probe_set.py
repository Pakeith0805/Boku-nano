"""固定入力集合を生成して凍結する（実装計画 §9 手順2）。

```powershell
uv run python -m scripts.build_probe_set probe_set.version=v1
```

単一opのAST 24個の出力列が全て相異なるまで自動で増やし、件数を報告する。

## 凍結ファイルを黙って書き換えない

この入力集合は `behavior_hash` の基準である。内容が変わると**全レコードのハッシュが変わる**。
既に凍結したファイルと違う内容が出た場合は、`probe_set.force=true` を明示しない限り
エラーで止める。事故で作り直すと、既存のコーパスと新しいコーパスの `behavior_hash` が
比較できなくなる（漏洩検査が意味を失う）。
"""

import sys
from itertools import permutations
from pathlib import Path

import hydra
from omegaconf import DictConfig

from boku.probes.behavior_probes import (
    build_probe_set,
    describe,
    external_inputs,
    find_false_collisions,
    grow_until_no_false_collisions,
    indistinguishable_pairs,
    load_probe_set,
    save_probe_set,
)
from boku.semantics.registry import OP_NAMES


@hydra.main(config_path="../conf", config_name="probe_set", version_base=None)
def main(cfg: DictConfig) -> None:
    """設定に従って入力集合を作り、凍結する。

    2段階で育てる。

    1. **単一opの識別**（実装計画 §2.5 の受け入れ条件）
    2. **偽の衝突の除去**：単一opが分かれても複合ASTでは分かれないことがあるので、
       入力集合の外から見て食い違う組を探し、その反例を入力集合に足す
    """
    settings = cfg.probe_set
    root = Path(hydra.utils.get_original_cwd())
    out = root / settings.out

    probes = build_probe_set(
        seed=settings.seed,
        random_count=settings.random_count,
        max_probes=settings.max_probes,
    )
    base_count = len(probes)

    verify_difficulties = tuple(settings.verify_difficulties)
    op_sequences = [
        ops
        for difficulty in verify_difficulties
        for ops in permutations(OP_NAMES, difficulty)
    ]
    external = external_inputs(
        count=settings.external_count, seed=settings.seed, exclude=probes
    )
    before = find_false_collisions(op_sequences, probes, external)
    probes = grow_until_no_false_collisions(
        probes,
        op_sequences=op_sequences,
        external=external,
        max_probes=settings.max_probes,
    )

    summary = describe(probes)
    print(f"probe_set_version : {settings.version}")
    print(f"seed              : {settings.seed}")
    print(f"件数              : {summary['count']}"
          f"（境界値20 + 乱数{settings.random_count} + 反例{len(probes) - base_count}）")
    print(f"k の網羅          : {summary['k_values']}")
    print(f"xs の長さ         : {summary['xs_lengths']}")
    print(f"単一op24個の識別  : {'OK（全て相異なる）' if not indistinguishable_pairs(probes) else 'NG'}")
    print(f"偽の衝突の検証    : difficulty {list(verify_difficulties)} の {len(op_sequences):,} 件 "
          f"× 外部入力 {settings.external_count:,} 件")
    print(f"  反例駆動の前    : {len(before)} 件")
    print("  反例駆動の後    : 0 件")

    if out.exists():
        existing = load_probe_set(out)
        if existing == probes:
            print(f"\n既存ファイルと同一。書き換えません: {out}")
            return
        if not settings.force:
            print(
                f"\n[中止] 既存の凍結ファイルと内容が違います: {out}\n"
                f"  既存 {len(existing)} 件 / 新規 {len(probes)} 件\n"
                "  上書きすると全レコードの behavior_hash が変わり、既存コーパスとの比較ができなくなります。\n"
                "  意図した作り直しなら probe_set.force=true を付けてください。",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"\n[force] 既存ファイルを上書きします: {out}")

    save_probe_set(
        out, probes, version=settings.version, random_count=settings.random_count
    )
    print(f"\n凍結しました: {out}")


if __name__ == "__main__":
    main()
