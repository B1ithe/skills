# webconf-audit 最终设计方案

## 1. 目标

构建一个 **Web 服务器配置安全审计技能包**（可被任意 agent 加载）：

1. **自研** Nginx / Apache 配置解析（不依赖、不封装 gixy）
2. **按预配置规则扫描有缺陷的配置**（不限于 CRLF；CRLF / Host 信任 / 路径混淆 / 危险反代等均为规则包）
3. 支持后续扩展 Tomcat 等
4. 支持 **单跳** 问题与 **多跳组合** 问题（如 Nginx → Apache 的 decode/normalize 差）
5. **代码**做确定性分析；**LLM（可选）**做组合补强、缺口覆盖与解释

当前已落地：解析器 + Nginx 变量原语 + gixy 对齐规则包。引擎定位是**通用规则扫描框架**，不是 CRLF 专用工具。

---

## 2. 设计原则

| 原则 | 说明 |
|---|---|
| 编排与判定分离 | 入口文档只编排；解析/规则在代码里 |
| Adapter 只管解析（+ 变量原语） | 服务器文法互不共用 |
| 规则引擎统一产出 Signal / Finding | 旧「facts」并入引擎，称 **Signal** |
| 薄语义，不厚 IR | 不建跨服务器完整配置 AST |
| 组合靠 Pipeline + Signal + Behavior | 不要求各 hop 信号对称 |
| Signal id 语义优先 | 服务器名放 hop/issuer；私有观察才用 `nginx.*` / `apache.*` |
| 先垂直后抽象 | 单跳 Checker 可暂合并；组合多了再拆 Analyzer/Evaluator |

---

## 3. 目录结构

```text
webconf-audit/                          # skill root (portable; any agent skills dir)
├── SKILL.md                            # orchestration entry
├── requirements.txt
│
├── adapters/                           # 服务器相关（解析 + 变量原语）
│   ├── base.py                         # Adapter 接口、ParseResult
│   ├── common/
│   │   ├── model.py                    # 共享 AST 节点
│   │   └── pathmap.py                  # include 路径映射
│   ├── nginx/
│   │   ├── raw_parser.py
│   │   ├── parser.py
│   │   └── variables.py                # （待做）$uri 等 can_contain 原语
│   ├── apache/
│   │   ├── raw_parser.py
│   │   └── parser.py
│   └── tomcat/                         # 占位
│
├── engine/                             # 规则引擎（观察 / 判定 / 组合）
│   ├── model.py                        # Signal, Finding, HopResult, PipelineResult
│   ├── runner.py                       # 单跳 / pipeline 调度
│   ├── behaviors.py                    # profiles + 轻量推断
│   ├── analyzers/                      # AST → Signals（不定 severity）
│   │   ├── nginx/
│   │   └── apache/
│   ├── evaluators/                     # Signals → Findings（单跳）
│   │   ├── nginx/
│   │   └── apache/
│   └── chain/                          # 多 HopResult → Findings
│
├── profiles/                           # 默认 HTTP 行为档案
│   ├── nginx-default.yaml
│   └── apache-default.yaml
│
├── references/                         # 知识与合同（编排层 / LLM 消费）
│   ├── design.md                       # 本文
│   ├── architecture.md                 # 短摘要
│   ├── bundle-schema.md                # （待做）LLM 输入合同
│   └── chain-patterns.md               # （待做）
│
├── fixtures/                           # 解析/规则回归样本
│   ├── nginx/
│   └── apache/
│
└── scripts/                            # 仅薄 CLI，禁止堆业务
    ├── parse_config.py                 # 已做
    └── audit.py                        # （待做）
```

**硬约束**：`scripts/` 不得放 nginx/apache 解析或规则逻辑。

---

## 4. 逻辑架构

```text
用户 / 编排层（任意 agent）
    │
    ├─ 确认 Pipeline（单 hop 或 nginx → apache → …）
    │
    ▼
┌──────────────────────────────────────────────┐
│ adapters                                     │
│   conf → AST                                 │
│   nginx.variables → 原语（可否含 \n 等）        │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ engine.runner                                │
│                                              │
│  per hop:                                    │
│    analyzers  → Signals                      │
│    evaluators → Findings（single_hop）        │
│    behaviors  ← profiles + 轻量推断           │
│                                              │
│  pipeline:                                   │
│    chain/*    → Findings（chain）             │
└──────────────────────┬───────────────────────┘
                       ▼
              PipelineResult
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
   代码确认 Findings           LLM 辅助层（可选）
   (confidence=high)           补 behavior / 组合叙事 /
                               remediation（低置信候选）
```

---

## 5. 领域模型

### 5.1 Pipeline / Hop

```text
Pipeline
  hops: [Hop, ...]                 # 有序

Hop
  id, kind                         # nginx | apache | tomcat | …
  role                             # edge | middle | origin
  config_roots[]
  ast                              # adapter 输出
  # 以下由 engine 填充：
  # signals, findings, behaviors
```

拓扑来源：用户显式声明 > 部署推断 > 默认单 hop。

### 5.2 Signal（原「facts」，属引擎）

中性、可组合的原子观察；**不是**最终告警。

```text
Signal
  id          # 语义 id，见命名规范
  hop_id
  issuer      # 可选：nginx.uri_injection（谁发出）
  evidence[]  # file/line/snippet
  data{}
  confidence  # 代码多为 high
```

### 5.3 Finding

```text
Finding
  id, severity, title, remediation
  category: single_hop | chain
  hop_ids[]
  based_on[]     # signal ids
  evidence[]
  confidence     # high | medium | low
```

### 5.4 Behaviors（组合常用）

来自 `profiles/*` + 少量 AST 推断，例如：

