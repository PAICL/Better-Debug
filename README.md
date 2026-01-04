# Better Debug (pyserial)

一个基于 `pyserial` 的跨平台串口调试/打印工具，提供 CLI 和 GUI 两种使用模式。

- **CLI (命令行)**：适合快速交互、脚本化调用、重定向输出。
- **GUI (图形界面)**：基于 Qt (PySide6)，提供多标签页分流、动态表格刷新、ANSI 颜色支持等高级功能。

本项目的目标是提供一个“连接稳定、打印清晰、发送格式灵活”的现代化串口助手，并保持代码结构清晰，易于扩展。

## 核心特性

- **双模式运行**：
    - CLI：交互式 Shell，支持命令补全和历史记录（依赖终端能力）。
    - GUI：跨平台（Windows/Linux/macOS），现代化界面。
- **灵活的发送功能**：
    - 支持 Text (可转义), Hex, Base64, C-struct 数组 (u16/i16), 文件发送。
    - 支持多种行尾格式 (None, LF, CR, CRLF)。
- **强大的接收显示**：
    - 支持 Text (自动解码), Hex, Both (同时显示) 三种模式。
    - 支持时间戳显示。
    - **自动 Tag 分流**：自动识别日志中的 `[tag]` 并分流到独立标签页。
    - **动态表格 (Table)**：支持通过特定协议头自动创建并刷新表格视图。
    - **ANSI 颜色支持**：正确解析并显示终端颜色代码。
- **日志记录**：支持将 TX/RX 数据以 HEX 格式记录到文件，便于回放分析。

## 安装

### 1. 环境准备

确保已安装 Python 3.8 或更高版本。建议使用虚拟环境：

```powershell
python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# Linux/macOS
# source .venv/bin/activate
```

### 2. 安装依赖

根据需要选择安装：

- **仅使用 CLI**：

```powershell
pip install -r requirements.txt
```

- **使用 GUI (推荐)**：

```powershell
pip install -r requirements-gui.txt
```

## 快速开始

### 列出可用串口

```powershell
python -m better_debug --list
```

### 启动 CLI 模式

连接 COM3，波特率 115200，同时显示 Text 和 Hex，开启时间戳：

```powershell
python -m better_debug --port COM3 --baud 115200 --rx both --eol crlf --timestamp --log serial.log
```

### 启动 GUI 模式

```powershell
python -m better_debug --gui
```

---

# 功能详解

## 1. CLI 交互模式

启动 CLI 后，你可以直接输入文本发送，或使用以 `:` 开头的命令进行控制。

### 常用命令

- `:help`：显示帮助信息。
- `:quit`：退出程序。
- `:flush`：清空接收缓冲区。
- `:rx <text|hex|both>`：切换接收显示模式。
- `:encoding <name>`：切换文本编码 (如 utf-8, gbk, ascii)。
- `:eol <none|lf|cr|crlf>`：设置发送文本时的行尾符。

### 发送命令

- **文本**：直接输入内容（不以 `:` 开头），或使用 `:text <content>`。
- **十六进制**：`:hex AA 55 01 02` (支持空格、冒号等分隔符)。
- **Base64**：`:b64 <base64_string>` (解码后发送原始字节)。
- **16位整数列表**：
    - `:u16le 0x1234 100` (小端无符号)
    - `:u16be 0x1234 100` (大端无符号)
    - `:i16le -123 456` (小端有符号)
- **文件**：`:file <path/to/file>` (发送文件的原始内容)。

## 2. GUI 界面功能

### 界面概览

- **左侧设置栏**：
    - **Port/Baud**：串口参数设置。
    - **Encoding/EOL**：编码与行尾设置。
    - **RX Mode**：接收显示模式 (Text/Hex/Both)。
    - **开关项**：XON/XOFF, RTS/CTS, DSR/DTR, Escapes (转义支持), Timestamp (时间戳)。
    - **Log**：日志文件路径设置。
    - **控制按钮**：Open/Close, Flush, Pause, Clear。
    - *注：左侧栏宽度可拖动调节，过窄时会自动隐藏。*
