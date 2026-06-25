英文版见 [README.md](README.md).

# Firewalla Local Skill

面向 Firewalla 设备的 AI-first CLI 工具与根技能，基于本地优先、只读的可见性与分析。完全在本机通过 SSH 运行——不需云端中转，不需 MSP API。

**只读设计。** 工具仅对 Firewalla 发起只读 Redis 命令。不修改防火墙规则、策略、Redis 状态、iptables 或系统服务。

**隐私优先。** 所有 JSON 工件默认私有。需要分享工件（文档、issue、PR）时，使用 `--privacy redacted` 将真实值替换为稳定的匿名 token，同时保留 schema key 以支持跨记录关联。

## 安装

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e '.[dev]'
```

## 快速开始

创建 `.firewalla.local.json`（已 git 忽略）：

```json
{"ssh_alias": "firewalla"}
```

或使用环境变量：`FIREWALLA_SSH_ALIAS`、`FIREWALLA_HOST`、`FIREWALLA_SSH_USER`、`FIREWALLA_SSH_KEY`。

所有命令默认 dry-run，需加 `--execute` 才连接 Firewalla。

```bash
firewalla-skill health --execute
firewalla-skill devices --json --all --execute
firewalla-skill alarms --json --since-days 7 --include-archive --all --execute
firewalla-skill active-devices --devices reports/devices_all_latest.json --alarms reports/alarms_last7d_latest.json
firewalla-skill snapshot --execute
```

## 隐私模式

| 模式 | 行为 |
|------|------|
| `private`（默认） | 保留真实值。工件留在被忽略的路径中。 |
| `redacted` | 值替换为稳定 token，例如 `<mac:0123456789>`、`<ip:0123456789>`、`<bname:0123456789>`。Schema key 保持不变。同一值映射到同一 token，关联查询可用。 |

分享公开文档、issue 或 PR 时使用 `--privacy redacted`。

## 安全模型

- SSH 连接 Firewalla，密钥认证。
- 只读 Redis 命令白名单：`SCAN`、`HGETALL`、`ZRANGE`、`ZREVRANGE`、`ZRANGEBYSCORE`、`ZREVRANGEBYSCORE`、`ZCARD`、`GET`、`MGET`、`PING`。
- 不写 Redis。不改 iptables。不改策略。不改服务文件。
- 默认 dry-run；`--execute` 才发起真实连接。

## 命令

| 命令 | 用途 |
|------|------|
| `health` | 主机名、运行时间、Redis PING |
| `devices --json --all` | 从 `host:mac:*` 采集设备清单 |
| `alarms --json --since-days N --all` | 采集活跃和归档告警，基于时间窗口过滤 |
| `flows` | 读取系统或指定 MAC 的近期流量记录 |
| `snapshot` | 生成有界、AI 可读的快照 |
| `dump-format` | 输出本地原始和脱敏格式转储 |
| `summary` | 从快照或实时读取生成确定性 JSON 摘要 |
| `cluster` | 告警可操作性聚类 |
| `device-summary` | 当前与历史设备清单分桶和类型计数 |
| `attribute` | 源感知的告警到设备归因 |
| `active-devices` | 最近 N 天活跃设备调查上下文 |
| `resolve-device` | 脱敏工件诊断辅助，将匿名 token 映射回设备字段 |

## 告警归因规则

归因仅使用源/客户端字段：`device`、`p.device.id`、`p.device.ip`、`p.device.mac`、`p.device.name`、`p.flows[].device`。排除基础设施/接口字段（如 `p.intf.*`），这些描述的是 Firewalla 观测接口而非客户端源。

设备显示 ID 优先当前运行名称（`name`、`dhcpName`、`localDomain`、`sambaName`、`ssdpName`）。过期发现别名（`bname`、`bonjourName`、`pname`）为次要来源。当运行名称与别名不一致时发出 `identity_conflict`。

## 活跃设备调查

采集设备和告警工件后运行 `active-devices`：

```bash
firewalla-skill devices --execute --all --json --output reports/devices_all_latest.json
firewalla-skill alarms --execute --since-days 7 --include-archive --all --json --output reports/alarms_last7d_latest.json
firewalla-skill active-devices --devices reports/devices_all_latest.json --alarms reports/alarms_last7d_latest.json --since-days 7 --output reports/active_devices_last7d.json
```

输出包含活跃设备、当前身份字段、别名、detect 元数据、告警数量/类别/类型，以及 `identity_conflict`、`network_security_alarm`、`bandwidth_alarm` 等调查提示。

## 告警处理指引

- 不应仅为减少告警噪声创建流量/网络规则。
- 游戏/视频类告警通常是通知噪声。
- 大上传和异常带宽告警需结合设备和时间上下文判断。
- UPNP、BRO_NOTICE、DUAL_WAN、INTEL 类告警在忽略前应予以审核。
- 优先使用官方/App 支持的告警调节或本地 Encipher API，而非直接写 Redis。

## 被忽略的路径

以下路径已被 git 忽略，包含真实本地数据：

- `reports/`
- `.firewalla_dumps/`
- `.firewalla.local.json`
- `.env`
- SSH 配置文件

## 测试

```bash
# 离线测试
python -m pytest -q -m "not live"

# 在线测试（需要 Firewalla 连接）
FIREWALLA_LIVE_TESTS=1 python -m pytest -q -m live
```

## 许可证

MIT
