# Codex Windows API-key Browser Compatibility

**中文** | [English](#english)

这是一个可独立运行、并能识别 Codex++ 恢复记录的 Windows 工具，用于修复特定版本 Codex Desktop / CUA 经 `mcp__cua_repl` 在纯 API key 登录下首次调用 Edge / Chrome 浏览器时出现的 `unsupported Codex auth method: apikey`。它沿用 Codex++ [PR #2335](https://github.com/BigPizzaV3/CodexPlusPlus/pull/2335) 中经过异机用户测试的浏览器标识回调适配。它不是官方工具，也不保证修复 [issue #2294](https://github.com/BigPizzaV3/CodexPlusPlus/issues/2294) 中所有浏览器故障。

## 作用与范围

脚本通过 Codex 的 `unified-computer-use` 插件描述文件，自动找出当前使用的 CUA runtime；不需要手工猜测 Codex App 安装目录。它**只修改**命中指纹的 `browser-service.mjs` 中一个回调绑定，并附加本仓库的短辅助函数。原文件、修改后的候选文件和恢复日志保存在 runtime 缓存之外；检测到经过完整验证的 Codex++ 状态时，复用其原件、候选件、journal 与控制文件，并受其监控锁和事务锁保护。不会编辑 `codex.exe`、MSIX / ASAR、`config.toml`、认证文件、插件描述文件或浏览器扩展。

该回调只在已验证的 Edge / Chrome 正式版扩展、有效的当前 turn 与本地显式开关同时成立时要求原生请求标识；其他情况交还原本回调。它不伪造 ChatGPT 登录或凭据，不跳过网站限制、操作审批及用户停止机制。浏览器扩展可能长期保留已经启用的 `x-browser-agent: ChatGPT/<session-id>` 请求标识；**还原脚本不会关闭扩展内保留的标识**，目标网站可能继续收到该标头。

仅支持 Windows 下**文件 SHA-256 全部匹配**的 CUA 0.0.11 和 0.0.24 两组运行时。版本号相同但文件不同也会拒绝；以后 Codex 更新时可能需要新的适配。Mac、Computer Use、插件入口/缓存缺失、浏览器扩展安装、其他认证服务及所有站点的可用性不在范围内。

## 使用

需要 Windows；EXE 版无需安装 Python，源码脚本需要 Python 3.10+，只使用标准库。无需管理员权限。先保存工作并**正常退出 Codex App 与 Codex++（包括 launcher 和 manager）**；工具会在访问可能被占用的服务文件前检查运行进程，并在写入时再次检查。若 Codex++ 原生浏览器监控或事务仍持有锁，操作也会拒绝。它不能禁止其他进程**随后**启动应用，故请保持应用退出直到操作结束。首次使用前先启动过 Codex，使其生成 `unified-computer-use` 的 `.mcp.json`，再退出。

**Codex++ 设置的生命周期：**管理器保存选项后，launcher 在**下次启动**才读取该选项；只重启 Codex App 不一定停止 Codex++ 的监控。若以后仍通过 Codex++ launcher 启动，必须保持其内建“原生 Edge / Chrome 请求标识兼容”选项开启；选项关闭时，launcher 下次启动会恢复原服务，即使本工具刚执行了解锁。本工具不会更改你的设置，也不会宣称能绕过正在运行的监控。未知 Codex++ journal、缺失锁、无效/未完成的监控回执、双重活动补丁和外部修改均会拒绝覆盖。

### 图形界面

目前已发布的 `v0.1.0-beta.1` **尚不支持**上述 Codex++ 状态互操作；本分支的 `v0.1.0-beta.2` 是待真人验收的本地候选，不要把旧版 EXE 当作新版测试。从 [Releases](https://github.com/Yuimi-chaya/codex-windows-apikey-browser/releases) 获取已发布版本时，核对发布页的 SHA-256。界面自动读取当前用户注册的 Codex App 版本与安装路径，并通过 Codex 数据目录中的插件描述文件定位实际 CUA 服务。**安装路径仅供识别；补丁修改的是界面显示的“实际补丁文件”，而不是安装包。**“选择 Codex 路径”用于选择包含插件缓存的 `.codex` **数据目录**，不接受 App 安装目录。未签名的 EXE 可能触发 Windows 安全警告。

状态检查只读，会显示当前匹配的是独立工具还是 Codex++ 的恢复资料。退出 Codex / Codex++ 后，点击“解锁浏览器”，重新打开 Codex，并在新的浏览器工具上下文中测试。需要撤销时，再次退出应用并点击“恢复原件”。状态“已解锁（磁盘状态）”只表明文件与相应恢复记录一致，**不是**浏览器连接成功的证明。未知组件指纹会阻止解锁，但完整可信的恢复记录仍可能允许还原；其他修改、恢复资料冲突或运行进程会阻止写入。不要直接替换文件或删除恢复资料。

### 命令行

在本仓库目录打开 PowerShell：

```powershell
py -3 .\codex_browser_patch.py status
py -3 .\codex_browser_patch.py apply
py -3 .\codex_browser_patch.py status
```

`apply` 需要用户显式执行；`status` 只读。看到 `Prepared` 后再打开 Codex，在新的浏览器工具上下文里测试 Edge / Chrome；`Prepared` 本身**不是**实际连通或网页操作成功的证明。若没有生成描述文件、路径不一致、任何指纹未知、备份冲突或已有其他工具修改同一服务，脚本会拒绝覆盖。

要撤销本脚本的修改，先退出 Codex，再运行：

```powershell
py -3 .\codex_browser_patch.py restore
py -3 .\codex_browser_patch.py status
```

恢复会校验对应的原件与候选件，禁用本地控制并还原服务内容及原修改时间；保留恢复文件以供排查。如果其他程序又改动了同一服务，脚本会拒绝覆盖并保留备份；不要手工删除备份或强制替换。独立状态下用错 `--state-root`、恢复日志丢失却仍发现被修改的服务，也会**报错而不是假装恢复完成**。独立状态所有权标记丢失但恢复日志完整时，脚本会重建标记；Codex++ 状态则必须有可验证的监控回执、事务锁和 journal。已被 Codex 更新删除的旧缓存不会被重新创建。若扩展已保留标识，还需在扩展自身的控制中处理；重启后才能检验新的 worker。

默认读取 `%CODEX_HOME%`（若设置）与 `%USERPROFILE%\.codex` 中的描述文件，实际 runtime 位于 `%LOCALAPPDATA%\OpenAI\Codex\runtimes\cua_node`。没有 Codex++ 状态时，独立恢复资料在 `%LOCALAPPDATA%\CodexWinApiBrowserPatch`；存在经过验证的 Codex++ 状态时使用 `%USERPROFILE%\.codex-session-delete\native-browser-identification`。便携/隔离环境可显式传 `--codex-home`、`--runtime-root`、`--state-root`；独立状态还原时务必复用应用时的 `--state-root`。脚本拒绝 junction、symlink、路径穿越、重叠的恢复目录及 runtime 缓存内的备份目录。它不能对抗本机同一用户权限的恶意进程。

## 验证与来源

```powershell
py -3 -m unittest discover -s tests -v
```

默认测试使用合成文件，不执行 Codex 随附代码。仓库不包含 OpenAI 的原生 runtime、扩展、账号信息或密钥。可选的真文件测试通过环境变量指定**本机未修改过的** runtime 与由其生成的描述文件，只读取原文件，在临时目录中复制后分别测试独立状态与 Codex++ journal 往返；不要把原生文件提交到仓库。该测试不等于真实浏览器验收。

如果当前服务已经由 Codex++ 修改，可用 `CODEX_BROWSER_FIXTURE_SERVICE` 指向其经过指纹验证的 `original.mjs` 备份；测试会从该备份复制服务文件，**不会**把任何东西写回它。设置 `CODEX_BROWSER_TEST_TEMP` 可让大文件临时副本落在指定磁盘。真文件测试同时需要 `CODEX_BROWSER_FIXTURE_RUNTIME` 和 `CODEX_BROWSER_FIXTURE_DESCRIPTOR`。

核心回调与辅助函数提取自 [CodexPlusPlus](https://github.com/BigPizzaV3/CodexPlusPlus) 的 Windows 原生浏览器兼容实现，沿用 GNU AGPL-3.0；详见 [LICENSE](LICENSE)。本仓库与 OpenAI 没有关联或背书。

构建 EXE 需要在单独虚拟环境安装 `requirements-build.txt` 中固定版本的 PyInstaller。`build.ps1 -WorkRoot <独立工作目录>` 把虚拟环境、临时文件、依赖下载报告和构建缓存放在该目录；可用 `-PackageIndex <镜像地址>` 仅为本次安装指定镜像，不修改全局 pip 配置。不要把工作目录指向源仓库。构建结果在 `<工作目录>\dist\CodexBrowserUnlocker.exe`。构建不安装、关闭或重启 Codex，也不修改活动 CUA 服务。

## English

This Windows tool runs independently while recognizing verified Codex++ recovery state. It adapts the browser-identification callback used by specific Codex Desktop CUA runtimes, targeting `unsupported Codex auth method: apikey` on first use of the Edge/Chrome extension through `mcp__cua_repl` under API-key-only authentication. It uses the narrow, reversible fix from [CodexPlusPlus PR #2335](https://github.com/BigPizzaV3/CodexPlusPlus/pull/2335); it is unofficial and does not fix every symptom in [issue #2294](https://github.com/BigPizzaV3/CodexPlusPlus/issues/2294).

The tool discovers the selected runtime from Codex's generated `unified-computer-use/.mcp.json` descriptor. It changes **one** verified `browser-service.mjs` file, keeping the original bytes, candidate bytes, and recovery journal outside the cache. With a fully verified Codex++ state, it uses that state's journal, control, and monitor/transaction locks instead of claiming a second active patch. It does not edit the app package, `codex.exe`, config, credentials, plugin descriptors, or browser extensions. Only the exact Windows CUA 0.0.11 and 0.0.24 component fingerprints are supported; unknown versions fail closed.

The helper requires request identification only for the verified stable Edge/Chrome extensions during a valid turn with the explicit local control enabled. It does not impersonate an account or bypass site policy, operation approvals, or stop handling. **Restoring the service does not undo identification retained by the extension**: destination sites may still receive `x-browser-agent: ChatGPT/<session-id>` until the extension's own state is changed.

### Quick start

The Windows EXE needs no Python installation; the source script requires Python 3.10+ and no pip dependencies or elevation. Let Codex generate the plugin descriptor once, then save your work and **fully quit Codex and Codex++ (including launcher and manager)** before applying or restoring this patch. The tool checks running processes before accessing possibly locked service files, then checks again before writing; an active Codex++ monitor or transaction lock also blocks a write. Keep the apps closed until completion, since a later concurrent launch cannot be prevented.

Codex++ takes a snapshot of its native Edge/Chrome compatibility setting when its launcher starts. If you continue launching through Codex++, leave that built-in option **enabled**; with it disabled, the next launcher start restores the service even after this tool unlocks it. This tool neither changes that setting nor overrides an active monitor. Unknown Codex++ journals, missing locks, invalid/unfinished monitor receipts, simultaneous active adapters, and external edits fail closed.

The published `v0.1.0-beta.1` does **not** have Codex++ interoperability; this branch's `v0.1.0-beta.2` is a local candidate awaiting human validation. Verify the published SHA-256 when downloading a published EXE from [Releases](https://github.com/Yuimi-chaya/codex-windows-apikey-browser/releases). The GUI shows the registered Codex App version/install location for identification and the **actual CUA service file** it will change. "选择 Codex 路径" selects a `.codex` **data directory** containing the plugin cache, not the app installation. Status checks are read-only and identify the recovery owner. Fully quit Codex/Codex++ before clicking "解锁浏览器" (apply) or "恢复原件" (restore). An "已解锁（磁盘状态）" status confirms the on-disk patch and recovery record, **not** browser connectivity. Unknown component fingerprints block unlocking, but a fully verified recovery record may still allow restoration; external edits, recovery conflicts, and running processes block writes.

Alternatively, from PowerShell in the repository directory:

```powershell
py -3 .\codex_browser_patch.py status
py -3 .\codex_browser_patch.py apply
py -3 .\codex_browser_patch.py status
```

Launch Codex afterward and test from a **fresh** browser tool context. `Prepared` only means the on-disk service was patched; it does not prove browser connectivity. To revert, quit Codex again, run `py -3 .\codex_browser_patch.py restore`, then inspect `status`. Restoration checks the matching journal, disables its control, restores original bytes and timestamp, and refuses external edits. A wrong standalone recovery directory or missing journal is an error when a modified service remains. A missing standalone owner marker is reconstructed only from a verified journal; Codex++ state requires a valid monitor receipt, transaction lock, and verified journal. Keep backups on any conflict. Removed Codex caches are never recreated.

By default the script checks `%CODEX_HOME%` (if set) and `%USERPROFILE%\.codex`, selecting the native runtime beneath `%LOCALAPPDATA%\OpenAI\Codex\runtimes\cua_node`. Standalone recovery files live under `%LOCALAPPDATA%\CodexWinApiBrowserPatch`; verified Codex++ recovery uses `%USERPROFILE%\.codex-session-delete\native-browser-identification`. Use `--codex-home`, `--runtime-root`, and `--state-root` for a portable or isolated installation, and reuse the same standalone state root for restoration. It rejects linked paths and recovery directories overlapping each other or the runtime. These checks are not a security boundary against a malicious process running as the same user.

Run `py -3 -m unittest discover -s tests -v` for synthetic tests. The optional genuine-byte test reads an unmodified local runtime and descriptor, then exercises both recovery formats exclusively in temporary copies; it never executes proprietary runtime code. This repository redistributes no native binaries, extensions, credentials, or keys. The code is derived from CodexPlusPlus and licensed under [GNU AGPL-3.0](LICENSE). Not affiliated with or endorsed by OpenAI.

For the optional genuine-byte test, set `CODEX_BROWSER_FIXTURE_RUNTIME` and `CODEX_BROWSER_FIXTURE_DESCRIPTOR`. If the live service is already adapted, set `CODEX_BROWSER_FIXTURE_SERVICE` to a fingerprint-verified original backup; it is read only. `CODEX_BROWSER_TEST_TEMP` can place the temporary copy on a larger drive.

To build from source, install the pinned PyInstaller version in an isolated environment with `build.ps1 -WorkRoot <dedicated-directory>`. An optional `-PackageIndex <mirror-url>` affects only that installation, not global pip configuration. The script places its virtual environment, temporary files, dependency download report, and build cache outside the repository and writes `<work-root>\dist\CodexBrowserUnlocker.exe`. It never installs, stops, restarts, or patches a running Codex instance.
