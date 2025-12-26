# Better Debug (pyserial)

一个基于 `pyserial` 的串口调试/打印工具：

- CLI：终端交互收发、可脚本化/可重定向
- GUI：基于 Qt（PySide6）的跨平台界面（Windows / Linux / macOS）

本仓库的目标是：

- 先保证“连接稳定 + 打印清晰 + 多格式发送好用”
- 再保证“代码结构清晰、好加功能、好测”

> 说明：当前版本是一个可运行的 MVP，串口基础能力已齐；后续会逐步把更多“串口助手”常见能力补齐（见下方 Roadmap）。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 安装（GUI 版）

GUI 使用 Qt（PySide6），支持 Windows / Linux / macOS。

```powershell
pip install -r requirements-gui.txt
```

## 快速开始（建议流程）

### 1) 创建虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2) 安装依赖

- 只用 CLI：

```powershell
pip install -r requirements.txt
```

- 要用 GUI：

```powershell
pip install -r requirements-gui.txt
```

## 列出串口

```powershell
python -m better_debug --list
```

## 连接并交互

```powershell
python -m better_debug --port COM3 --baud 115200 --rx both --eol crlf --timestamp --log serial.log
```

## 启动 GUI

```powershell
python -m better_debug --gui
```

---

# 功能说明（现有）

## 1) 通用串口能力

- 端口枚举（CLI：`--list`；GUI：Refresh）
- 打开/关闭串口
- 常用串口参数
	- CLI 已支持：`baud/bytesize/parity/stopbits/xonxoff/rtscts/dsrdtr/timeout`
	- GUI 当前版本：提供 `port/baud/encoding/eol/rx mode`，以及 `xonxoff/rtscts/dsrdtr` 开关
- 可选时间戳（CLI：`--timestamp`；GUI：Timestamp）
- 可选日志（按 HEX 记录 TX/RX）

## 2) 接收打印（RX）

支持 3 种显示模式：

- `text`：按指定编码解码（默认 `utf-8`，错误用替换字符兜底）
- `hex`：按十六进制显示（大写，空格分隔）
- `both`：同时输出 text 与 hex

CLI 使用 `--rx text|hex|both`；GUI 在界面里选择 `RX` 模式。

## 3) 发送（TX）——多种格式

### 3.1 文本发送（text）

- CLI：
	- 直接输入一行（不以 `:` 开头）：作为文本发送
	- 或用 `:text <payload>`
- GUI：Send as = `text`

文本发送会追加行尾（EOL）：`none/lf/cr/crlf`。

### 3.2 HEX 发送（hex）

支持以下输入：

- `AA55`（紧凑写法）
- `AA 55 01 02`（空格）
- `AA:55;01,02`（任意分隔符）
- `0xAA,0x55`（带 `0x` 的 token 序列）

### 3.3 Base64 发送（base64 / b64）

用于从外部复制 base64 数据直接发送原始字节。

### 3.4 16-bit word 发送（u16/i16）

用于“按 word(16-bit) 序列”发送（常见于协议/寄存器场景），并且可选端序：

- `u16le`：无符号 16 位，小端（`0x1234 -> 34 12`）
- `u16be`：无符号 16 位，大端（`0x1234 -> 12 34`）
- `i16le`：有符号 16 位，小端
- `i16be`：有符号 16 位，大端

### 3.5 发送文件（file）

把文件按“原始字节”发送。

---

# CLI 使用指南

## 1) 常用参数

示例：

```powershell
python -m better_debug --port COM3 --baud 115200 --rx both --eol crlf --timestamp --log serial.log
```

说明：

- `--port`：串口名（Windows 常见为 `COM3`）
- `--baud`：波特率
- `--encoding`：文本解码/编码（默认 `utf-8`）
- `--eol`：文本发送追加的行尾（默认 `crlf`）
- `--escapes`：开启后，文本发送支持 `\n \r \t \xNN` 等转义
- `--log`：把 TX/RX 以 HEX 行写入文件

## 2) 交互命令（以 `:` 开头）

进入后输入 `:help` 会显示内置帮助。常用命令：

- `:quit`：退出
- `:flush`：清空接收缓冲
- `:rx text|hex|both`：切换 RX 显示
- `:encoding <name>`：切换编码
- `:eol none|lf|cr|crlf`：切换文本发送行尾
- `:text <payload>`
- `:hex <AA 55 01 02>`
- `:b64 <base64>`
- `:u16le <n1 n2 ...>` / `:u16be ...`
- `:i16le <n1 n2 ...>` / `:i16be ...`
- `:file <path>`

---

# GUI 使用指南

## 1) 界面元素

- 顶部工具栏：
	- 左侧：Serial（当前功能，高亮）
	- 右侧：Settings（进入软件设置页：风格/字体/字体大小/文本颜色）
- 主页面（Serial）：
	- 左侧参数栏：从上到下依次排列（默认宽度 240），可拖动分割条改变宽度；窗口宽度缩小到阈值时会自动隐藏
	- 右侧：
		- 接收区：顶部标签栏（类似浏览器 Tab），默认 `[ALL]`，并按 `[tag]message` 自动生成对应标签
		- 发送区：多行文本输入框（可通过分割条调节高度，默认约 120）+ Send

