# 字段与计算方式

输入是一个 UTF-8 JSON 对象，可带 BOM，最大 256 KiB、合计 1,200 个数组条目。每组源行号从 1 起，指数组原始位置。时间使用带偏移的 ISO 文本，按上海时区转成分钟精度，所有区间为左闭右开。普通字符串 ID 保留前导零。`cutoff` 为事件统计截点，等于截点的事件纳入本班。

| 数据集 | 字段 | 含义 |
|---|---|---|
| `windows` | `rink`,`start`,`end`,`kind` | 场地、营业开始与结束、`paid` 收费或 `waived` 豁免 |
| `passes` | `pass`,`owner`,`rink`,`start`,`end`,`allowance` | 权益号、队伍、冰面、生效时段，本有效段可用分钟整数 |
| `events` | `booking`,`revision`,`timestamp`,`action` | 订单号、正整数修订号、发生时刻、动作 |
| `events` | `owner`,`rink`,`start`,`end` | 新订与改单必填。撤销只读身份键和修订信息 |
| `closures` | `rink`,`start`,`end`,`reason`,`reported`,`by` | 封场冰面与时段、停用依据、上报时刻、上报方；可缺省 |
| `migrations` | `booking`,`rink`,`start`,`end` | 受影响预订的新时段去向；与 `todo` 二选一，可缺省 |
| `migrations` | `booking`,`todo` | 受影响预订的待办去向，覆盖该单未落实的停用分钟 |
| `debit.rows` | `day`,`start`,`end`,`debit`,`cash`,`waived`,`disputed` | 本地自然日、分钟区间及分钟分解 |
| `debit.rows` | `windows`,`passes`,`peers`,`codes` | 决定结果的营业行、权益行、冲突订单行、原因码 |
| `balance.tally` | `booked`,`difference`,`voucher_difference` | 有效预订分钟、分钟差、券已用差 |
| `migration.rows` | `key`,`owner`,`rink`,`start`,`end`,`line` | 原预订快照：订单号、队伍、冰面、原时段与源行号 |
| `migration.rows` | `affected`,`basis`,`basis_lines` | 停用分钟、停用依据（理由 · 上报方 时刻）、封场源行号 |
| `migration.rows` | `slot`,`moves`,`todo`,`moved`,`pending`,`status` | 新时段或待办、结构化新时段、待办文本、迁移分、待办分、落实状态 |
| `migration` | `closures`,`sealed`,`shift_balanced` | 封场登记、迁移单是否封存可交接、全班是否对平 |
| `manifest` | `version`,`created_at`,`cutoff`,`elapsed_ms`,`input_sha256`,`result_sha256` | 规则版、封存时刻、结算截点、耗时和两种摘要 |

## 裁决

先以升序修订重放每单。版本号从 1 连续递增，发生时刻随版号单调不降。第一版必须新订，中间只接受改单，最后一版可撤销。重复版本内容相同时保留最早发生时间。同版内容相异时整单暂停。有效订单进入计分钟，取消和没有可识别分钟的单据进入复核清单。

以午夜、营业窗端点、同场同队券版本端点切分每单。每段只可得到一种营业分类。两个异类营业窗重叠，或多个权益同时有效，相交片段进入争议。两个预订共同占用同一冰面时，两单一并待核对。收费段依开场时间逐段使用权益预算，按源版本全班累计。该段余额不够的部分记自付，豁免不扣权益。相同时点以冰面和订单号稳定排序。

每个有效预订分钟拆为扣券、自付、豁免、争议。每券的核发分钟等于已用加剩余。复核账按单检查，另检查全场扣券总数和券已用总数。

封场段与有效预订时段的交集为停用分钟，同一冰面多个封场段按并集计。每个受影响预订的去向为新时段、待办或两者兼有：新时段分钟数逐项累计，待办覆盖该单剩余停用分钟，二者合计须恰好等于停用分钟。新时段不得落入封场段，不得与同冰面有效预订及其他新时段重叠。迁移行与封场行按完整内容去重，重跑同批复用原批次。全班对平且迁移无阻断证据时迁移单封存，`/api/runs/{运行号}/ticket` 导出与页面同一结果的正式凭证；未对平或仍重叠时该端点拒绝出具，草稿仍随批次归档可查。

凭证导出一个 JSON，内含原始交换文本、完整阶段结论及运行清单。`input_sha256` 对上传原字节计算，`result_sha256` 对排序字段的 UTF-8 JSON 结果计算。样例中的现金列是待自付分钟，价格由票务系统维护。
