"""② JS 音源脚本管理 —— 只管安装 / 更新 / 列表 / 删除，**不执行脚本**。

术语（见 ``docs/CONVENTIONS.md``）：

* 本包 = **音源脚本**（``pdone/lx-music-source`` 的 ``flower``/``sixyin``/``lx`` …），
  装在 ``user_api.json``，唯一职责是"给 songmid → 换播放 URL"
* **不是** ``lx_cli.sources``（那是平台元数据接口，负责搜索）

⚠️ 硬约束（照 ``lx-music-desktop`` 源码，违反会损坏 LX）：

1. ``script`` 字段编码 = ``"gz_" + base64(``**zlib**``.compress(utf8))``
   —— **不是 gzip**！用 ``gzip.decompress`` 会失败
2. ``user_api.json`` 必须 **Tab 缩进**、**原子写**（temp + rename）；
   解析失败 LX 会把文件改名 ``.bak`` 并弹错误框
3. **LX 运行时不得写入**（LX 是内存缓存 + 全量回写，会覆盖我们的写入）
4. 元数据头必须在**文件索引 0** 处有 ``/* */``；白名单 5 键
   ``name/description/author/homepage/version``；截断长度 24/36/56/1024/36
5. **不得改动脚本一个字节**（``lx/2.js`` 有基于 ``@name+@description`` 的
   自毁校验；多脚本有 ``SCRIPT_MD5`` 自校验）
"""
