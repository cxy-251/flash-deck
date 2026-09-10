# -*- coding: utf-8 -*-
"""
mega_service.py - Omni Deck MEGA 网盘原生集成服务 (基于 mega-cmd 原生引擎)

职责架构：
1. 原生服务守护：管理与连接 /home/deck/Applications/mega-cmd/bin/mega-cmd-server
2. 账户凭证管理：支持账号密码登录、2FA验证、状态查询与安全登出
3. 网盘资源浏览：基于 mega-ls 实现云端文件树解析、面包屑路径与属性提取
4. 极速异步下载：调度 mega-get 后台下载到 Deck 存储 (/home/deck/Downloads 或 SD卡)
5. 传输任务监控：解析 mega-transfers 实时追踪下载速率与进度
6. 云端回收站与同步：支持文件移入回收站、查看与清空回收站、mega-reload 快速同步
"""

import os
import sys
import re
import json
import time
import subprocess
import threading
from typing import Dict, List, Any, Optional

MEGA_APP_DIR = "/home/deck/Applications/mega-cmd"
MEGA_BIN_DIR = os.path.join(MEGA_APP_DIR, "bin")
MEGA_LIB_DIR = os.path.join(MEGA_APP_DIR, "lib")
MEGA_EXEC = os.path.join(MEGA_BIN_DIR, "mega-exec")
MEGA_SERVER = os.path.join(MEGA_BIN_DIR, "mega-cmd-server")

DEFAULT_DOWNLOAD_DIR = "/home/deck/Downloads"
SD_CARD_DOWNLOAD_DIR = "/run/media/deck/FUCKDECK"

_lock = threading.Lock()

def get_mega_env() -> Dict[str, str]:
    """构造携带 mega-cmd 二进制与运行依赖库的环境变量"""
    env = os.environ.copy()
    current_path = env.get("PATH", "")
    env["PATH"] = f"{MEGA_BIN_DIR}:{current_path}"
    
    current_ld = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = f"{MEGA_LIB_DIR}:{current_ld}"
    return env

def ensure_server_running() -> bool:
    """确保 mega-cmd-server 后台服务正常存活并在运行"""
    socket_path = os.path.expanduser("~/.megaCmd/megacmd.socket")
    try:
        res = subprocess.run(["pgrep", "-f", "mega-cmd-server"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            return True
    except Exception:
        pass

    try:
        env = get_mega_env()
        subprocess.Popen([MEGA_SERVER, "--do-not-log-to-stdout"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(30):
            if os.path.exists(socket_path):
                time.sleep(0.1)
                return True
            time.sleep(0.1)
    except Exception as e:
        print(f"[MEGA] Failed to start mega-cmd-server: {e}")
    return os.path.exists(socket_path)

def run_mega_command(args: List[str], timeout: int = 35) -> Dict[str, Any]:
    """
    以非交互方式执行 mega-cmd 子命令并返回统一结果
    """
    ensure_server_running()
    env = get_mega_env()
    
    cmd = [MEGA_EXEC] + args
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "success": proc.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "Command timed out after {}s".format(timeout),
            "success": False
        }
    except Exception as e:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "success": False
        }

def format_bytes(b: int) -> str:
    """将字节大小转换为人类可读的字符串 (B, KB, MB, GB, TB)"""
    if b is None or b < 0:
        return "--"
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    elif b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    elif b < 1024 * 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024 * 1024):.2f} GB"
    else:
        return f"{b / (1024 * 1024 * 1024 * 1024):.2f} TB"

