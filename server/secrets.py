"""仅为 Python 服务进程加载 DeepSeek 凭据，绝不将密钥暴露给前端。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env.local"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


@dataclass(frozen=True)
class DeepSeekSettings:
    # 故意设置 repr=False：打印或调试配置对象时不能泄露 Key。
    api_key: str = field(repr=False)
    base_url: str
    model: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    @property
    def mode(self) -> str:
        return "deepseek" if self.configured else "mock"


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise RuntimeError("无法读取服务端密钥配置文件") from exc
    for line in lines:
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        if item.startswith("export "):
            item = item[7:].strip()
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "X100_MYSQL_ENABLED", "X100_MYSQL_HOST", "X100_MYSQL_PORT", "X100_MYSQL_USER", "X100_MYSQL_PASSWORD", "X100_MYSQL_DATABASE"):
            values[name] = value
    return values


def load_deepseek_settings(
    env: Optional[Mapping[str, str]] = None,
    env_file: Path = ENV_FILE,
) -> DeepSeekSettings:
    # 优先级为进程环境变量 > 本地 .env.local > 非敏感默认值。
    process_env = os.environ if env is None else env
    file_values = _parse_env_file(env_file)

    def resolve(name: str, default: str) -> str:
        if name in process_env:
            return str(process_env[name]).strip()
        if name in file_values:
            return file_values[name].strip()
        return default

    settings = DeepSeekSettings(
        api_key=resolve("DEEPSEEK_API_KEY", ""),
        base_url=resolve("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        model=resolve("DEEPSEEK_MODEL", DEFAULT_MODEL),
    )
    if settings.base_url:
        parsed = urlsplit(settings.base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("DeepSeek Base URL 配置无效")
        if parsed.scheme != "https" and not local_http:
            raise ValueError("DeepSeek Base URL 必须使用 HTTPS")
    if settings.model and (len(settings.model) > 128 or any(char.isspace() for char in settings.model)):
        raise ValueError("DeepSeek 模型标识配置无效")
    return settings
