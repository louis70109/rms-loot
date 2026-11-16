"""儲存空間檢查：讀取資料所在 volume 的已用比例（見 docs/adr/0001-storage-space-warning.md）。"""

import os

WARN_RATIO = 0.80      # 80% 以上：空間快滿
CRITICAL_RATIO = 0.95  # 95% 以上：空間即將用完


def _usage(path):
    """一次 statvfs，回傳 (已用比例, 總容量 bytes, 已用 bytes)。讀取失敗丟出 OSError。"""
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    if total <= 0:
        return 0.0, 0, 0
    used = total - st.f_bavail * st.f_frsize  # 一般使用者可用以外的部分都算已用
    return used / total, total, used


def disk_usage_ratio(path):
    """path 所在檔案系統的已用比例（0.0 ~ 1.0）。"""
    return _usage(path)[0]


def storage_status(path):
    """回傳 None（空間足夠或無法判斷）、或 {"level", "percent", "used_mb", "total_mb"}。

    無法讀取時直接回傳 None，不讓警告功能影響頁面。
    """
    try:
        ratio, total, used = _usage(path)
    except OSError:
        return None
    if ratio >= CRITICAL_RATIO:
        level = "critical"
    elif ratio >= WARN_RATIO:
        level = "warning"
    else:
        return None
    return {
        "level": level,
        "percent": round(ratio * 100),
        "used_mb": round(used / 1_048_576),
        "total_mb": round(total / 1_048_576),
    }