def get_mega_status() -> Dict[str, Any]:
    """
    查询当前 MEGA 服务的运行状态、登录账号与云端容量
    """
    ensure_server_running()
    whoami_res = run_mega_command(["whoami"])
    
    if whoami_res["returncode"] != 0 or "Not logged in" in whoami_res["stderr"] or "Not logged in" in whoami_res["stdout"]:
        return {
            "server_running": True,
            "logged_in": False,
            "email": None,
            "storage": None,
            "error": None
        }

    email = None
    stdout = whoami_res["stdout"]
    m = re.search(r"Account e-mail:\s*([^\s\n]+)", stdout)
    if m:
        email = m.group(1).strip()
    elif "@" in stdout:
        for part in stdout.split():
            if "@" in part:
                email = part.strip()
                break

    df_res = run_mega_command(["df", "-h"])
    storage_info = {
        "used_str": "--",
        "total_str": "--",
        "percent": 0.0,
        "raw": df_res["stdout"]
    }
    
    if df_res["success"]:
        lines = df_res["stdout"].splitlines()
        for line in lines:
            line_lower = line.lower()
            if "total storage" in line_lower:
                storage_info["total_str"] = line.split(":")[-1].strip()
            elif "used storage" in line_lower:
                storage_info["used_str"] = line.split(":")[-1].strip()

    quota_info = get_quota_status(force_probe=True)

    return {
        "server_running": True,
        "logged_in": True,
        "email": email,
        "storage": storage_info,
        "quota": quota_info,
        "error": None
    }

def mega_login(email: str, password: str, auth_code: Optional[str] = None) -> Dict[str, Any]:
    """
    登录 MEGA 账户
    """
    if not email or not password:
        return {"success": False, "error": "邮箱和密码不能为空"}

    args = ["login", email, password]
    if auth_code:
        args.insert(1, f"--auth-code={auth_code.strip()}")

    res = run_mega_command(args, timeout=30)
    if res["success"]:
        return {"success": True, "message": "登录成功", "status": get_mega_status()}
    
    err = res["stderr"] or res["stdout"]
    if "invalid email or password" in err.lower():
        return {"success": False, "error": "账号或密码错误，请检查输入"}
    elif "mfa" in err.lower() or "auth code" in err.lower() or "two-factor" in err.lower():
        return {"success": False, "mfa_required": True, "error": "该账户开启了双重身份验证 (2FA)，请输入验证码"}
    
    return {"success": False, "error": f"登录失败: {err}"}

def mega_logout() -> Dict[str, Any]:
    """
    安全退出 MEGA 账户
    """
    res = run_mega_command(["logout"])
    return {
        "success": res["success"],
        "message": "已安全退出当前 MEGA 账户" if res["success"] else res["stderr"]
    }

def mega_reload() -> Dict[str, Any]:
    """
    执行 mega-reload 同步云端最新变更 (如浏览器刚保存的文件)
    """
    res = run_mega_command(["reload"], timeout=20)
    return {
        "success": res["success"],
        "message": "云端索引已刷新同步完成" if res["success"] else res["stderr"]
    }

def list_mega_files(remote_path: str = "/") -> Dict[str, Any]:
    """
    列出指定云端目录下的所有文件与子目录
    """
    norm_path = remote_path.strip()
    if not norm_path:
        norm_path = "/"
    if not norm_path.startswith("/"):
        norm_path = "/" + norm_path

    res = run_mega_command(["ls", "-l", "--time-format=ISO6081_WITH_TIME", norm_path], timeout=25)
    if not res["success"]:
        return {
            "success": False,
            "path": norm_path,
            "items": [],
            "error": res["stderr"] or res["stdout"]
        }

    items = []
    lines = res["stdout"].splitlines()
    for line in lines:
        line_clean = line.strip()
        if not line_clean or line_clean.startswith("Total storage:") or line_clean.startswith("FLAGS"):
            continue
        
        parts = line_clean.split(None, 4)
        if len(parts) >= 5:
            flags = parts[0]
            vers = parts[1]
            size_raw = parts[2]
            date_str = parts[3]
            name = parts[4]

            is_dir = flags.startswith('d') or flags.startswith('r') or flags.startswith('b')
            is_rubbish = flags.startswith('b')
            
            size_int = 0
            try:
                if size_raw != '-':
                    size_int = int(size_raw)
            except Exception:
                pass

            item_path = norm_path.rstrip('/') + '/' + name if norm_path != '/' else '/' + name

            items.append({
                "name": name,
                "path": item_path,
                "is_dir": is_dir,
                "is_rubbish": is_rubbish,
                "size": size_int,
                "size_str": format_bytes(size_int) if not is_dir else "--",
                "mtime": date_str,
                "flags": flags
            })
        elif len(parts) == 1:
            items.append({
                "name": parts[0],
                "path": norm_path.rstrip('/') + '/' + parts[0],
                "is_dir": False,
                "size": 0,
                "size_str": "--",
                "mtime": "--",
                "flags": "----"
            })

    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

    return {
        "success": True,
        "path": norm_path,
        "items": items,
        "total": len(items),
        "error": None
    }

