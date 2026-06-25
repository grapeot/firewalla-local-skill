英文版见 [prd.md](prd.md).

# Firewalla Local Skill — 产品需求

## 目标

提供本地优先、AI 友好的 CLI，对 Firewalla 设备进行只读可见性采集。核心场景是用户授权的 AI 在用户本机进行分析。不依赖云端，不需要付费 MSP API。

工具产出结构化 JSON 工件，供 AI agent 直接消费——设备清单、带归因的告警历史、流量记录和系统状态的有界快照。这些工件支持自动化分析，且对 Firewalla 无任何写入权限。

## 用户

- 希望借助 AI 分析网络状态但不将数据发送到云服务的 Firewalla 用户。
- 在用户本地机器上运行的 AI agent，消费结构化 Firewalla 数据进行告警分类和网络诊断。

## 范围

- 基于 SSH 访问 Firewalla Redis。
- 受严格白名单约束的只读 Redis 命令执行。
- 覆盖完整 CLI 命令集的 JSON 工件生成：健康检查、设备、告警、流量、快照、格式转储、摘要、聚类、设备摘要、归因和设备解析。
- 两种隐私模式：`private`（真实值，私有路径）和 `redacted`（稳定匿名 token，可分享）。
- 带时间窗口和候选数量上限的告警采集。
- 源感知的设备归因与身份冲突检测。
- 离线与在线测试套件。
- 面向脱敏工件的 `resolve-device` 诊断工具。

## 非目标

- Firewalla 配置或策略变更。
- Redis 写入、iptables 修改或服务文件变更。
- 云端分析或数据外传。
- 实时监控或常驻守护进程。
- MSP API 集成（可选且需付费；工具承认其存在但不依赖）。
- 超出 Redis key 直接暴露范围的历史设备状态重建。

## 数据模型

### 设备

存储于 Firewalla Redis 的 `host:mac:*` key 下。每个设备携带运行标识（`name`、`dhcpName`、`localDomain`、`sambaName`、`ssdpName`）和发现别名（`bname`、`bonjourName`、`pname`）。MAC 地址、IP 分配、DHCP 指纹和厂商元数据在可用时一并采集。

### 告警

三个关键空间：
- `alarm_active` — 当前未解决的告警。
- `alarm_archive` — 已解决告警记录，以 zset 存储。
- `_alarm:<aid>` 和 `_alarmDetail:<aid>` — 每条告警的负载 key，含结构化 JSON。

时间窗口过滤使用负载字段 `timestamp` 和 `alarmTimestamp`，而非 Redis zset score。`--candidate-limit` 参数限制扫描的归档条目数。

### 流量

按系统或设备 MAC 组织的近期流量记录，暴露连接元数据、字节计数、应用分类和端口信息。

### 报告

每条命令产出确定性 JSON。`snapshot` 命令生成有界、AI 可读的聚合数据，可直接传入 LLM 上下文。`summary` 命令从快照或实时有界读取计算确定性摘要。

## 设备身份语义

设备显示 ID 解析优先当前运行名称而非过期发现别名。优先级链：
1. `name` — Firewalla 中当前名称
2. `dhcpName` — DHCP 提供的主机名
3. `localDomain` — mDNS/LLMNR 本地域名
4. `sambaName` — Samba/NetBIOS 名称
5. `ssdpName` — SSDP 发现的名称
6. `bname` / `bonjourName` / `pname` — 过期发现别名（次要来源）

当运行名称与别名不一致时（例如设备已改名但旧 Bonjour 名称仍缓存），工具发出 `identity_conflict` 标记，而非静默选择一侧。

## 隐私模型

**私有模式（默认）：** 工件包含真实设备名称、IP、MAC、域名和告警消息。工件存储在 git 忽略路径中（`reports/`、`.firewalla_dumps/`、`.firewalla.local.json`、`.env`），不进入仓库。

**脱敏模式：** 所有可识别值替换为稳定的确定性 token，按类型加前缀（`<mac:...>`、`<ip:...>`、`<bname:...>`、`<domain:...>`）。Schema key 原样保留。Token 映射对每个值确定——同一 MAC 始终映射到同一 token，使脱敏工件之间的关联查询可用。脱敏模式用于文档、issue 和 PR 中的分享。

## 验收标准

- 所有命令在 dry-run 模式下无需 Firewalla 连接即可成功执行。
- 所有命令通过 `--execute` 对真实 Firewalla 成功执行。
- `devices` 返回完整设备清单，包含所有运行标识和别名。
- `alarms` 返回指定时间窗口内的活跃和归档告警，受候选上限约束。
- `alarms` 的时间过滤使用负载时间戳，而非 zset score。
- `attribute` 正确区分源/客户端字段与基础设施/接口字段。
- 运行名称与发现别名不一致时发出 `identity_conflict`。
- 脱敏模式产出确定性 token：相同输入产生相同 token，schema key 不变。
- 只读白名单被强制执行：任何写命令被拒绝。
- 离线测试无需 Firewalla 连接即可通过。
- 在线测试在 `FIREWALLA_LIVE_TESTS=1` 下通过。
- 公开仓库不包含任何真实本地数据。
