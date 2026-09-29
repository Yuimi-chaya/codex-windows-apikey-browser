# Codex Windows API-key Browser Compatibility

**中文** | [English](#english)

这是一个独立于 Codex++ 的 Windows 脚本，用于修复特定版本 Codex Desktop / CUA 经 `mcp__cua_repl` 在纯 API key 登录下首次调用 Edge / Chrome 浏览器时出现的 `unsupported Codex auth method: apikey`。它把 Codex++ [PR #2335](https://github.com/BigPizzaV3/CodexPlusPlus/pull/2335) 中经过异机用户测试的浏览器标识回调适配提取成可独立运行、可还原的最小补丁。它不是官方工具，也不保证修复 [issue #2294](https://github.com/BigPizzaV3/CodexPlusPlus/issues/2294) 中所有浏览器故障。

## 作用与范围

脚本通过 Codex 的 `unified-computer-use` 插件描述文件，自动找出当前使用的 CUA runtime；不需要手工猜测 Codex App 安装目录。它**只修改**命中指纹的 `browser-service.mjs` 中一个回调绑定，并附加本仓库的短辅助函数。原文件、修改后的候选文件和恢复日志保存在 runtime 缓存之外。不会编辑 `codex.exe`、MSIX / ASAR、`config.toml`、认证文件、插件描述文件或浏览器扩展。

该回调只在已验证的 Edge / Chrome 正式版扩展、有效的当前 turn 与本地显式开关同时成立时要求原生请求标识；其他情况交还原本回调。它不伪造 ChatGPT 登录或凭据，不跳过网站限制、操作审批及用户停止机制。浏览器扩展可能长期保留已经启用的 `x-browser-agent: ChatGPT/<session-id>` 请求标识；**还原脚本不会关闭扩展内保留的标识**，目标网站可能继续收到该标头。

仅支持 Windows 下**文件 SHA-256 全部匹配**的 CUA 0.0.11 和 0.0.24 两组运行时。版本号相同但文件不同也会拒绝；以后 Codex 更新时可能需要新的适配。Mac、Computer Use、插件入口/缓存缺失、浏览器扩展安装、其他认证服务及所有站点的可用性不在范围内。

## 使用

需要 Windows 和 Python 3.10+，只使用标准库，不需要管理员权限或 pip 包。先保存工作并**正常退出 Codex App 与 Codex++**；脚本会在修改实际缓存前检查是否仍有 Codex/Codex++/CUA 进程，并拒绝在检测到运行中的进程时操作。它不能禁止另一人或另一进程**随后**启动应用，故请保持应用退出直到命令结束。**不要与 Codex++ 的“原生 Edge / Chrome 请求标识兼容”选项并用**：只要存在 Codex++ 的原生浏览器适配状态目录，`apply` 就会拒绝；此前使用过该选项的用户应使用 Codex++ 内建功能。在重新启用 Codex++ 原生补丁之前，应先运行本脚本 `restore`。首次使用前先启动过 Codex，使其生成 `unified-computer-use` 的 `.mcp.json`，再退出。

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

恢复会先禁用本地开关、核对原件与候选件，再还原服务内容及原修改时间；保留恢复文件以供排查。如果其他程序又改动了同一服务，脚本会拒绝覆盖并保留备份；不要手工删除备份或强制替换。用错 `--state-root`、恢复日志丢失却仍发现被修改的服务，也会**报错而不是假装恢复完成**。若所有权标记丢失但恢复日志完整，脚本会重建标记并完成还原；若标记冲突或日志无法校验，只关闭可识别的本地开关并报错，保留文件供排查。已被 Codex 更新删除的旧缓存不会被重新创建。若扩展已保留标识，还需在扩展自身的控制中处理；重启后才能检验新的 worker。

默认读取 `%CODEX_HOME%`（若设置）与 `%USERPROFILE%\.codex` 中的描述文件，实际 runtime 位于 `%LOCALAPPDATA%\OpenAI\Codex\runtimes\cua_node`，恢复资料默认在 `%LOCALAPPDATA%\CodexWinApiBrowserPatch`。便携/隔离环境可显式传 `--codex-home`、`--runtime-root`、`--state-root`；还原时务必复用应用时的 `--state-root`。脚本拒绝 junction、symlink、路径穿越、与 Codex++ 状态重叠的目录及 runtime 缓存内的备份目录。它不能对抗本机同一用户权限的恶意进程。

## 验证与来源

```powershell
py -3 -m unittest discover -s tests -v
```

默认测试使用合成文件，不执行 Codex 随附代码。仓库不包含 OpenAI 的原生 runtime、扩展、账号信息或密钥。可选的真文件测试通过环境变量指定**本机未修改过的** runtime 与由其生成的描述文件，只读取原文件，在临时目录中复制后修改/还原；不要把原生文件提交到仓库。该测试不等于真实浏览器验收。

如果当前服务已经由 Codex++ 修改，可用 `CODEX_BROWSER_FIXTURE_SERVICE` 指向其经过指纹验证的 `original.mjs` 备份；测试会从该备份复制服务文件，**不会**把任何东西写回它。设置 `CODEX_BROWSER_TEST_TEMP` 可让大文件临时副本落在指定磁盘。真文件测试同时需要 `CODEX_BROWSER_FIXTURE_RUNTIME` 和 `CODEX_BROWSER_FIXTURE_DESCRIPTOR`。

核心回调与辅助函数提取自 [CodexPlusPlus](https://github.com/BigPizzaV3/CodexPlusPlus) 的 Windows 原生浏览器兼容实现，沿用 GNU AGPL-3.0；详见 [LICENSE](LICENSE)。本仓库与 OpenAI 没有关联或背书。

## English

This standalone Windows script adapts the browser-identification callback used by specific Codex Desktop CUA runtimes. It targets the `unsupported Codex auth method: apikey` error observed on first use of the Edge/Chrome extension through `mcp__cua_repl` under API-key-only authentication. It extracts the narrow, reversible fix from [CodexPlusPlus PR #2335](https://github.com/BigPizzaV3/CodexPlusPlus/pull/2335); it is unofficial and does not fix every symptom in [issue #2294](https://github.com/BigPizzaV3/CodexPlusPlus/issues/2294).

The script discovers the selected runtime from Codex's generated `unified-computer-use/.mcp.json` descriptor. It changes **one** verified `browser-service.mjs` file, keeping the original bytes, candidate bytes, and recovery journal outside the cache. It does not edit the app package, `codex.exe`, config, credentials, plugin descriptors, or browser extensions. Only the exact Windows CUA 0.0.11 and 0.0.24 component fingerprints are supported; unknown versions fail closed.

The helper requires request identification only for the verified stable Edge/Chrome extensions during a valid turn with the explicit local control enabled. It does not impersonate an account or bypass site policy, operation approvals, or stop handling. **Restoring the service does not undo identification retained by the extension**: destination sites may still receive `x-browser-agent: ChatGPT/<session-id>` until the extension's own state is changed.

### Quick start

Install Python 3.10+ on Windows; no pip dependencies or elevation are needed. Let Codex generate the plugin descriptor once, then save your work and **fully quit Codex and Codex++** before applying or restoring this patch. The script refuses to change the real cache while it detects a running Codex/Codex++/CUA process; keep the apps closed until the command finishes, since it cannot prevent a later concurrent launch. Do **not** use it alongside Codex++'s native Edge/Chrome identification option: `apply` refuses any existing Codex++ native-browser state directory; users of that option should use the built-in implementation. Restore this standalone patch before enabling the Codex++ option again. From PowerShell in the repository directory:

```powershell
py -3 .\codex_browser_patch.py status
py -3 .\codex_browser_patch.py apply
py -3 .\codex_browser_patch.py status
```

Launch Codex afterward and test from a **fresh** browser tool context. `Prepared` only means the on-disk service was patched; it does not prove browser connectivity. To revert, quit Codex again, run `py -3 .\codex_browser_patch.py restore`, then inspect `status`. Restoration checks the journal and refuses to overwrite external edits; a wrong recovery directory or missing journal is an error when a modified service remains. A missing owner marker is reconstructed only from a verified journal; a conflicting marker or unverifiable journal disables recognizable local control and reports an error. Keep the backups if it reports a conflict. Removed Codex caches are never recreated.

By default the script checks `%CODEX_HOME%` (if set) and `%USERPROFILE%\.codex`, selects the native runtime beneath `%LOCALAPPDATA%\OpenAI\Codex\runtimes\cua_node`, and keeps recovery files under `%LOCALAPPDATA%\CodexWinApiBrowserPatch`. Use `--codex-home`, `--runtime-root`, and `--state-root` for a portable or isolated installation, and reuse the same state root for restoration. It rejects linked paths and recovery directories overlapping the runtime or Codex++ state. These checks are not a security boundary against a malicious process running as the same user.

Run `py -3 -m unittest discover -s tests -v` for synthetic tests. The optional genuine-byte test reads an unmodified local runtime and descriptor, then works exclusively in a temporary copy; it never executes proprietary runtime code. This repository redistributes no native binaries, extensions, credentials, or keys. The code is derived from CodexPlusPlus and licensed under [GNU AGPL-3.0](LICENSE). Not affiliated with or endorsed by OpenAI.

For the optional genuine-byte test, set `CODEX_BROWSER_FIXTURE_RUNTIME` and `CODEX_BROWSER_FIXTURE_DESCRIPTOR`. If the live service is already adapted, set `CODEX_BROWSER_FIXTURE_SERVICE` to a fingerprint-verified original backup; it is read only. `CODEX_BROWSER_TEST_TEMP` can place the temporary copy on a larger drive.