_quota_cache = {
    "last_check": 0.0,
    "exceeded": False,
    "remaining_seconds": 0,
    "reset_timestamp": 0.0,
    "wait_desc": None,
    "reset_time_clock": None
}

def get_quota_status(force_probe: bool = False) -> Dict[str, Any]:
    """
    获取 MEGA 带宽配额状态及精确解除倒计时
    """
    global _quota_cache
    now = time.time()

    # 如果已有超额缓存且处于倒计时内，未强制探测时直接基于时间差实时计算
    if not force_probe and _quota_cache["exceeded"] and now < _quota_cache["reset_timestamp"]:
        remaining_sec = max(0, int(_quota_cache["reset_timestamp"] - now))
        h = remaining_sec // 3600
        m = (remaining_sec % 3600) // 60
        clock_str = time.strftime("%H:%M", time.localtime(_quota_cache["reset_timestamp"]))
        wait_desc = f"{h}小时{m}分钟" if h > 0 else f"{m}分钟"
        return {
            "exceeded": True,
            "remaining_seconds": remaining_sec,
            "wait_time": wait_desc,
            "reset_time_clock": clock_str,
            "desc": f"配额超限，预计于 {clock_str} 解除 (还需 {wait_desc})"
        }

    # 检查配额状态（基于真实传输状态或限额倒计时缓存，绝不发起虚假文件下载）
    if _quota_cache["exceeded"]:
        if now < _quota_cache["reset_timestamp"]:
            remaining_sec = max(0, int(_quota_cache["reset_timestamp"] - now))
            h = remaining_sec // 3600
            m = (remaining_sec % 3600) // 60
            clock_str = time.strftime("%H:%M", time.localtime(_quota_cache["reset_timestamp"]))
            wait_desc = f"{h}小时{m}分钟" if h > 0 else f"{m}分钟"
            return {
                "exceeded": True,
                "remaining_seconds": remaining_sec,
                "wait_time": wait_desc,
                "reset_time_clock": clock_str,
                "desc": f"配额超限，预计于 {clock_str} 解除 (还需 {wait_desc})"
            }
        else:
            _quota_cache["exceeded"] = False

    # 配额充足或正常可用
    _quota_cache = {
        "last_check": now,
        "exceeded": False,
        "remaining_seconds": 0,
        "reset_timestamp": 0.0,
        "wait_desc": None,
        "reset_time_clock": None
    }
    return {
        "exceeded": False,
        "remaining_seconds": 0,
        "wait_time": None,
        "reset_time_clock": None,
        "desc": "正常可用 (充足)"
    }


def extract_quota_wait_time() -> Optional[str]:
    """兼容旧接口：返回剩余等待时间字符串"""
    info = get_quota_status(force_probe=False)
    return info["wait_time"] if info["exceeded"] else None