- **右侧接收区**：
    - 多标签页设计，默认包含 `[ALL]` 标签，显示所有数据。
    - 支持 ANSI 颜色显示。
- **右侧发送区**：
    - 支持多行文本输入。
    - **Send as**：下拉选择发送格式 (Text, Hex, Base64, u16le, etc.)。

### 高级特性：自动 Tag 分流

当接收到的日志行符合 `[tag]message` 格式（且 `tag` 以字母开头）时，GUI 会自动创建一个名为 `[tag]` 的新标签页，并将该行内容分流到该标签页中。

- `[ALL]` 标签页始终包含所有内容。
- `[tag]` 标签页只包含对应 tag 的内容。
- 适合多模块调试（如 `[wifi]`, `[bt]`, `[sensor]` 分离显示）。

### 高级特性：动态表格 (Table)

GUI 支持一种特殊的协议头，用于在独立的标签页中刷新显示表格或状态信息。

**协议格式**：

1.  **开始刷新**：`[&Table][TableName][Start]`
2.  **数据内容**：任意文本行
3.  **结束刷新**：`[&Table][TableName][End]`

**行为逻辑**：

- 当收到 `[&Table][MyStatus][Start]` 时：
    - 自动创建（或聚焦）名为 `[MyStatus]` 的标签页。
    - **清空** 该标签页的现有内容。
    - 进入“表格模式”。
- 在 Start 和 End 之间的所有接收内容，会实时追加到 `[MyStatus]` 标签页中。
- 收到 `[&Table][MyStatus][End]` 后，退出“表格模式”。

**应用场景**：
周期性打印系统状态（如 CPU 占用、内存池状态、任务列表），每次打印前自动清屏，实现类似 `top` 命令的动态刷新效果。

## 3. 发送格式详解

| 模式 | 说明 | 示例输入 | 发送数据 (Hex) |
| :--- | :--- | :--- | :--- |
| **text** | 普通文本，支持转义 (需开启 Escapes) | `Hello\n` | `48 65 6C 6C 6F 0A` |
| **hex** | 十六进制字符串 | `AA 55 01` | `AA 55 01` |
| **base64** | Base64 解码 | `SGVsbG8=` | `48 65 6C 6C 6F` |
| **u16le** | 16位小端整数序列 | `0x1234 10` | `34 12 0A 00` |
| **u16be** | 16位大端整数序列 | `0x1234 10` | `12 34 00 0A` |
| **file** | 文件内容 | `firmware.bin` | (文件原始内容) |

---

# 开发与构建

## 运行测试

项目包含基于 `pytest` 的单元测试，主要覆盖格式解析逻辑。

```powershell
python -m pytest
```

## 构建可执行文件 (EXE)

项目提供了构建脚本，使用 PyInstaller 将 GUI 版本打包为单文件 EXE。

1.  确保已安装 GUI 依赖。
2.  运行构建脚本：

```powershell
.\build.ps1
```

构建产物将位于 `release/BetterDebug.exe`。

---

# Roadmap

- [ ] **更多串口参数**：在 GUI 中暴露 Parity, Stopbits, Bytesize 等高级设置。
- [ ] **发送增强**：发送历史记录、快捷发送列表（常用指令集）。
- [ ] **自动发送**：支持定时循环发送。
- [ ] **配置持久化**：记住上次使用的端口、波特率和窗口布局（已部分实现）。
- [ ] **波形显示**：简单的数值波形绘制。

---

# 常见问题 (FAQ)

**Q: 找不到串口？**
A: 请检查设备是否连接，驱动是否安装。在 Windows 上查看设备管理器；在 Linux 上检查用户是否有 `dialout` 组权限。

**Q: GUI 无法启动？**
A: 请确认已安装 `requirements-gui.txt` 中的依赖。如果是在无图形界面的服务器上，请使用 CLI 模式。

**Q: 接收到的中文乱码？**
A: 请尝试在设置中切换 Encoding（如 `utf-8` 改为 `gbk`）。
