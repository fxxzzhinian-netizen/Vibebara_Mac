"""ObjectStore — 平台 Skill 持久化的可插拔对象存储抽象。

后端不再直接用 `Path` 操作本地 store 目录，而是面向「对象键 / 前缀」读写：

- `STORAGE_BACKEND=local`（开发默认）：`LocalObjectStore`，键映射到 `COWORK_DATA_DIR`
  下的文件系统（`skills/personal/{owner_id}/{id}/...`、`skill_versions/...`）。
- `STORAGE_BACKEND=cos`（生产）：`CosObjectStore`，用 cos-python-sdk-v5 读写腾讯云 COS。

键约定（逻辑键，不含 COS_PREFIX）：
  skills/personal/{owner_id}/{id}/skill.config.yaml | SKILL.md | scripts/** | references/** | assets/** | LICENSE
  skills/team/{id}/...
  skill_versions/{skill_id}/{version_id}/scripts|references|assets/**

哈希口径见 docs/design/cos-storage.md §5：与本地代理 / 旧 `_compute_dir_hash` 位级一致，
仅数据来源从「磁盘 rglob」改为「对象列举」。
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _norm_prefix(prefix: str) -> str:
    """规整目录前缀：统一正斜杠、去首尾斜杠后补一个尾斜杠（空前缀返回空）。"""
    p = (prefix or "").replace("\\", "/").strip("/")
    return (p + "/") if p else ""


class ObjectStore:
    """对象存储接口（同步实现，与现有阻塞式 IO 调用风格一致）。"""

    def put_text(self, key: str, text: str) -> None:
        self.put_bytes(key, (text or "").encode("utf-8"))

    def put_bytes(self, key: str, data: bytes) -> None:  # pragma: no cover - 抽象
        raise NotImplementedError

    def get_text(self, key: str) -> Optional[str]:
        data = self.get_bytes(key)
        return None if data is None else data.decode("utf-8")

    def get_bytes(self, key: str) -> Optional[bytes]:  # pragma: no cover - 抽象
        raise NotImplementedError

    def exists(self, key: str) -> bool:  # pragma: no cover - 抽象
        raise NotImplementedError

    def list(self, prefix: str) -> List[str]:  # pragma: no cover - 抽象
        """返回逻辑键以 prefix 起始的全部对象键（递归，原始前缀匹配）。"""
        raise NotImplementedError

    def list_dirs(self, prefix: str) -> List[str]:  # pragma: no cover - 抽象
        """返回 prefix 下的「直接子目录名」（用于枚举 skill id）。"""
        raise NotImplementedError

    def delete_prefix(self, prefix: str) -> None:  # pragma: no cover - 抽象
        raise NotImplementedError

    def copy_prefix(self, src_prefix: str, dst_prefix: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def compute_prefix_hash(self, prefix: str) -> str:
        """对前缀下对象按相对前缀 POSIX 路径的 UTF-8 字节序排序后逐个喂 sha256。

        与 docs/design/cos-storage.md §5 / 本地代理算法位级一致。
        """
        base = _norm_prefix(prefix)
        keys = self.list(base)
        if not keys:
            return ""
        # rel = 去掉 base 前缀后的相对路径；按 UTF-8 字节序排序
        rels = sorted(
            (k[len(base):] for k in keys if len(k) > len(base)),
            key=lambda r: r.encode("utf-8"),
        )
        if not rels:
            return ""
        digest = hashlib.sha256()
        for rel in rels:
            data = self.get_bytes(base + rel)
            if data is None:
                continue
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(data)
            digest.update(b"\0")
        return digest.hexdigest()


# =========================================================================
# 本地文件系统实现（开发默认）
# =========================================================================


class LocalObjectStore(ObjectStore):
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _safe_key(self, key: str, *, allow_root: bool = False) -> str:
        """把逻辑对象键约束在存储根内，并阻断绝对路径、父级与符号链接逃逸。"""
        raw = (key or "").replace("\\", "/")
        if "\x00" in raw:
            raise ValueError("对象键包含非法空字节")
        if raw.startswith("/") or (
            len(raw) >= 2 and raw[0].isalpha() and raw[1] == ":"
        ):
            raise ValueError(f"对象键必须是相对路径: {key!r}")
        rel = raw.strip("/")
        if not rel:
            if allow_root:
                return ""
            raise ValueError("对象键不能为空")
        parts = rel.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"非法对象键: {key!r}")

        candidate = (self._root / Path(*parts)).resolve()
        try:
            candidate.relative_to(self._root)
        except (ValueError, OSError):
            raise ValueError(f"对象键越出存储根目录: {key!r}") from None
        return "/".join(parts)

    def _path(self, key: str, *, allow_root: bool = False) -> Path:
        rel = self._safe_key(key, allow_root=allow_root)
        return self._root if not rel else self._root.joinpath(*rel.split("/"))

    def put_bytes(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_bytes(self, key: str) -> Optional[bytes]:
        p = self._path(key)
        if not p.is_file():
            return None
        return p.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list(self, prefix: str) -> List[str]:
        norm = self._safe_key(prefix, allow_root=True)
        # 以目录形式列举：取 norm 去尾斜杠对应的目录，递归列出文件，再用原始前缀过滤。
        dir_part = norm.rstrip("/")
        base_dir = self._path(dir_part, allow_root=True)
        if not base_dir.exists():
            # 也可能 norm 本身就是某文件键
            if self._path(norm, allow_root=True).is_file():
                return [norm]
            return []
        out: List[str] = []
        if base_dir.is_dir():
            for f in base_dir.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(self._root).as_posix()
                    if rel.startswith(norm):
                        out.append(rel)
        elif base_dir.is_file():
            out.append(base_dir.relative_to(self._root).as_posix())
        return out

    def list_dirs(self, prefix: str) -> List[str]:
        base = _norm_prefix(prefix)
        base_dir = self._path(base, allow_root=True)
        if not base_dir.is_dir():
            return []
        return sorted(
            d.name for d in base_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    def delete_prefix(self, prefix: str) -> None:
        # 删除根前缀会清空整个对象仓库；任何调用方都必须提供明确的非空命名空间。
        target = self._path(prefix)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.is_file():
            try:
                target.unlink()
            except OSError:
                pass

    def copy_prefix(self, src_prefix: str, dst_prefix: str) -> None:
        src_base = _norm_prefix(src_prefix)
        dst_base = _norm_prefix(dst_prefix)
        self._safe_key(src_base, allow_root=True)
        self._safe_key(dst_base, allow_root=True)
        for key in self.list(src_base):
            rel = key[len(src_base):]
            data = self.get_bytes(key)
            if data is not None:
                self.put_bytes(dst_base + rel, data)


# =========================================================================
# 腾讯云 COS 实现（生产）
# =========================================================================


class CosObjectStore(ObjectStore):
    def __init__(
        self, bucket: str, region: str, secret_id: str, secret_key: str, prefix: str = ""
    ) -> None:
        # 延迟导入：仅 STORAGE_BACKEND=cos 时才需要该依赖，避免本地/测试环境强依赖。
        from qcloud_cos import CosConfig, CosS3Client

        if not (bucket and region and secret_id and secret_key):
            raise ValueError(
                "STORAGE_BACKEND=cos 需配置 COS_BUCKET/COS_REGION/COS_SECRET_ID/COS_SECRET_KEY"
            )
        self._bucket = bucket
        self._region = region
        self._prefix = _norm_prefix(prefix)  # 桶内统一前缀（可空）
        self._client = CosS3Client(
            CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
        )

    def _full(self, key: str) -> str:
        return self._prefix + (key or "").replace("\\", "/").lstrip("/")

    def _strip(self, full_key: str) -> str:
        return full_key[len(self._prefix):] if self._prefix else full_key

    def put_bytes(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Body=data, Key=self._full(key))

    def get_bytes(self, key: str) -> Optional[bytes]:
        from qcloud_cos.cos_exception import CosServiceError

        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=self._full(key))
            return resp["Body"].get_raw_stream().read()
        except CosServiceError as e:
            if e.get_status_code() == 404:
                return None
            raise

    def exists(self, key: str) -> bool:
        return bool(self._client.object_exists(Bucket=self._bucket, Key=self._full(key)))

    def _list_full(self, full_prefix: str, delimiter: str = "") -> dict:
        """分页列举，返回 {'keys': [...], 'dirs': [...]}（full key，未去 self._prefix）。"""
        keys: List[str] = []
        dirs: List[str] = []
        marker = ""
        while True:
            resp = self._client.list_objects(
                Bucket=self._bucket, Prefix=full_prefix, Marker=marker,
                Delimiter=delimiter, MaxKeys=1000,
            )
            for c in resp.get("Contents", []) or []:
                keys.append(c["Key"])
            for cp in resp.get("CommonPrefixes", []) or []:
                dirs.append(cp["Prefix"])
            if resp.get("IsTruncated") == "true":
                marker = resp.get("NextMarker", "")
                if not marker:
                    break
            else:
                break
        return {"keys": keys, "dirs": dirs}

    def list(self, prefix: str) -> List[str]:
        full_prefix = self._full(prefix)
        res = self._list_full(full_prefix)
        return [self._strip(k) for k in res["keys"]]

    def list_dirs(self, prefix: str) -> List[str]:
        base = _norm_prefix(prefix)
        full_prefix = self._full(base)
        res = self._list_full(full_prefix, delimiter="/")
        names: List[str] = []
        for d in res["dirs"]:
            logical = self._strip(d)  # e.g. skills/personal/{owner_id}/
            name = logical[len(base):].rstrip("/")
            if name and not name.startswith("."):
                names.append(name)
        return sorted(names)

    def delete_prefix(self, prefix: str) -> None:
        if not _norm_prefix(prefix):
            raise ValueError("拒绝删除空对象前缀")
        keys = self.list(prefix)
        if not keys:
            return
        # 批量删除（每批 ≤1000）
        for i in range(0, len(keys), 1000):
            batch = keys[i:i + 1000]
            self._client.delete_objects(
                Bucket=self._bucket,
                Delete={"Object": [{"Key": self._full(k)} for k in batch]},
            )

    def copy_prefix(self, src_prefix: str, dst_prefix: str) -> None:
        src_base = _norm_prefix(src_prefix)
        dst_base = _norm_prefix(dst_prefix)
        for key in self.list(src_base):
            rel = key[len(src_base):]
            self._client.copy_object(
                Bucket=self._bucket,
                Key=self._full(dst_base + rel),
                CopySource={
                    "Bucket": self._bucket,
                    "Region": self._region,
                    "Key": self._full(key),
                },
            )


# =========================================================================
# 工厂（单例）
# =========================================================================

_store: Optional[ObjectStore] = None


def get_object_store() -> ObjectStore:
    global _store
    if _store is not None:
        return _store
    if settings.STORAGE_BACKEND == "cos":
        _store = CosObjectStore(
            bucket=settings.COS_BUCKET,
            region=settings.COS_REGION,
            secret_id=settings.COS_SECRET_ID,
            secret_key=settings.COS_SECRET_KEY,
            prefix=settings.COS_PREFIX,
        )
        logger.info(
            f"[ObjectStore] 使用 COS 后端 bucket={settings.COS_BUCKET} region={settings.COS_REGION}"
        )
    else:
        root = settings.COWORK_DATA_DIR or str(
            Path(os.getcwd()) / "data"
        )
        _store = LocalObjectStore(root)
        logger.info(f"[ObjectStore] 使用本地文件系统后端 root={root}")
    return _store
