"""
local_settings.py 的模板文件。

新机器上部署 Omni Deck 时，把这份文件复制一份、改名成同目录下的 `local_settings.py`，
再按自己的实际情况填写下面几项——那份文件已经加进 `.gitignore`，不会被提交到 git，
这份模板本身没有任何真实的路径/域名/密码，可以随代码公开分发。

`app_config.py` 就是从 `local_settings.py` 读这些值的；找不到 `local_settings.py` 时
`app_config.py` 会退回到本文件同款的通用默认值，保证首次 clone 下来代码不会直接崩，
只是相当于"资源库还没配置""广域网隧道没开"。
"""

# 资源库根路径：新下载/新写入固定落在第一项（"主库"），其余按顺序作为只读扫描来源
# （比如再插一张 SD 卡、换一个下载盘，加一行就行，不用去各个 service 文件里找哪里写死了路径）。
LIBRARY_ROOTS = [
    "/home/deck/Games",
]

# Cloudflare 广域网隧道域名，不需要在外网访问就留 None（广域网远程访问功能整体关闭）。
WAN_DOMAIN = None

# NSFW 内容锁的默认密码，仅在第一次使用、还没设置过密码时生效——请务必在 App 内的
# 「NSFW 解锁」弹窗里把密码改成非默认值，不要让这个值一直生效。
NSFW_DEFAULT_PASSWORD = "changeme"
