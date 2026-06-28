英文版见 [rfc.md](rfc.md).

# Firewalla Local Skill — 架构设计

## 概述

工具以本地 Python CLI 运行，通过 SSH 连接 Firewalla 设备，发出只读 Redis 命令，在本地文件系统上产出结构化 JSON 工件。无服务端组件，无守护进程，除写入的工件外无持久状态。

```
用户机器                            Firewalla
┌─────────────┐     SSH + key     ┌──────────┐
│  CLI (Python) │ ◄──────────────► │  Redis     │
│               │   只读命令        │            │
│  JSON 工件     │                   │            │
│  → 文件系统    │                   └──────────┘
└─────────────┘
```

## 传输层

SSH 连接通过以下三种机制之一配置，按顺序检查：
1. `.firewalla.local.json` — 本地配置文件，含 `ssh_alias` 键。
2. `FIREWALLA_SSH_ALIAS` 环境变量 — SSH config 别名。
3. `FIREWALLA_HOST` / `FIREWALLA_SSH_USER` / `FIREWALLA_SSH_KEY` 环境变量 — 直接连接参数。

CLI 调用系统 `ssh` 命令并在 Firewalla 上执行 `redis-cli --raw`。连接生命周期为每次命令：每次调用启动 SSH、运行有界只读读取管线、捕获 stdout/stderr、然后退出。

## 只读白名单

任何 Redis 命令发出前，CLI 先对照硬编码白名单检查：

```
SCAN, HGETALL, ZRANGE, ZREVRANGE, ZRANGEBYSCORE, ZREVRANGEBYSCORE, ZCARD, GET, MGET, PING
```

白名单之外的命令在 SSH 传输前被拒绝并报错。这是代码层强制，非 Firewalla 侧 ACL。即使 Firewalla Redis 实例被错误配置为可写，工具也无法发出写入。

## Dry-Run 守卫

CLI 默认 dry-run。未提供 `--execute` 时：
- 不建立 SSH 连接。
- Redis 命令打印到 stdout 而非发送。
- 不写入工件文件。

这提供安全的预览路径。执行任何真实操作必须显式传递 `--execute`。

## 采集器契约

每条命令对应一个采集器模块，定义：
- 要读取的 Redis key。
- 要发出的 Redis 命令。
- 如何将原始 Redis 响应转换为输出 JSON schema。
- 本地原始输出处理。

采集器为无状态函数。它们构造只读远端 Redis 命令，解析 `redis-cli --raw` 输出，应用命令级参数，并返回保留真实本地值的可 JSON 序列化对象。

### 告警时间窗口

告警采集器先读 `alarm_active`，再扫描 `alarm_archive`（zset），以 `--candidate-limit` 限制扫描范围。对每个候选项获取 `_alarm:<aid>` 和 `_alarmDetail:<aid>`。时间过滤使用负载层 `timestamp` 和 `alarmTimestamp` 字段，而非 zset score。这避免了 Redis zset score 语义与告警自身时间戳之间的时钟偏差。`--since-days` 转换为 Unix 时间戳阈值；仅包含负载时间戳在阈值之后的告警。

### 设备身份解析

设备采集器读取所有 `host:mac:*` key。对每个设备提取运行名称和发现别名。当首选运行名称（`name`、`dhcpName` 等中最高优先级的非空值）与任何发现别名不一致时，设置 `identity_conflict` 标志。该标志在输出中而非自动解析，因为正确解析依赖操作者知识。

## 本地原始工件

采集器保留真实设备名、IP、MAC、域名、告警消息和 flow 字段。这是可靠关联和实际网络调查所需。生成的工件属于 git 忽略的本地路径。公开文档和测试使用 fake fixture，而不是转换后的真实数据。

## 告警归因语义

归因将告警映射到设备。归因模块仅考虑告警负载中的源/客户端字段：

- `device`（顶层设备标识）
- `p.device.id`、`p.device.ip`、`p.device.mac`、`p.device.name`
- `p.flows[].device`

基础设施字段（`p.intf.*`、接口标识、观测元数据）被排除。这些字段描述哪个 Firewalla 接口观测到流量，而非哪个客户端生成流量。包含它们会导致将网络基础设施误归因为告警源。

归因输出包含 `device_summary` 字段，含来自设备清单的可读设备身份信息。

## 工件 Schema

采集命令包含命令自己的数据和 `collection` 元数据对象：

```json
{
  "alarms": [],
  "collection": {
    "source": "ssh_redis",
    "local_raw": true,
    "since_days": 3,
    "include_archive": true,
    "candidate_limit": 2000
  }
}
```

`cluster`、`device-summary`、`attribute`、`active-devices` 等分析命令读取这些 JSON 工件，并在输出中保留输入的采集元数据。

### 活跃设备调查 Schema

`active-devices` 是本地工件关联命令。它读取设备清单，并可选读取告警工件，不连接 Firewalla。命令使用 `--since-days` 基于 `lastActiveTimestamp` 筛选设备，通过与 `attribute` 相同的源感知归因语义附加告警上下文，并输出 `investigation_indicators` 作为调查提示。告警上下文关联到具体设备记录，而不是显示名称，因此多块手表这类重名设备会保持区分。

```json
{
  "active_devices": [
    {
      "device_id": "Example Device",
      "device_key": "host:mac:aa:bb:cc:dd:ee:ff",
      "last_active_timestamp": 2000000000,
      "last_active_age_days": 0.01,
      "device_summary": {},
      "alarm_context": {"alarm_count": 1, "categories": {}, "types": {}},
      "investigation_indicators": ["network_security_alarm"]
    }
  ],
  "summary": {
    "active_device_count": 1,
    "indicator_counts": {}
  }
}
```

## 安全边界

代码中强制执行以下硬边界：

1. **只读 Redis。** 白名单在 Redis 命令调度层检查。无代码路径可绕过。
2. **默认 dry-run。** `--execute` 是任何实时操作的必要标志。无该标志，不打开 SSH 连接。
3. **不操作 iptables、策略、服务文件。** 工具无相关代码路径。
4. **不对外传输数据。** 所有工件写入本地文件系统路径。无网络上传。
5. **Git 忽略私有数据。** `.gitignore` 覆盖 `reports/`、`.firewalla_dumps/`、`.firewalla.local.json`、`.env` 和 SSH config。

## 未来写入路径约束

任何未来写入功能必须通过独立 RFC 引入，需用户在配置和命令调用两级显式同意，并优先使用官方 Firewalla 机制（App 支持的告警/通知调节、本地 Encipher API）而非直接 Redis 写入。直接 Redis 写入存在与 Firewalla 软件内部状态假设不同步的风险。

## 测试架构

测试分为两层：

**离线测试**（`-m "not live"`）：无需 Firewalla 连接。覆盖 dry-run 行为、白名单执行、变更拒绝、配置解析、本地原始输出、时间戳过滤、告警归因规则、身份冲突处理和 JSON schema 一致性。使用模拟 Redis 响应。

**在线测试**（`-m live`）：由 `FIREWALLA_LIVE_TESTS=1` 控制。需要本地网络上的真实 Firewalla，且 SSH 访问已配置。端到端覆盖所有只读命令。不修改任何 Firewalla 状态。

## 依赖

- **Python 3.11+** — 运行时。
- **pytest** — 测试框架。
- **uv** — 包管理与 venv。