def start_download(source_path_or_link: str, target_location: str = "downloads") -> Dict[str, Any]:
    """
    发起后台异步下载：一律保存至 /home/deck/Downloads
    """
    src = source_path_or_link.strip()
    if not src:
        return {"success": False, "error": "下载路径或公开链接不能为空"}

    os.makedirs(DEFAULT_DOWNLOAD_DIR, exist_ok=True)
    # 锁定 MEGA-CMD 本地工作路径为 Downloads 目录
    run_mega_command(["lcd", DEFAULT_DOWNLOAD_DIR], timeout=5)

    args = ["get", "-q", "-m", "--ignore-quota-warn", src]
    # 关键防重名处理：
    # 仅当确定为网盘内部单文件时，显式拼接具体目标文件名 (/home/deck/Downloads/filename)；
    # 若为公开分享直链 (http...) 或目录，绝对不追加 /home/deck/Downloads 参数，
    # 而是交由 mega-cmd 依据 lcd 自动写入，杜绝将 Downloads 目录误当重名文件并生成 "Downloads (1)" 的问题。
    if not src.startswith("http") and not src.endswith('/'):
        fname = os.path.basename(src.rstrip('/'))
        if fname:
            args.append(os.path.join(DEFAULT_DOWNLOAD_DIR, fname))

    # 获取当前配额状态 (非强制探测)
    quota_info = get_quota_status(force_probe=False)
    quota_wait = quota_info["wait_time"] if quota_info["exceeded"] else None

    res = run_mega_command(args, timeout=30)
    
    if res["success"]:
        msg = f"任务已加入后台下载队列，将保存至 {DEFAULT_DOWNLOAD_DIR}"
        if quota_wait:
            msg += f"（⚠️ 当前触发 MEGA 免费流量限额，预计需等待 {quota_wait} 恢复下载）"
        return {
            "success": True,
            "message": msg,
            "dest_dir": DEFAULT_DOWNLOAD_DIR,
            "quota_exceeded": bool(quota_wait),
            "wait_time": quota_wait,
            "quota": quota_info
        }
    else:
        err_msg = res["stderr"] or res["stdout"] or "添加到下载队列失败"
        if "bandwidth quota" in err_msg.lower() or "try again in" in err_msg.lower() or "overquota" in err_msg.lower():
            m = re.search(r"try again in (\d+)\s*(?:seconds|s)?", err_msg, re.IGNORECASE)
            wait_sec = int(m.group(1)) if m else 7200
            now = time.time()
            reset_ts = now + wait_sec
            h = wait_sec // 3600
            m_min = (wait_sec % 3600) // 60
            clock_str = time.strftime("%H:%M", time.localtime(reset_ts))
            wait_desc = f"{h}小时{m_min}分钟" if h > 0 else f"{m_min}分钟"
            _quota_cache["exceeded"] = True
            _quota_cache["remaining_seconds"] = wait_sec
            _quota_cache["reset_timestamp"] = reset_ts
            _quota_cache["wait_desc"] = wait_desc
            _quota_cache["reset_time_clock"] = clock_str
            quota_info = get_quota_status(force_probe=False)
            quota_wait = wait_desc
            err_msg = f"已达 MEGA 免费流量限额，预计于 {clock_str} 解除 (还需等待 {wait_desc})"
        return {
            "success": False,
            "error": err_msg,
            "quota_exceeded": bool(quota_wait),
            "wait_time": quota_wait,
            "quota": quota_info
        }