## 2) GUI 的日志

如果 Log 路径不为空：

- 每行格式：`[可选时间戳] TX|RX <HEX...>`
- 便于后期做“回放/对比/问题定位”

## 3) 接收区 Tab 分流

当接收文本行满足形如：`[wifi]xxx`、`[bt]xxx`、`[system]xxx` 这种“行首 tag”格式时：

- `[ALL]`：始终包含所有接收输出
- `[wifi]` / `[bt]` / ...：只显示对应 tag 的行

不同 Tab 的数据彼此独立；切换 Tab 不会丢失之前的输出。

补充规则：只有 tag 的首字符为英文字母（`A-Z` 或 `a-z`）时，才会自动创建对应标签页（例如 `[00:11:22][debug]...` 会进入 `[debug]`，但 `[00:11:22][123]...` 不会创建 `[123]`）。

---

# 代码结构与开发文档

## 1) 模块划分

- `better_debug/formats.py`
	- 负责“多格式输入 -> bytes”的解析
	- 典型函数：
		- `parse_hex_string()`：HEX 输入解析
		- `parse_u16_list()/parse_i16_list()`：word 序列打包
		- `parse_base64()`：base64 解码
		- `apply_text_escapes()`：文本转义解析
- `better_debug/monitor.py`
	- CLI 用的串口读线程与收发封装
	- `SerialMonitor`：负责打开串口、后台 read、打印、可选日志
- `better_debug/cli.py`
	- CLI 参数解析、交互命令解析、把用户输入转成 bytes 并调用 `SerialMonitor.send()`
	- `--gui` 入口也放在这里，便于统一从 `python -m better_debug` 启动
- `better_debug/gui.py`
	- Qt GUI 实现
	- 采用“后台线程读串口 + Qt Signal 发到 UI”的模型，避免阻塞界面
- `tests/test_formats.py`
	- 解析层单测（不依赖真实串口硬件，跑得快、稳定）

## 2) 线程模型/数据流（关键点）

### CLI

- 主线程：读取 stdin（你的输入）并调用 `send()`
- 后台线程：循环 `serial.read()`，拿到数据后直接输出到 stdout，并可写日志

### GUI

- UI 线程（Qt 主线程）：负责渲染与响应按钮
- 后台线程：循环 `serial.read()`
- 用 Qt Signal：把 `bytes` 发回 UI 线程进行显示

这个模型的目标是：

- 串口读不会卡 UI
- UI 更新线程安全

## 3) 如何新增“发送格式”（推荐扩展点）

以新增 `u32le/u32be` 为例（示意流程）：

1) 在 `better_debug/formats.py` 增加解析/打包函数（并抛出 `FormatError`）
2) 在 `better_debug/cli.py`：
	 - `:u32le` 命令分支里调用新的解析函数
3) 在 `better_debug/gui.py`：
	 - `Send as` 下拉框里新增 `u32le/u32be`
	 - 在 `on_send()` 里增加对应分支
4) 在 `tests/` 增加单测

为什么建议这么做：

- 解析逻辑集中在 `formats.py`，方便测试/复用
- CLI/GUI 都只是“薄薄的一层壳”

## 4) 如何新增“接收显示”能力

- CLI：修改 `better_debug/monitor.py` 的 `_emit()`
- GUI：修改 `better_debug/gui.py` 的 `on_rx()`

建议：尽量保持“显示层不做协议解析”，协议解析如果要做，最好单独建一个模块（后续如果你需要，我再按你的协议结构来设计）。

## 5) 如何新增/扩展日志格式

当前日志是最通用的 HEX 行格式（便于肉眼排查，也便于后续解析）。

如需更结构化（JSONL、CSV、按帧分段、带方向/时间/统计），建议新增一个 `logger.py` 统一封装，然后 CLI/GUI 共用。

---

# 测试与验证

## 单元测试

```powershell
python -m pytest
```

当前测试覆盖：多格式解析（HEX、u16/i16、escapes 等）。

## 串口硬件验证建议

- Windows：可用 USB-TTL 或虚拟串口对（例如 com0com）做 loopback
- Linux/macOS：可用 `socat` 创建伪终端对（PTY）做 loopback

---

# Roadmap（计划补齐的功能）

以下是“典型串口调试助手常见能力”，会按优先级逐步加入：

1) GUI 暴露更多串口参数：bytesize/parity/stopbits/flow control
2) 发送区增强：多行文本、历史记录、常用发送条目（快捷按钮）
3) 自动重复发送：周期发送/次数限制
4) 配置持久化：记住上次端口/波特率/编码/窗口布局
5) 更友好的 RX 显示：自动滚动开关、清屏、过滤不可见字符（不做“协议过滤器/复杂过滤器”，保持简单）

---

# 常见问题（FAQ）

## 1) 找不到串口

- Windows：检查设备管理器里的 COM 号；权限一般不是问题
- Linux：可能需要把用户加入 `dialout` 组或用 `sudo`（不推荐长期使用）
- macOS：通常在 `/dev/cu.*` 下

## 2) GUI 无法启动

- 确认安装了 GUI 依赖：`pip install -r requirements-gui.txt`
- 若环境是最小化/无 GUI（例如服务器），请使用 CLI 模式
