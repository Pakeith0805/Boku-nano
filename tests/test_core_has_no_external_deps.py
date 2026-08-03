"""依存の層を機械的に固定する（実装計画 §7, §11）。

| 層 | 許す依存 |
| --- | --- |
| `boku/` | **標準ライブラリのみ**（＋ `boku` 内部） |
| `scripts/` | ＋ `hydra-core`（`omegaconf`）、`mlflow` |
| `tests/` | ＋ `pytest` |

## なぜ機械的に止めるのか

参照インタプリタは意味の唯一の権威（実装計画 §2.7）であり、`OP_REGISTRY` は意味を持たない
データ（§2.8）である。ここに設定ライブラリや実験管理の都合が混ざると、監査の対象が
「手書きの退屈なコード」から「ライブラリの挙動込み」に広がる。

境界は口約束では守れない。`hydra` や `mlflow` を `boku/` の中で import しても普通に動いて
しまうので、テストで止める。

## この検査自体が命名判断の受益者

import 文の走査には標準ライブラリの `ast` を使う。もし意味ASTのモジュールを `ast.py` と
名付けていたら、`boku/semantics/` を直接実行する経路で標準の `ast` が隠れていた
（実装計画 §5「モジュール名で標準ライブラリを隠さない」）。
"""

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "boku"

SCRIPT_ONLY = frozenset({"hydra", "omegaconf", "mlflow"})
"""`scripts/` でだけ許す依存（実装計画 §11）。"""


def core_modules() -> list[Path]:
    """`boku/` 配下の全 Python モジュール。"""
    return sorted(CORE.rglob("*.py"))


def imported_roots(path: Path) -> set[str]:
    """そのファイルが import しているトップレベルのモジュール名。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 相対import は自パッケージ内
                roots.add("boku")
            elif node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_core_modules_are_found() -> None:
    """走査対象が実在する（空振りしていない）。"""
    modules = core_modules()
    assert len(modules) >= 8, [p.name for p in modules]
    names = {p.name for p in modules}
    assert {"registry.py", "ops.py", "run.py", "fingerprint.py"} <= names


@pytest.mark.parametrize("path", core_modules(), ids=lambda p: str(p.relative_to(ROOT)))
def test_core_module_imports_only_stdlib_and_boku(path: Path) -> None:
    """`boku/` のモジュールが標準ライブラリと `boku` しか import しない。"""
    for root in imported_roots(path):
        assert root == "boku" or root in sys.stdlib_module_names, (
            f"{path.relative_to(ROOT)} が外部ライブラリ {root!r} を import している"
            f"（実装計画 §11 の依存の層）"
        )


def test_core_does_not_import_hydra_or_mlflow() -> None:
    """設定管理と実験管理が意味の権威側に染み出していない。

    上のテストに含まれるが、**最も守りたい境界**なので名指しで固定する。
    """
    for path in core_modules():
        leaked = imported_roots(path) & SCRIPT_ONLY
        assert not leaked, f"{path.relative_to(ROOT)} が {leaked} を import している"


def test_scripts_may_use_hydra_and_mlflow() -> None:
    """`scripts/` は使ってよい（境界が逆向きに厳しすぎないことの確認）。

    ここが空になっていたら、Hydra を使う設計（実装計画 §11）が実装されていない。
    """
    scripts = sorted((ROOT / "scripts").rglob("*.py"))
    assert scripts
    used = set()
    for path in scripts:
        used |= imported_roots(path) & SCRIPT_ONLY
    assert "hydra" in used
    assert "mlflow" in used


def test_no_pydantic_anywhere_in_core() -> None:
    """`boku/` に pydantic を入れない（実装計画 §1）。

    mlflow の推移的依存として仮想環境には存在するので、「入っていない」ではなく
    「使っていない」を確認する。
    """
    for path in core_modules():
        assert "pydantic" not in imported_roots(path), path.relative_to(ROOT)
