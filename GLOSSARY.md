# GLOSSARY

| 词 | 意思 |
|---|---|
| company / registrant | 在 SEC 注册的公司，由 CIK 唯一标识；同一公司可有多个 ticker |
| CIK | SEC 给公司的 10 位编号 |
| filing | 一次提交，例如年报、季报、代理声明；由 accession number 唯一定位 |
| accession | filing 的编号，形如 `0000320193-26-000026` |
| form | filing 的类型，如 `10-K`、`10-Q`、`8-K`、`DEF 14A`、`4` |
| document | filing 里的一个文件；一份 filing 可含多个 HTML、XML、图片 |
| section | 从 filing 正文识别出的章节，如 Item 7 (MD&A)、Risk Factors、CD&A |
| concept / tag | XBRL 里一个会计科目名，如 `RevenueFromContractWithCustomerExcludingAssessedTax` |
| fact | 某个 concept 在某个期间、某个单位下的一个报送值，带来源 accession |
| period | fact 覆盖的期间：年报、季报、年初至今、时点值 |
| latest-filed | 同一期间被多份 filing 重复报送时，保留最后提交的那条 |
| proxy | 股东大会委托书（通常 DEF 14A），高管薪酬和激励计划的主要来源 |
| full-text search | SEC 对 2001 年以来 filing 正文的检索，不是 XBRL 数据查询 |
| 渐进式披露 | 默认只给摘要和导航，调用方按需再取全文、表格或下一页 |
