"""注册邀请码（测试版收口注册）单元验证。

目标：
1. 邀请码生成格式：VH 前缀 + 8 位随机字符，字母表剔除 0/O/1/I/L 易混淆字符。
2. 规范化容错：大小写不敏感、连字符/空格可省略；展示格式 VH-XXXX-XXXX。
3. 随机性：批量生成不重复（随机空间 31^8，碰撞概率可忽略）。
4. RegisterRequest schema 含 invite_code 字段（默认空串，向后兼容）。

可直接运行：`python -m tests.test_invite_codes`（无需 pytest，亦兼容 pytest）。
DB 相关链路（原子消费/过期/禁用）依赖 MySQL，由部署后冒烟验证覆盖。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import invite_service as inv
from app.schemas.auth import RegisterRequest


def test_random_code_format():
    for _ in range(50):
        code = inv._random_code()
        assert code.startswith(inv._PREFIX)
        body = code[len(inv._PREFIX):]
        assert len(body) == inv._RANDOM_LEN
        for ch in body:
            assert ch in inv._ALPHABET, f"出现字母表外字符: {ch}"


def test_alphabet_excludes_ambiguous_chars():
    for ch in "0O1IL":
        assert ch not in inv._ALPHABET


def test_normalize_tolerates_user_input():
    assert inv.normalize_code("vh-8k2m-9dq4") == "VH8K2M9DQ4"
    assert inv.normalize_code("  VH 8K2M 9DQ4  ") == "VH8K2M9DQ4"
    assert inv.normalize_code("VH8K2M9DQ4") == "VH8K2M9DQ4"
    assert inv.normalize_code("") == ""


def test_format_roundtrip():
    code = inv._random_code()
    displayed = inv.format_code(code)
    assert displayed.count("-") == 2
    assert inv.normalize_code(displayed) == code


def test_batch_generation_unique():
    codes = {inv._random_code() for _ in range(1000)}
    assert len(codes) == 1000


def test_register_request_has_invite_code():
    req = RegisterRequest(
        username="u",
        password="p",
        invite_code="VH-8K2M-9DQ4",
        client_uuid="test-device",
    )
    assert req.invite_code == "VH-8K2M-9DQ4"
    # 缺省为空串：老客户端不传也能反序列化（由服务端逻辑判定是否放行）
    legacy = RegisterRequest(username="u", password="p", client_uuid="test-device")
    assert legacy.invite_code == ""


def _run_all():
    tests = [
        test_random_code_format,
        test_alphabet_excludes_ambiguous_chars,
        test_normalize_tolerates_user_input,
        test_format_roundtrip,
        test_batch_generation_unique,
        test_register_request_has_invite_code,
    ]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\nAll {len(tests)} invite-code tests passed.")


if __name__ == "__main__":
    _run_all()
