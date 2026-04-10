"""Bilibili QR code login for idol-skill.

Usage:
    # Login via QR code (terminal)
    python3 bilibili_auth.py login

    # Check if credential is valid
    python3 bilibili_auth.py check

    # Print saved credential (for debugging)
    python3 bilibili_auth.py show
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

CREDENTIAL_PATH = Path.home() / ".config" / "idol-skill" / "bilibili_credential.json"


def _save_credential(credential_data: dict) -> None:
    """Save credential to disk."""
    CREDENTIAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIAL_PATH.write_text(json.dumps(credential_data, ensure_ascii=False, indent=2))
    CREDENTIAL_PATH.chmod(0o600)
    print(f"Credential saved to {CREDENTIAL_PATH}")


def load_credential():
    """Load saved credential. Returns Credential object or None."""
    from bilibili_api import Credential
    if not CREDENTIAL_PATH.exists():
        return None
    data = json.loads(CREDENTIAL_PATH.read_text())
    return Credential(
        sessdata=data.get("sessdata"),
        bili_jct=data.get("bili_jct"),
        buvid3=data.get("buvid3"),
        dedeuserid=data.get("dedeuserid"),
        ac_time_value=data.get("ac_time_value"),
    )


def login_qrcode() -> None:
    """Login via QR code in terminal."""
    import asyncio
    asyncio.run(_login_qrcode_async())


async def _login_qrcode_async() -> None:
    """Async QR code login implementation."""
    from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

    print("正在生成 B站登录二维码...")
    print("请用 B站 App 扫码登录\n")

    qr_login = QrCodeLogin()
    await qr_login.generate_qrcode()

    # Display QR code in terminal
    print(qr_login.get_qrcode_terminal())

    print("\n等待扫码...")

    # Poll for login result
    for _ in range(60):  # 120 seconds timeout
        time.sleep(2)
        state = await qr_login.check_state()

        if state == QrCodeLoginEvents.DONE:
            cred = qr_login.get_credential()
            credential_data = {
                "sessdata": cred.sessdata or "",
                "bili_jct": cred.bili_jct or "",
                "buvid3": cred.buvid3 or "",
                "dedeuserid": cred.dedeuserid or "",
                "ac_time_value": cred.ac_time_value or "",
            }
            _save_credential(credential_data)
            print("\n✅ 登录成功！")
            return
        elif state == QrCodeLoginEvents.TIMEOUT:
            print("❌ 二维码已过期，请重新运行")
            sys.exit(1)
        elif state == QrCodeLoginEvents.CONF:
            print("  📱 已扫码，请在手机上确认...", end="\r")
        elif state == QrCodeLoginEvents.SCAN:
            pass  # still waiting

    print("❌ 登录超时")
    sys.exit(1)


def login_from_sessdata(sessdata: str) -> None:
    """Login using manually provided SESSDATA."""
    credential_data = {
        "sessdata": sessdata,
        "bili_jct": "",
        "buvid3": "",
        "dedeuserid": "",
        "ac_time_value": "",
    }
    _save_credential(credential_data)
    print("✅ SESSDATA 已保存")


def check_credential() -> bool:
    """Check if saved credential is valid."""
    from bilibili_api import sync as bsync, user
    cred = load_credential()
    if cred is None:
        print("❌ 未登录。运行 `python3 bilibili_auth.py login` 扫码登录")
        return False

    try:
        # Try to get current user info
        my_info = bsync(user.get_self_info(credential=cred))
        name = my_info.get("name", "?")
        print(f"✅ 已登录：{name}")
        return True
    except Exception as e:
        print(f"❌ 凭证已失效：{e}")
        return False


def show_credential() -> None:
    """Print saved credential info (masked)."""
    if not CREDENTIAL_PATH.exists():
        print("No credential saved")
        return
    data = json.loads(CREDENTIAL_PATH.read_text())
    for k, v in data.items():
        if v:
            print(f"  {k}: {v[:8]}...{v[-4:]}" if len(str(v)) > 12 else f"  {k}: {v}")
        else:
            print(f"  {k}: (empty)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "login":
        login_qrcode()
    elif cmd == "sessdata":
        if len(sys.argv) < 3:
            print("Usage: python3 bilibili_auth.py sessdata <YOUR_SESSDATA>")
            sys.exit(1)
        login_from_sessdata(sys.argv[2])
    elif cmd == "check":
        check_credential()
    elif cmd == "show":
        show_credential()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
