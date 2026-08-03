"""R2 hash 排序键收敛验证（方案 B M1）。

目标：
1. project_service._compute_content_hash 与 native_skill_store._compute_dir_hash
   对同一目录树结果 **位级一致**。
2. 二者均与 M0 契约 §7.3 冻结伪代码（按相对 POSIX 路径 UTF-8 字节序排序）一致。
3. 同一内容在「不同根路径 / 含中文名 / 触发分隔符排序分歧」场景下 hash 稳定。

可直接运行：`python -m tests.test_hash_convergence`（无需 pytest，亦兼容 pytest）。
"""

import hashlib
import sys
import tempfile
from pathlib import Path

# 允许 `python tests/test_hash_convergence.py` 直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.project_service import _compute_content_hash
from app.services.native_skill_store import _compute_dir_hash


def _reference_hash(root_path: str) -> str:
    """M0 §7.3 冻结伪代码的独立参考实现（不复用生产代码）。"""
    root = Path(root_path)
    if not root.exists():
        return ""
    rels = sorted(
        (p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()),
        key=lambda s: s.encode("utf-8"),
    )
    if not rels:
        return ""
    h = hashlib.sha256()
    for rel in rels:
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update((root / rel).read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _build_tree(base: Path) -> None:
    """构造覆盖边界场景的目录树。

    关键边界：`ref/z`（目录内文件，相对路径 'ref/z'）与同级 `refA.md`
    （相对路径 'refA.md'）—— POSIX 字节序下 '/'(0x2F) < 'A'(0x41)，
    Windows 原生 Path 排序用 '\\'(0x5C) > 'A'，顺序相反。收敛后必须按 POSIX。
    """
    base.mkdir(parents=True, exist_ok=True)
    (base / "SKILL.md").write_text("---\nname: demo\n---\nbody\n", encoding="utf-8")
    (base / "refA.md").write_text("refA-content", encoding="utf-8")
    (base / "ref").mkdir(exist_ok=True)
    (base / "ref" / "z").write_text("z-content", encoding="utf-8")
    # 中文目录与文件名
    (base / "资料").mkdir(exist_ok=True)
    (base / "资料" / "说明.md").write_text("中文内容\n", encoding="utf-8")
    # 大小写排序边界；避免仅大小写不同的文件名在 Windows 上发生覆盖
    (base / "Aa.txt").write_text("Aa", encoding="utf-8")
    (base / "aB.txt").write_text("aB", encoding="utf-8")
    # 二进制资源
    (base / "assets").mkdir(exist_ok=True)
    (base / "assets" / "icon.png").write_bytes(bytes(range(256)) * 4)


def test_two_functions_bit_identical():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "skill"
        _build_tree(root)
        h_project = _compute_content_hash(str(root))
        h_native = _compute_dir_hash(root)
        assert h_project == h_native, (
            f"两处算法不一致: project={h_project} native={h_native}"
        )
        assert h_project == _reference_hash(str(root)), (
            "与 M0 §7.3 冻结伪代码不一致"
        )
        assert len(h_project) == 64


def test_stable_across_different_roots():
    """同一内容在不同绝对根路径下 hash 必须相同（去平台/分隔符相关性）。"""
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        r1 = Path(d1) / "a" / "deep" / "skill"
        r2 = Path(d2) / "x" / "skill"
        _build_tree(r1)
        _build_tree(r2)
        assert _compute_content_hash(str(r1)) == _compute_content_hash(str(r2))
        assert _compute_dir_hash(r1) == _compute_dir_hash(r2)


def test_empty_and_missing():
    with tempfile.TemporaryDirectory() as d:
        empty = Path(d) / "empty"
        empty.mkdir()
        assert _compute_content_hash(str(empty)) == ""
        assert _compute_dir_hash(empty) == ""
        missing = Path(d) / "nope"
        assert _compute_content_hash(str(missing)) == ""
        assert _compute_dir_hash(missing) == ""


def test_separator_edge_case_ordering():
    """显式验证 ref/z 与 refA.md 按 POSIX 字节序排列，结果与参考实现一致。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "edge"
        root.mkdir(parents=True)
        (root / "refA.md").write_text("A", encoding="utf-8")
        (root / "ref").mkdir()
        (root / "ref" / "z").write_text("Z", encoding="utf-8")
        # 参考实现强制 POSIX 字节序；生产代码必须一致
        assert _compute_content_hash(str(root)) == _reference_hash(str(root))
        assert _compute_dir_hash(root) == _reference_hash(str(root))


def _run_all():
    tests = [
        test_two_functions_bit_identical,
        test_stable_across_different_roots,
        test_empty_and_missing,
        test_separator_edge_case_ordering,
    ]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\nAll {len(tests)} hash-convergence tests passed.")


if __name__ == "__main__":
    _run_all()
