"""lx-cli — 洛雪音乐助手 (LX Music desktop) 的命令行工具。

设计分层（见 ../03-重建方案与命令清单.md）::

    core/    领域层：id/meta 契约、DB 读写、Open API 客户端、匹配算法
    sources/ 内置 5 平台元数据源（直连官方接口），支持单源/多源/聚合搜索
    scripts/ 音源脚本管理（安装/更新/列表/删除；不执行脚本）
    cli/     Click 表现层

关键契约（务必遵守，来自 lx-music-desktop-2.12.5 源码 `toNewMusicInfo`）:

* ``kw/tx/wy/mg`` 的歌曲 id 是 ``<source>_<songmid>``
* **``kg`` 的歌曲 id 是 ``<songmid>_<hash>``（无 source 前缀！）**
* ``local`` 的 id 是文件绝对路径

因此 **绝不能** 用 ``id.split('_')[0]`` 反推 source，必须读 ``source`` 字段。
"""

__version__ = "0.2.1"
