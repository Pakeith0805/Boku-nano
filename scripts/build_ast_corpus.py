"""ASTコーパスを構築する（実装計画 §9 手順3）。

```powershell
uv run python -m scripts.build_ast_corpus seed=0            # conf の既定 target=45,000
uv run python -m scripts.build_ast_corpus target=30000 seed=0  # 明示指定
```

意味AST層の総仕上げにあたる。列挙（#7）→ 構造検証（#3）→ 指紋（#6）→ レコード化（#8）を
通しで実行し、`asts.jsonl` と `manifest.json` を書き、MLflow に1 runとして記録する。

## MLflow は索引であって正本ではない

`manifest.json` は MLflow に載せても**コーパスと同じ場所に必ず残す**（実装計画 §11）。
MLflow のストアはツールの都合で移動・消去され得るが、改訂版 L795-808 が求めている
由来の記録はコーパスに添えられている方である。`mlflow.enabled=false` にしても
`manifest.json` は書かれる。
"""

from collections import Counter
from itertools import permutations
from pathlib import Path
from typing import Any

import hydra
from omegaconf import DictConfig, OmegaConf

from boku.probes.behavior_probes import default_probe_set_path, load_probe_set
from boku.semantics.corpus import (
    RecordMeta,
    build_manifest,
    build_records,
    drop_behavior_duplicates,
    utc_now_rfc3339,
    write_manifest,
    write_records,
)
from boku.semantics.enumeration import (
    allocation_from_counts,
    default_allocation,
    enumerate_asts,
)
from boku.semantics.registry import MAX_OPS, OP_NAMES, OP_REGISTRY
from boku.semantics.semantic_ast import SemanticAST
from boku.semantics.validate import problems


def _resolve_allocation(cfg: DictConfig):
    """設定から層化配分を作る。

    `alloc` が指定されていればそれを検証して使い、なければ `target` から既定配分を作る。
    **どちらの経路でも同じ検証（改訂版 L397 の帯）を通す。**抜け道を作らないため。
    """
    if cfg.alloc is None:
        return default_allocation(cfg.target)
    return allocation_from_counts(list(cfg.alloc), target=cfg.target)


def _report(title: str, rows: list[tuple[str, Any]]) -> None:
    """整形して表示する。"""
    print(f"\n--- {title} ---")
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label.ljust(width)} : {value}")


def _log_to_mlflow(cfg: DictConfig, manifest: dict[str, Any], paths: list[Path]) -> None:
    """1回の生成を MLflow の1 runとして記録する（実装計画 §11）。"""
    import mlflow  # noqa: PLC0415  スクリプト層でだけ触る（§11 の依存の層）

    if cfg.mlflow.tracking_uri:
        mlflow.set_tracking_uri(cfg.mlflow.tracking_uri)
    mlflow.set_experiment(cfg.mlflow.experiment)

    with mlflow.start_run():
        mlflow.log_params(
            {
                "target": manifest["target"],
                "seed": manifest["seed"],
                "max_ops": manifest["max_ops"],
                "registry_version": manifest["registry_version"],
                "probe_set_version": manifest["probe_set_version"],
                "generator_version": manifest["generator_version"],
                "schema_version": manifest["schema_version"],
                "drop_behavior_duplicates": manifest["drop_behavior_duplicates"],
                "probe_count": manifest["probe_count"],
            }
        )

        metrics: dict[str, float] = {
            "record_count": manifest["record_count"],
            "behavior_hash_distinct": manifest["behavior_hash"]["distinct"],
            "behavior_hash_largest_group": manifest["behavior_hash"]["largest_group"],
            "behavior_hash_collision_groups": manifest["behavior_hash"]["collision_groups"],
            "behavior_hash_asts_in_collisions": manifest["behavior_hash"]["asts_in_collisions"],
            "always_empty_count": manifest["always_empty_count"],
            "is_identity_count": manifest["is_identity_count"],
            "canonical_order_ratio": manifest["canonical_order_ratio"],
            "uniform_literal_domain_min": manifest["uniform_literal_domain_min"],
            "max_output_abs_digits": manifest["max_output_abs_digits"],
            "op_frequency_max_deviation": manifest["op_frequency_max_deviation"],
        }
        for difficulty, count in manifest["allocation"]["actual"].items():
            metrics[f"records_difficulty_{difficulty}"] = count
        for slots, count in manifest["k_slot_distribution"].items():
            metrics[f"k_slots_{slots}"] = count
        for category, count in manifest["category_frequency"].items():
            metrics[f"category_{category}"] = count
        mlflow.log_metrics(metrics)

        for path in paths:
            if path.exists():
                mlflow.log_artifact(str(path))


