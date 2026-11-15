"""运行时配置读取。

配置只从环境变量读取，统一使用 ``PRINTCARE_`` 前缀。仓库仅提交
``.env.example`` 占位示例；真实密钥通过本机 ``.env`` 或部署环境的秘密配置注入，
不写入仓库、日志或错误消息。
"""

from __future__ import annotations

import os
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

ENV_PREFIX = "PRINTCARE_"
ENVIRONMENTS = frozenset({"local", "test", "staging", "production"})
LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})
DEFAULT_DATA_DIR = Path("runtime")


class ConfigError(ValueError):
    """配置取值不合法。

    消息只包含变量名和允许取值，不回显变量值，避免把密钥或连接串写进日志。
    """


@dataclass(frozen=True)
class Settings:
    """一次运行使用的配置。"""

    environment: str
    log_level: str
    data_dir: Path
    database_path: Path
    model_api_key: str | None = None
    model_api_key_file: Path | None = None
    model_base_url: str | None = None
    model_name: str = "deepseek-flash"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """从环境变量构造配置；``environ`` 便于测试传入固定字典。"""
        source = os.environ if environ is None else environ
        environment = _choice(source, "ENVIRONMENT", ENVIRONMENTS, "local", lower=True)
        log_level = _choice(source, "LOG_LEVEL", LOG_LEVELS, "INFO", upper=True)
        data_dir = Path(_value(source, "DATA_DIR") or DEFAULT_DATA_DIR)
        database_path = _value(source, "DATABASE_PATH")
        key_file = _value(source, "MODEL_API_KEY_FILE")
        return cls(
            environment=environment,
            log_level=log_level,
            data_dir=data_dir,
            database_path=Path(database_path) if database_path else data_dir / "printcare.sqlite3",
            model_api_key=_value(source, "MODEL_API_KEY") or None,
            model_api_key_file=Path(key_file) if key_file else None,
            model_base_url=_value(source, "MODEL_BASE_URL") or None,
            model_name=_value(source, "MODEL_NAME") or "deepseek-flash",
        )

    def describe(self) -> dict[str, object]:
        """返回可安全写入日志的配置摘要，不包含密钥值。"""
        return {
            "environment": self.environment,
            "log_level": self.log_level,
            "data_dir": str(self.data_dir),
            "database_path": str(self.database_path),
            "model_api_key_present": bool(self.model_api_key),
            "model_api_key_file": str(self.model_api_key_file) if self.model_api_key_file else None,
            "model_base_url": self.model_base_url,
            "model_name": self.model_name,
        }


def _value(environ: Mapping[str, str], name: str) -> str:
    return environ.get(ENV_PREFIX + name, "").strip()


def resolve_model_api_key(
    settings: Settings,
    default_file: Path | None = None,
) -> str:
    """Resolve the API key from the environment, an explicit file, or a local default.

    The key is returned only in memory and never written to logs.
    """
    if settings.model_api_key:
        return settings.model_api_key
    candidates = [settings.model_api_key_file, default_file or Path("runtime/model_key.txt")]
    for candidate in candidates:
        if candidate is None:
            continue
        path = Path(candidate)
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    raise ConfigError(
        "未配置模型密钥：设置 PRINTCARE_MODEL_API_KEY，或把 Key 写入 runtime/model_key.txt"
    )


def _choice(
    environ: Mapping[str, str],
    name: str,
    allowed: Collection[str],
    default: str,
    *,
    lower: bool = False,
    upper: bool = False,
) -> str:
    raw = _value(environ, name)
    if not raw:
        return default
    if lower:
        raw = raw.lower()
    elif upper:
        raw = raw.upper()
    if raw not in allowed:
        options = ", ".join(sorted(allowed))
        raise ConfigError(f"{ENV_PREFIX + name} 取值不合法，允许值：{options}")
    return raw