def get_transfers() -> Dict[str, Any]:
    """
    获取当前活跃的下载传输任务 (自动过滤已取消和已完成的任务，自动清理遗留探测任务)
    mega-cmd 输出格式: TYPE|||TAG|||SOURCEPATH|||DESTINYPATH|||PROGRESS|||STATE
    """
    res = run_mega_command(["transfers", "--col-separator=|||"], timeout=15)
    transfers = []
    has_retrying = False
    
    if res["success"] and res["stdout"]:
        lines = res["stdout"].splitlines()
        for line in lines:
            line_str = line.strip()
            if not line_str or "TYPE legend" in line_str or "TAG" in line_str:
                continue
            cols = [c.strip() for c in line_str.split("|||")]
            if len(cols) >= 6:
                status = cols[5]
                if any(s in status.upper() for s in ("CANCEL", "COMPLET", "CANCELED")):
                    continue
                source_path = cols[2]
                # 自动拦截并取消遗留的探测任务或欢迎pdf
                if any(k in source_path for k in ("欢迎来到MEGA.pdf", ".quota_probe", "welcome to mega.pdf")):
                    tag = cols[1]
                    if tag:
                        run_mega_command(["transfers", "-c", tag])
                    continue
                if any(k in status.upper() for k in ("RETRY", "PAUSE", "BLOCK")):
                    has_retrying = True
                file_name = os.path.basename(source_path) if source_path else "未知下载项"
                transfers.append({
                    "type": cols[0],
                    "tag": cols[1],
                    "name": file_name,
                    "source": source_path,
                    "dest": cols[3],
                    "progress": cols[4],
                    "status": status
                })
            elif len(cols) >= 4:
                status = cols[5] if len(cols) > 5 else "ACTIVE"
                if any(s in status.upper() for s in ("CANCEL", "COMPLET", "CANCELED")):
                    continue
                source_path = cols[2] if len(cols) > 2 else ""
                if any(k in source_path for k in ("欢迎来到MEGA.pdf", ".quota_probe", "welcome to mega.pdf")):
                    tag = cols[1] if len(cols) > 1 else ""
                    if tag:
                        run_mega_command(["transfers", "-c", tag])
                    continue
                if any(k in status.upper() for k in ("RETRY", "PAUSE", "BLOCK")):
                    has_retrying = True
                transfers.append({
                    "type": cols[0],
                    "tag": cols[1] if len(cols) > 1 else "",
                    "name": os.path.basename(source_path) if source_path else "未知下载项",
                    "source": source_path,
                    "dest": cols[3] if len(cols) > 3 else "",
                    "progress": cols[4] if len(cols) > 4 else "--",
                    "status": status
                })

    # 读取实时同步的配额状态
    quota_info = get_quota_status(force_probe=False)

    # 关键修复：若传输队列中有任务处于 RETRY/BLOCK 状态但缓存未记录限额，
    # 说明限额可能在上次服务重启前被触发。此时根据传输状态推断限额并设保守倒计时。
    if has_retrying and not quota_info["exceeded"]:
        now = time.time()
        conservative_wait_sec = 7200  # 保守估计 2 小时
        reset_ts = now + conservative_wait_sec
        clock_str = time.strftime("%H:%M", time.localtime(reset_ts))
        wait_desc = "约2小时"
        _quota_cache["exceeded"] = True
        _quota_cache["remaining_seconds"] = conservative_wait_sec
        _quota_cache["reset_timestamp"] = reset_ts
        _quota_cache["wait_desc"] = wait_desc
        _quota_cache["reset_time_clock"] = clock_str
        quota_info = {
            "exceeded": True,
            "remaining_seconds": conservative_wait_sec,
            "wait_time": wait_desc,
            "reset_time_clock": clock_str,
            "desc": f"配额超限 (从传输状态推断)，预计于 {clock_str} 解除 (还需 {wait_desc})"
        }

    for t in transfers:
        if any(k in t["status"].upper() for k in ("RETRY", "PAUSE", "BLOCK")):
            t["quota_wait"] = quota_info["wait_time"]
            t["reset_clock"] = quota_info["reset_time_clock"]

    return {
        "success": True,
        "transfers": transfers,
        "count": len(transfers),
        "quota": quota_info,
        "quota_wait": quota_info["wait_time"] if quota_info["exceeded"] else None
    }

def cancel_transfer(tag: str) -> Dict[str, Any]:
    """取消指定的传输任务 (tag 或 'all')"""
    arg = "-a" if tag == "all" else tag
    res = run_mega_command(["transfers", "-c", arg])
    return {
        "success": res["success"],
        "message": f"任务 {tag} 已取消" if res["success"] else res["stderr"]
    }

