"""
游戏资源虚拟文件系统：Windows 游戏在 Linux 上的大小写敏感问题、RPG Maker 加密扩展名互转、
汉化补丁改名后的反向映射、语言子目录回退——所有 /game/<id>/... 请求都经这里解析成真实路径。
"""
import json
import os
import urllib.parse


REVERSE_LOCALE_CACHE = {}

def _merge_locale_reverse_map(json_path: str, rev: dict) -> None:
    """读取一个语言包 JSON 文件，把"翻译后文本 -> 原始 key"的反向映射合并进 rev。

    从 get_reverse_locale() 拆出来的单文件加载逻辑，避免那边的
    "遍历文件 -> 遍历 JSON 键值对" 叠成三层嵌套。

    Args:
        json_path: 语言包 JSON 文件路径。
        rev: 累积结果的反向映射字典（原地修改，不返回新对象）。
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as jf:
            data = json.load(jf)
        if not isinstance(data, dict):
            return
        for k, v in data.items():
            if isinstance(v, str) and isinstance(k, str) and len(v) < 100:
                rev[v.strip().lower()] = k.strip()
    except Exception:
        pass


def get_reverse_locale(base_dir):
    """
    扫描游戏 locales/ 目录下的翻译 JSON 映射表，构建反向映射字典。
    解决多语言汉化补丁中将文件名改为中文导致游戏内核找不到原英文/日文资源的问题。
    """
    if base_dir in REVERSE_LOCALE_CACHE:
        return REVERSE_LOCALE_CACHE[base_dir]
    rev = {}
    locales_dir = os.path.join(base_dir, 'locales')
    if os.path.isdir(locales_dir):
        try:
            for root, dirs, files in os.walk(locales_dir):
                for f in files:
                    if f.endswith('.json'):
                        _merge_locale_reverse_map(os.path.join(root, f), rev)
        except Exception:
            pass
    REVERSE_LOCALE_CACHE[base_dir] = rev
    return rev

KNOWN_LOCALES = {'tw', 'ch', 'zh', 'zh-cn', 'zh-tw', 'en', 'ja', 'jp', 'es', 'ru', 'kr', 'fr', 'de'}

def try_strip_locale(rel_path: str):
    """尝试剥离 URL 路径中的语言前缀目录（如 img/zh-cn/pictures -> img/pictures）以实现自适应回退"""
    parts = rel_path.strip('/').split('/')
    new_parts = []
    removed = False
    for i, p in enumerate(parts):
        if not removed and p.lower() in KNOWN_LOCALES and i > 0 and i < len(parts) - 1:
            removed = True
            continue
        new_parts.append(p)
    return '/'.join(new_parts) if removed else None

def _resolve_case_insensitive_path_inner(base_dir, rel_path):
    """
    Linux 虚拟文件系统 (VFS) 大小写无关与扩展名混淆回退核心算法：
    1. 逐层路径贪婪匹配与 URL 解码
    2. RPG Maker 加密扩展名自动互转 (.rpgmvp <-> .png, .rpgmvo <-> .ogg, .rpgmvm <-> .m4a)
    3. 多语言旗帜与语言包命名互转 (flag_ <-> locale_)
    4. 反向翻译字典逆向匹配
    """
    current = base_dir
    decoded_path = urllib.parse.unquote(rel_path)
    parts = decoded_path.strip('/').split('/')
    for part in parts:
        if not part: continue
        target = os.path.join(current, part)
        if os.path.exists(target):
            current = target
        else:
            found = False
            if os.path.isdir(current):
                part_lower = part.lower()
                part_no_asar = part_lower[:-5] if part_lower.endswith('.asar') else part_lower
                
                candidates = [part_lower, part_no_asar]
                if part_lower.endswith('.png'):
                    candidates.extend([part_lower[:-4] + '.rpgmvp', part_lower + '_'])
                elif part_lower.endswith('.rpgmvp'):
                    candidates.extend([part_lower[:-7] + '.png', part_lower[:-7] + '.png_'])
                elif part_lower.endswith('.ogg'):
                    candidates.extend([part_lower[:-4] + '.rpgmvo', part_lower + '_'])
                elif part_lower.endswith('.rpgmvo'):
                    candidates.extend([part_lower[:-7] + '.ogg', part_lower[:-7] + '.ogg_'])
                elif part_lower.endswith('.m4a'):
                    candidates.extend([part_lower[:-4] + '.rpgmvm', part_lower + '_'])
                elif part_lower.endswith('.rpgmvm'):
                    candidates.extend([part_lower[:-7] + '.m4a', part_lower[:-7] + '.m4a_'])
                elif part_lower.endswith('.mp4'):
                    candidates.append(part_lower + '_')

                if part_lower.startswith('flag_'):
                    candidates.extend(['locale_' + part_lower[5:], 'locale_' + part_lower[5:] + '_'])
                elif part_lower.startswith('locale_'):
                    candidates.extend(['flag_' + part_lower[7:], 'flag_' + part_lower[7:] + '_'])

                entries = os.listdir(current)
                for entry in entries:
                    entry_lower = entry.lower()
                    if entry_lower in candidates:
                        current = os.path.join(current, entry)
                        found = True
                        break

                if not found and base_dir:
                    rev_dict = get_reverse_locale(base_dir)
                    stem, ext = os.path.splitext(part)
                    stem_lower = stem.strip().lower()
                    if stem_lower in rev_dict:
                        orig_key = rev_dict[stem_lower]
                        cand_names = [orig_key.lower() + ext.lower(), orig_key.lower()]
                        for entry in entries:
                            entry_lower = entry.lower()
                            if entry_lower in cand_names or entry_lower.startswith(orig_key.lower()):
                                current = os.path.join(current, entry)
                                found = True
                                break

            if not found:
                return os.path.join(current, part)
    return current

def resolve_case_insensitive_path(base_dir, rel_path):
    """URL 解码 + 忽略大小写智能查找 + 资源扩展名智能回退 + 翻译资源反向映射 + 语言子目录自适应回退"""
    res = _resolve_case_insensitive_path_inner(base_dir, rel_path)
    if os.path.exists(res):
        return res
    stripped = try_strip_locale(rel_path)
    if stripped:
        fallback_res = _resolve_case_insensitive_path_inner(base_dir, stripped)
        if os.path.exists(fallback_res):
            return fallback_res
    return res
