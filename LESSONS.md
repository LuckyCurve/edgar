# LESSONS

| 现象 | 根因 | 守住 |
|---|---|---|
| `www.sec.gov/Archives` 和 `efts.sec.gov` 返回 403 | SEC 要求 User-Agent 带真实联系人邮箱，`data.sec.gov` 不强制 | 请求前检查 UA 是否含 `@`，缺失就报错并给出 `edgar config set user_agent`；`doctor` 一并检查 |
| 10-K 章节被目录（TOC）截断或串到下一章 | 目录本身是表格，看起来像标题 | 章节边界只用正文文本（排除表格），并识别已知标题、字号和 h1–h3 |
| proxy 章节标题选到段落、边界跑到文末 | 代理声明靠视觉样式排版，没有稳定的 `Item` 标记 | 标题候选要求短、加粗或字号大；边界用已知薪酬标题、字号 ≥14、Proposal/Item/Part |
| `lxml` 报编码错误 | 字符串里带 `<?xml encoding=...?>` 声明，lxml 不接受 str | `parse_document` 一律先编码成 bytes 再解析 |
| 表格矩阵出现重复表头和大量空列 | colspan 被展开到每一列，空列也保留 | colspan 只填首格；全空列统一删除；测试锁住合并单元格行为 |
| 某些公司的主营收 tag 停在多年前 | 公司换过 XBRL tag，单看一个 tag 会得到旧数据 | `facts` 返回 `last_end` 并在数据过旧时提示用 `concepts --query` 换 tag |
| `GOOG` / `GOOGL` 查出两家公司或顺序不稳 | SEC ticker 表按 ticker 行展开，同一 CIK 重复出现 | ticker 索引按 CIK 合并，ticker 排序后再比较 |
| 终端里引号显示成乱码，以为解析坏了 | Windows 终端编码，不是数据问题 | 用 UTF-8 输出或看原始码点确认，不据此改解析 |
| 测试结束时出现 `HTTPResourceWarning` | `HTTPError` 没关闭 | 读完错误响应后显式 `close()` |
| 20-F 公司 `company` 的 latest 为空 | 默认只查 10-K / 10-Q / DEF 14A，外国私人发行人没有这些表单 | 默认同时查 20-F |
| 20-F 公司查 revenue 一个结果都没有 | 它们用 `ifrs-full` 而不是 `us-gaap`，默认 taxonomy 查空 | `detect_taxonomy` 自动选有数据的 taxonomy，CLI 不再写死 `us-gaap` |
| 20-F 的 risk / business / MD&A 别名指向错误 Item | 20-F Item 编号与 10-K 不同（3 风险、4 业务、5 OFR、6 董事） | 单独维护 `_TWENTY_F_ALIASES`，不混用 10-K 映射 |
| GGB / DECK 的章节或薪酬表整章缺失 | 标题本身是表格里的一行，早先直接跳过所有表格 | 非目录的表格标题也参与识别；目录行靠页码、点线或多单元格排除 |
| `Item 4 A.` 被当成 Item 4 的正文 | Item 后缀字母前有空格，正则没覆盖 | 正则允许空格，解析后去掉空白再归一化 |
| DECK 的 Summary Compensation Table 被算进 CD&A | 已知标题在表格里，没被加进章节边界集合，前一章一直延伸到文末 | 先判断已知标题，再决定是否跳过表格 |
| Windows 下输出含 ☐ / • 时命令崩溃 | 管道默认用 GBK 编码，JSON 里有 GBK 不支持的字符 | `main` 启动时把 stdout/stderr 重设为 UTF-8 |