def pause_transfer(tag: str) -> Dict[str, Any]:
    """暂停指定的传输任务 (tag 或 'all')"""
    arg = "-a" if tag == "all" else tag
    res = run_mega_command(["transfers", "-p", arg])
    return {
        "success": res["success"],
        "message": f"任务 {tag} 已暂停" if res["success"] else res["stderr"]
    }

def resume_transfer(tag: str) -> Dict[str, Any]:
    """恢复指定的传输任务 (tag 或 'all')"""
    arg = "-a" if tag == "all" else tag
    res = run_mega_command(["transfers", "-r", arg])
    return {
        "success": res["success"],
        "message": f"任务 {tag} 已恢复" if res["success"] else res["stderr"]
    }

def move_cloud_to_trash(remote_path: str) -> Dict[str, Any]:
    """
    将云端文件或文件夹移入 MEGA 回收站 (RubbishBin //bin/)
    """
    path_clean = remote_path.strip()
    if not path_clean or path_clean == "/":
        return {"success": False, "error": "不能删除网盘根目录"}

    res = run_mega_command(["mv", path_clean, "//bin/"], timeout=20)
    if res["success"]:
        return {"success": True, "message": f"已将 {path_clean} 移至网盘回收站"}
    return {"success": False, "error": res["stderr"] or res["stdout"]}

def list_cloud_trash() -> Dict[str, Any]:
    """列出网盘回收站 (//bin) 内的所有文件与文件夹"""
    res = run_mega_command(["ls", "-l", "--time-format=ISO6081_WITH_TIME", "//bin"], timeout=20)
    if not res["success"]:
        res = run_mega_command(["ls", "-l", "--time-format=ISO6081_WITH_TIME", "/RubbishBin"], timeout=20)

    items = []
    if res["success"]:
        for line in res["stdout"].splitlines():
            line_clean = line.strip()
            if not line_clean or line_clean.startswith("FLAGS") or line_clean.startswith("Total"):
                continue
            parts = line_clean.split(None, 4)
            if len(parts) >= 5:
                is_dir = parts[0].startswith('d') or parts[0].startswith('b')
                size_int = 0
                try:
                    if parts[2] != '-':
                        size_int = int(parts[2])
                except Exception:
                    pass
                items.append({
                    "name": parts[4],
                    "path": "//bin/" + parts[4],
                    "is_dir": is_dir,
                    "size": size_int,
                    "size_str": format_bytes(size_int) if not is_dir else "--",
                    "mtime": parts[3]
                })

    return {
        "success": True,
        "items": items,
        "total": len(items)
    }

def empty_cloud_trash() -> Dict[str, Any]:
    """
    清空网盘回收站
    """
    res = run_mega_command(["rm", "-r", "-f", "//bin/*"], timeout=35)
    if not res["success"]:
        res = run_mega_command(["rm", "-r", "-f", "/RubbishBin/*"], timeout=35)
        
    return {
        "success": res["success"],
        "message": "网盘回收站已成功清空" if res["success"] else (res["stderr"] or res["stdout"])
    }

def restore_cloud_trash(remote_path: str, target_dir: str = "/") -> Dict[str, Any]:
    """
    将网盘回收站中的文件或文件夹恢复到指定目录 (默认网盘根目录 /)
    """
    path_clean = remote_path.strip()
    if not path_clean:
        return {"success": False, "error": "恢复路径不能为空"}

    # 确保源路径带有 //bin/ 或 /RubbishBin/ 前缀
    if not path_clean.startswith("//bin/") and not path_clean.startswith("/RubbishBin/"):
        path_clean = "//bin/" + path_clean.lstrip("/")

    target_clean = target_dir.strip() or "/"
    if not target_clean.startswith("/"):
        target_clean = "/" + target_clean

    res = run_mega_command(["mv", path_clean, target_clean], timeout=25)
    if res["success"]:
        base_name = os.path.basename(path_clean)
        return {"success": True, "message": f"已成功恢复 {base_name} 至网盘根目录"}
    return {"success": False, "error": res["stderr"] or res["stdout"]}

