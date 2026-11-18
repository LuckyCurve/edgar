# edgar

给 Agent 用的 SEC EDGAR 数据 CLI：公司、filings、章节正文、XBRL facts、代理声明薪酬、内部人交易、全文搜索。

数据全部来自 SEC。只做清洗（空白、段落、表格、同期间去重），不做加工：没有比率、增速、同比和摘要。

## 安装

需要 Python 3.11+。

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
edgar --version
```

## 首次使用

SEC 要求访问 Archives 和全文搜索时，User-Agent 带真实联系人邮箱：

```bash
edgar config set user_agent "Your Name you@example.com"
edgar doctor
```

`doctor` 会检查 UA、缓存目录和 SEC 连通性。UA 可以放在 `EDGAR_USER_AGENT` 环境变量里，覆盖配置文件。

## 输出

所有命令输出 JSON。成功：

```json
{"ok":true,"command":"company","retrieved_at":"...","data":{...},"sources":[...],"next":{...}}
```

失败也输出 JSON，并带非零退出码：

```json
{"ok":false,"error":{"code":"not_found","message":"...","hint":"..."}}
```

退出码：`0` 成功，`2` 参数错误，`3` 找不到或有歧义，`4` 网络或被 SEC 拒绝，`5` 解析失败。

## 渐进式披露

默认只给摘要、元数据和下一步命令；需要细节时再展开：

| 需求 | 参数 |
|---|---|
| 读全文 | `--full` |
| 读下一段 | `--offset <字符位置>` |
| 只读某章 | `--section mda`（别名）、`--section item-7` |
| 只读某表 | `--table <索引或章节 id>` |
| 表格多看几行 | `--rows <n>` |
| 关缓存重取 | `--refresh` |
| 调试错误 | `--debug` |

`page.next_offset`、`next_offset` 和 `next.command` 会直接告诉你下一步该跑什么。

## 常见流程

**最近年报**

```bash
edgar company AAPL
edgar filing AAPL --form 10-K
edgar sections AAPL <accession>
edgar text AAPL <accession> --section mda --max-chars 4000
```

`company` 和 `filing` 的输出里已经带 accession，不用自己拼。`text` 返回的 `page.has_more` 为真时，用 `--offset` 续读。

**发展方向（MD&A / 业务 / 风险）**

```bash
edgar sections AAPL <accession>
edgar text AAPL <accession> --section business --max-chars 4000
edgar text AAPL <accession> --section risk --max-chars 4000
edgar text AAPL <accession> --section mda --offset 4000
```

**激励政策与高管薪酬**

```bash
edgar proxy AAPL
edgar proxy AAPL --section compensation-discussion-and-analysis
edgar proxy AAPL --section summary-compensation-table
edgar proxy AAPL --table summary-compensation-table
```

不带参数时只返回章节和表格的元数据，不含正文和整表。`--table` 一次给完整表格。

**五年、十年数据**

```bash
edgar concepts AAPL --query revenue
edgar facts AAPL --concept RevenueFromContractWithCustomerExcludingAssessedTax --period annual --since 2016-01-01 --limit 20
```

`facts` 默认按期间去重，只保留最新 filed。返回的 `last_end` 和数据过旧时的 warning 会提示是否换 tag。找不到概念时先 `concepts` 搜标签。

**内部人交易**

```bash
edgar insiders AAPL --limit 5
edgar insiders AAPL --limit 5 --parse
```

**全文搜索（2001 年后）**

```bash
edgar search '"artificial intelligence"' --ticker AAPL --form 10-K --limit 10
```

**保存原文**

```bash
edgar download AAPL <accession> --doc aapl-20250927.htm
edgar download AAPL <accession> --all -o ./filings
```

## 命令一览

| 命令 | 用途 |
|---|---|
| `resolve` | 按 ticker、CIK 或公司名片段找人 |
| `company` | 公司资料与最新关键 filing |
| `filings` | 列 filing，支持表单、日期、分页 |
| `filing` | 单个 filing 的元数据和文件列表 |
| `sections` | 列出章节 id，不含正文 |
| `text` | 读章节或全文，分页 |
| `tables` | 找表，再按索引读整表 |
| `proxy` | 代理声明里的薪酬章节和表格 |
| `facts` | XBRL facts，跨年 |
| `concepts` | 搜 XBRL 概念标签 |
| `search` | EDGAR 全文搜索 |
| `insiders` | Form 3/4/5 |
| `download` | 保存 SEC 原始文件 |
| `config` | 查看和修改本地设置 |
| `cache` | 查看和清理 HTTP 缓存 |
| `doctor` | 自检 UA、缓存和连通性 |

## 数据边界

- 章节和表格来自 filing 原文；表格保留合并单元格展开后的矩阵，不做单位换算。
- XBRL facts 原样返回 `val`、`unit`、`start`/`end`、`accn`、`form`、`filed`。
- `latest-filed` 只是同一期间重复报送时保留最后提交的一条，不是计算。
- 找不到、格式不支持、UA 不合规都会明确报错，不猜。

## 分层

- `edgar.base`：SEC 访问、解析、缓存、数据模型，不含 Agent 呈现逻辑。
- `edgar.cli`：面向 Agent 的 JSON 包装、分页、导航提示。
- 将来的 GUI 直接依赖 `edgar.base`。

## 开发

```bash
python -m unittest discover -s tests -v
```

真实 SEC 的端到端检查（需要已设置 UA）：

```bash
set EDGAR_LIVE=1
python -m unittest tests.test_live -v
```

## 已知限制

- 章节识别依赖正文标题样式，格式特殊的 filing 可能漏章；此时用 `text` 不加 `--section` 读全文。
- 代理声明表格按章节标题映射，非标准排版可能漏表。
- 全文搜索只覆盖 2001 年之后的 filing。
- PDF 文档不解析，只可通过 `download` 保存。