@hydra.main(config_path="../conf", config_name="config", version_base=None)
def main(cfg: DictConfig) -> None:
    """設定に従ってコーパスを構築する。"""
    root = Path(hydra.utils.get_original_cwd())
    created_at = utc_now_rfc3339()

    allocation = _resolve_allocation(cfg)
    probe_path = default_probe_set_path(root, cfg.probe_set_version)
    if not probe_path.exists():
        raise SystemExit(
            f"固定入力集合がない: {probe_path}\n"
            "  先に build_probe_set を実行すること（実装計画 §9 手順2）"
        )
    probes = load_probe_set(probe_path)

    print(f"設定:\n{OmegaConf.to_yaml(cfg)}".rstrip())

    # ---- 列挙 ----
    asts = enumerate_asts(allocation, seed=cfg.seed)

    # ---- 構造検証（実装計画 §9「構造検証通過 ＝ 全件」）----
    invalid = [(ast, problems(ast)) for ast in asts if problems(ast)]
    if invalid:
        raise SystemExit(f"列挙器が不正なASTを作った: {invalid[:3]}")

    # ---- 指紋とレコード化 ----
    meta = RecordMeta(
        created_at=created_at, probe_set_version=cfg.probe_set_version
    )
    records, max_digits = build_records(asts, probes, meta)

    dropped = 0
    if cfg.drop_behavior_duplicates:
        records, dropped = drop_behavior_duplicates(records)

    manifest = build_manifest(
        records,
        allocation=allocation,
        target=cfg.target,
        seed=cfg.seed,
        probe_count=len(probes),
        max_output_digits=max_digits,
        meta=meta,
        drop_behavior_duplicates=bool(cfg.drop_behavior_duplicates),
    )

    # op出現頻度の偏り（改訂版 L458 が均されているかの実測）
    frequencies = list(manifest["op_frequency"].values())
    expected = sum(frequencies) / len(frequencies)
    deviation = max(abs(value - expected) / expected for value in frequencies)
    manifest["op_frequency_max_deviation"] = round(deviation, 6)
    manifest["dropped_behavior_duplicates"] = dropped

    # ---- 書き出し ----
    out = root / cfg.out
    manifest_out = root / cfg.manifest_out
    write_records(out, records)
    write_manifest(manifest_out, manifest)

    # ---- 報告（実装計画 §9 の「期待される出力」）----
    _report(
        "配分（改訂版 L416-421）",
        [
            (f"difficulty {d}", f"{manifest['allocation']['actual'][str(d)]:>7,}"
             f"  （計画 {manifest['allocation']['planned'][str(d)]:>7,}）"
             f"{'  全数' if allocation.is_exhaustive(d) else ''}")
            for d in range(1, MAX_OPS + 1)
        ]
        + [("合計", f"{manifest['record_count']:>7,}")],
    )
    _report(
        "検証",
        [
            ("構造検証", f"全 {len(asts):,} 件通過"),
            ("op出現頻度の偏り", f"最大 {deviation:.3%}（一様からの相対偏差）"),
            (
                "カテゴリ頻度",
                " : ".join(
                    f"{c} {n:,}" for c, n in manifest["category_frequency"].items()
                ),
            ),
            (
                "uniform域",
                f"最小 {manifest['uniform_literal_domain_min']} "
                f"（k参照ASTは全件で非空）",
            ),
            ("k参照スロット分布", manifest["k_slot_distribution"]),
        ],
    )
    _report(
        "behavior_hash（漏洩検査第5項の材料）",
        [
            ("異なり数", f"{manifest['behavior_hash']['distinct']:,}"),
            ("衝突グループ", f"{manifest['behavior_hash']['collision_groups']:,}"),
            ("最大グループ長", f"{manifest['behavior_hash']['largest_group']:,}"),
            ("衝突に関与するAST", f"{manifest['behavior_hash']['asts_in_collisions']:,}"),
            ("除去した重複", f"{dropped:,}（既定は除去しない）"),
        ],
    )

    # 既知の可換対が同一グループに入っているか（実装計画 §9 の期待出力）
    by_ops = {tuple(r["semantic_ast"]): r["behavior_hash"] for r in records}
    known = [
        (("even", "positive"), ("positive", "even")),
        (("even", "desc"), ("desc", "even")),
        (("double", "triple"), ("triple", "double")),
    ]
    checks = [
        (f"{list(a)} / {list(b)}",
         "同一グループ" if by_ops.get(a) == by_ops.get(b) is not None else "不一致")
        for a, b in known
    ]
    _report("既知の可換対（改訂版 L529-531）", checks)

    _report(
        "その他",
        [
            ("always_empty", f"{manifest['always_empty_count']:,} 件"),
            ("is_identity", f"{manifest['is_identity_count']:,} 件"),
            ("canonical_order 比率", f"{manifest['canonical_order_ratio']:.3f}"),
            (
                "出力の絶対値の最大桁数",
                f"{manifest['max_output_abs_digits']} 桁"
                "（Phase 2 のトークナイザ設計への申し送り）",
            ),
        ],
    )

    print(f"\n書き出し: {out}")
    print(f"          {manifest_out}")

    if cfg.mlflow.enabled:
        _log_to_mlflow(cfg, manifest, [manifest_out, probe_path])
        print(f"MLflow:   experiment={cfg.mlflow.experiment} に記録した")
    else:
        print("MLflow:   無効（manifest.json は書かれている）")


if __name__ == "__main__":
    main()