- URI 解码 / normalize  
- CL vs TE 优先级  
- 上游 keepalive  
- 头内 CRLF 策略  
- Host / X-Forwarded-* 信任方式  

后跳常常 **没有对称 conf signal**，靠 behaviors 参与组合。

### 5.5 IR 策略

- **薄**：Signal + Behavior，不做跨服务器厚配置树  
- 各服务器保留自有 AST；analyzer 负责「翻译」成 Signal  

---

## 6. 规则引擎结构（通用缺陷扫描，非 CRLF 专用）

引擎按**预置规则包**扫描配置缺陷；每类缺陷 = Analyzer（观察）± Evaluator（定级）± Chain（组合）。

| 组件 | 输入 | 输出 | 说明 |
|---|---|---|---|
| **Analyzers** | AST + VarModel | Signals | 只观察，不定级 |
| **Evaluators** | Signals + Behaviors | Findings | 单跳判定 |
| **Chain** | [HopResult…] | Findings | 跨跳判定 |

规则类别示例（可扩展，不限于下列）：

| 类别 | 示例 Signal / 规则 |
|---|---|
| HTTP splitting / CRLF | `upstream.request_line.includes_decoded_uri` |
| Host spoofing（gixy） | `client.host.trusted_as_upstream_host` |
| 路径混淆 / 前缀逃逸 | `upstream.proxy.prefix_location_pass_through` + apache slash behavior |
| 危险反代 / SSRF 面 | proxy_pass 用户可控 host 等 |
| 其它 gixy 类 | alias traversal、add_header 丢失… |

加新漏洞 ≈ 加 analyzer/evaluator（或 chain），**不必改 parser 或引擎骨架**。

早期允许一个 Plugin 同时产出 signals + findings；runner 仍先汇聚 signals，再跑 chain。

```text
HopResult = {
  hop, signals, findings, behaviors
}
```

---

## 7. Signal 命名规范

### 7.1 默认：语义 id，不嵌服务器名

```text
upstream.request_line.includes_decoded_uri
upstream.header.includes_decoded_uri
client.host.trusted_as_upstream_host
```

来源用 `hop.kind` / `issuer`，便于：

```text
front.has(upstream.request_line.includes_decoded_uri)
```

### 7.2 私有、不可对齐：加服务器前缀

```text
nginx.map.variable_inherits_decoded_uri
apache.allowoverride.all_in_directory
```

### 7.3 仅某服务器有的配置

- **只在该 hop 上发信号**；另一侧没有 ≠ 错误，只是 `has(...)` 为假  
- 不要为对称而伪造 Apache 同名 signal  
- 组合常见模式：`front.signal` + `back.behavior`（不必两边都有 conf 对称物）  

### 7.4 语义可对齐但指令不同

由各自 analyzer 翻译到**同一通用 id**；若永远无法对齐，则保持私有前缀或仅单跳。

---

## 8. 代码 vs LLM（可选）

| 代码 | LLM（可选） |
|---|---|
| Nginx/Apache 解析、include、path_map | 组合洞叙事与优先级 |
| `$uri` / 捕获组 `can_contain` | Host 信任是否可利用（业务语境） |
| Analyzers / Evaluators / Chain（条件可代码化时） | 条件暂不能代码化的 chain 候选 |
| 高置信 Finding | remediation 文案；无 parser 时的片段审阅 |

LLM 只消费 **PipelineResult / hop_bundle**（摘要 + signals + behaviors + 热片段）。  
**不得无证据覆盖代码 high Finding。**

---

## 9. 解析器（已定且部分已实现）

| 服务器 | 技术 | 说明 |
|---|---|---|
| Nginx | pyparsing（自研，类 gixy 思路） | 与 gixy 无依赖 |
| Apache | 行向 tokenizer + section 栈 | 无分号、`<Section>`；与 nginx **共享 AST 形状与 Adapter 接口，不共用法文** |
| Tomcat | 未来 XML | 占位 |

CLI：

```bash
python scripts/parse_config.py nginx|apache <entry> [--path-map SRC=DST] [--pretty]
```

---

## 10. 演进路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 0–3 | 目录契约 + Nginx/Apache **仅解析** + fixtures | **已完成** |
| Phase 4 | `adapters/nginx/variables.py` + engine 骨架（model/runner） | **已完成** |
| Phase 5 | nginx analyzers + evaluators（gixy parity 规则包） | **已完成** |
| Phase 6 | behaviors/profiles 接通；chain（nginx→apache）；可选 LLM 层 | 下一步 |
| Phase 7 | 更多单跳规则；Tomcat；LLM 契约完善 | 待定 |

---

## 11. 验收锚点（回顾）

解析阶段：

- [x] 目录：adapters 分服务器 / scripts 仅入口 / engine 占位  
- [x] Nginx、Apache → JSON AST  
- [x] USM path-map include 展开  
- [x] 无 gixy、无规则引擎实现  

规则引擎阶段：

- [x] Signal/Finding/HopResult 合同稳定  
- [x] 单跳 http_splitting：vulnerable fixture / crlf-desyncs 命中；`safe_request_uri` 不误报  
- [x] gixy simply 76/76 对齐（含 host_spoofing；不含应用层 XFH 信任）  
- [ ] 至少一条 nginx→apache chain 规则可跑（可用 profile 模拟后跳 behavior）  


---

## 12. 总览一句话

> **Adapter 解析；Engine 用 Analyzer→Signal、Evaluator→Finding、Chain 跨跳；Signal 语义命名、私有加前缀、允许不对称；Behavior 补后跳；编排层调度；LLM 可选补缺口。先解析、后单跳、再组合。**
