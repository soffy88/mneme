"""密码哈希与校验（可选密码登录）。

为什么直接用 bcrypt 而不是 passlib：
requirements 里写的是 `passlib[bcrypt]>=1.7`，但 passlib 1.7.4（2020 年最后
一版，已停止维护）与 bcrypt 5.x 不兼容——passlib 的 bcrypt handler 会用一个
>72 字节的探针密码调用 `bcrypt.hashpw` 做后端探测，而 bcrypt 5.0 起该调用改为
抛错而非截断，于是 `CryptContext` 初始化即崩。这里直接依赖 bcrypt 参考实现。

好处之一：bcrypt 5 对 >72 字节输入**显式抛错**而不是静默截断，所以我们不必
自己实现截断——直接把它当作校验规则拒掉。（静默截断会把两个不同密码折叠成
同一个哈希，`a"*72 + "b"` 与 `"a"*72` 就无法区分。）

哈希绝不入日志、绝不出现在任何响应体。
"""

from __future__ import annotations

import bcrypt

# bcrypt 的输入上限。超过则 bcrypt 抛错；我们先拦下来给出可读的 422。
MAX_PASSWORD_BYTES = 72
# 与 _verify_attempts/_lockout 的语义对齐：太短的密码没有抗爆破价值。
MIN_PASSWORD_CHARS = 8
# 12 轮 = OWASP 2024 对 bcrypt 的推荐下限。代价是每次校验约 250ms，
# 这是有意的：它让离线爆破的每条 hash 都变贵。
ROUNDS = 12


class PasswordPolicyError(ValueError):
    """密码不满足策略（长度/字节数）。调用方应转 422。"""


def validate_password(password: str) -> None:
    """校验密码是否可哈希。不合格抛 PasswordPolicyError。"""
    if not isinstance(password, str) or not password:
        raise PasswordPolicyError("密码不能为空")
    if len(password) < MIN_PASSWORD_CHARS:
        raise PasswordPolicyError(f"密码至少 {MIN_PASSWORD_CHARS} 位")
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        # 中文/emoji 很容易超。注意是按**字节**不是字符数。
        raise PasswordPolicyError(f"密码过长（最多 {MAX_PASSWORD_BYTES} 字节）")


def hash_password(password: str) -> str:
    """生成 bcrypt 哈希（$2b$ 前缀，60 字符）。调用前须先过 validate_password。"""
    validate_password(password)
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=ROUNDS)
    ).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    """校验密码。password_hash 为 None（未设密码）恒返回 False。

    对未设密码的账号绝不能返回 True——那会让任何空密码登录成功。
    """
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        # 库里存了脏数据/未知算法前缀，当作不匹配而不是 500。
        return False


# 供登录路径做时序均衡：账号不存在时也跑一次等价的 bcrypt 校验，
# 否则"用户不存在"会比"密码错误"快一个数量级，可据此枚举已注册邮箱。
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer-not-a-real-password", bcrypt.gensalt(rounds=ROUNDS)).decode("ascii")


def burn_password_verification(password: str) -> None:
    """账号不存在时调用，抹平与真实校验的时间差。"""
    bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH.encode("ascii"))
