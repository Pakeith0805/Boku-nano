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
from pathlib import Path

import hydra
from omegaconf import DictConfig

from boku.probes.behavior_probes import (
    build_probe_set,
    describe,
    indistinguishable_pairs,
    load_probe_set,
    save_probe_set,
)


@hydra.main(config_path="../conf", config_name="probe_set", version_base=None)
def main(cfg: DictConfig) -> None:
    """設定に従って入力集合を作り、凍結する。"""
    settings = cfg.probe_set
    root = Path(hydra.utils.get_original_cwd())
    out = root / settings.out

    probes = build_probe_set(
        seed=settings.seed,
        random_count=settings.random_count,
        max_probes=settings.max_probes,
    )

    summary = describe(probes)
    print(f"probe_set_version : {settings.version}")
    print(f"seed              : {settings.seed}")
    print(f"件数              : {summary['count']}（境界値20 + 乱数）")
    print(f"k の網羅          : {summary['k_values']}")
    print(f"xs の長さ         : {summary['xs_lengths']}")
    print(f"単一op24個の識別  : {'OK（全て相異なる）' if not indistinguishable_pairs(probes) else 'NG'}")

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

    save_probe_set(out, probes, version=settings.version)
    print(f"\n凍結しました: {out}")


if __name__ == "__main__":
    main()
