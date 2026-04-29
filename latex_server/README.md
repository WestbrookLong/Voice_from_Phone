# LaTeX Cloud Editor

云端协同编辑 + 本地编译的 LaTeX 编辑器。

## 架构

- **云端服务器 (`server.py`)**：WebSocket 消息中继 + 文档快照持久化 + 图片存储
- **本地桥接 (`desktop_client.py`)**：TK 桌面客户端，托管前端页面，轮询云端文本，调用本地 MiKTeX 编译
- **前端 (`static/index.html`)**：基于 Monaco Editor + Yjs CRDT 的浏览器编辑器，PDF.js 预览

## 使用方式

### 1. 启动云端服务器

```bash
python server.py --host 0.0.0.0 --port 9800
```

云端服务器负责：
- 中继所有客户端的 Yjs CRDT 更新（保证多人实时协同不冲突）
- 每 5 秒接收前端发送的文本快照并持久化到磁盘
- 存储项目图片（`POST /api/projects/{id}/images`）

### 2. 启动本地桥接

```bash
python desktop_client.py
```

在弹出的窗口中：
- **端口**：本地桥接 HTTP 服务端口（默认 9801）
- **云端地址**：云服务器地址（默认 `http://127.0.0.1:9800`）
- **项目 ID**：协同编辑的项目标识
- **本地目录**：本地 `.tex` 文件和图片存放路径

点击"启动服务"后：
- 本地桥接每 3 秒从云端轮询最新文本，写入 `main.tex`
- 提供浏览器编辑器页面（`http://本机IP:端口/?token=...`）
- 提供编译 API（调用本地 `latexmk` / `pdflatex`）

### 3. 打开编辑器

点击"打开编辑器"或扫描二维码，在浏览器中打开编辑器页面。

在设置面板中确认：
- 云端 WebSocket 地址（如 `ws://服务器IP:9800/ws`）
- 本地桥接 HTTP 地址（如 `http://127.0.0.1:9801`）
- 项目 ID

### 4. 编辑与编译

- **实时协同**：多人打开同一项目，通过 Yjs CRDT 自动合并编辑操作，无冲突
- **编译**：点击"编译"按钮或按 `Ctrl+Enter`，本地桥接调用 MiKTeX 生成 PDF
- **错误高亮**：编译错误自动解析并显示在编辑器下方，点击可跳转到对应行
- **插入图片**：点击"插入图片"上传，图片自动同步到云端，编译前自动下载到本地 `figures/` 目录

## 文件说明

| 文件 | 说明 |
|------|------|
| `server.py` | 云端协同服务器 |
| `desktop_client.py` | 本地桥接（TK GUI + HTTP 服务 + 编译器调用） |
| `static/index.html` | 前端编辑器（Monaco + Yjs + PDF.js） |
| `data/projects/` | 云端持久化的文本快照 |
| `data/images/` | 云端存储的项目图片 |
| `local_projects/` | 本地桥接下载的 `.tex` 和图片 |

## 依赖

- Python 3.10+
- MiKTeX（或 TeX Live）本地安装，确保 `latexmk` 或 `pdflatex` 在 PATH 中
- 浏览器（Chrome / Edge / Firefox）

## 与 Overleaf 的区别

| 特性 | Overleaf | 本项目 |
|------|----------|--------|
| 协同编辑 | 服务器端 OT | 浏览器端 Yjs CRDT + 云端中继 |
| 编译位置 | 云端服务器 | **本地 MiKTeX** |
| 图片存储 | 云端 | 云端 + 本地自动同步 |
| 离线编辑 | 不支持 | **必须联网**（云端同步） |
| 自定义宏包 | 受限 | **完整本地宏包支持** |
