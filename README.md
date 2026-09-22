# 排班技能路由仿真台

在调整客服排班**之前**评估技能路由规则的离散事件仿真系统。前端 Angular 回放队列轨迹与坐席占用，
后端 Python FastAPI + SimPy 执行离散事件仿真，PostgreSQL 保存场景、随机种子与事件流。
**仅用于仿真评估，不接入真实电话。**

## 为什么这些数字可信（不是前端随机画图）

1. 所有随机量（到达时刻、耐心、通话时长）在仿真开始前由 `random.Random(seed)` **一次性预生成**
   （`backend/app/sim/engine.py::generate_call_plan`），路由过程中不调用任何随机数。
   → A/B 两套溢出规则在同种子下消费**完全相同的来电计划**。
2. 每次状态变化都落一条带**事件前/后队列快照 + 坐席快照**的事件：
   `ARRIVAL / ASSIGNED / CALL_END / WRAP_START / WRAP_END / ABANDONED / OVERFLOW /
   SHIFT_START / SHIFT_END / SHIFT_END_PENDING / EXPIRED`。
3. 指标（等待分布、放弃率、各技能服务水平、占用率……）由 `backend/app/metrics.py`
   **仅遍历事件列表**推导，函数签名里没有 RNG、没有仿真对象。
4. 每次运行对完整事件流计算 sha256；`POST /api/runs/{id}/verify` 用存储事件重算哈希。
5. 前端「指标面板」底部有**浏览器端独立复算对照**：不使用后端 metrics，直接遍历 events
   重算总数/放弃率/SL/p90 并逐格对账。

## 核心建模

- 来电：语言、技能、优先级（数值越大越优先）、分段泊松到达、耐心分布、通话时长分布、SLA 门槛。
- 坐席：(语言, 技能) 能力组合、`level`（最佳适配排序）、上班/下班时刻、个人整理时长覆盖。
- 路由：严格优先级 + 先来先服务；**最佳适配优先专才**（能力数少的坐席优先，保护通才不被挤占）。
- 溢出等待阈值：某类来电等待超过阈值后增加可接能力集合，派发器立即重扫队列（`OVERFLOW` 事件）。
- 放弃：耐心计时器到点 → `ABANDONED`；接通或溢出生效会中断相关计时器。
- 话后整理：`WRAP` 状态不可被选中，结束后重新派发。
- 上下班：`AVAILABLE` 到点立即下班；通话/整理中到点则 `SHIFT_END_PENDING`，服务结束后才真正登出
  （不强行挂断，跨班次交接的关键行为）。
- **一人一通**：派发器只从 `status == AVAILABLE` 集合选坐席，赋值瞬间置 `ON_CALL`；
  有结构性不变量测试 `test_agent_never_double_booked` 回放每个事件验证。
- horizon 之后不再产生新来电；仍排队者记 `EXPIRED`（不计放弃），进行中的通话/整理跑完。

## 内置样例

| 场景 | 证明什么 |
|---|---|
| 跨班次交接 | 晚高峰 1500 秒整点交接班：队列积压、早班坐席延迟下班、各技能 SLA/放弃率 |
| 稀缺技能 A / B | 同种子 42、ARRIVAL 完全一致，仅溢出规则不同：B 让普通来电等 30s 溢出给反欺诈专家，专家被挤占后 fraud VIP 的 SL 从 ~27% 跌到 ~20%，普通线 SL 25%→34% |

前端顶部「🔬 稀缺技能 A/B 对照」按钮一键出对比表。

## 运行

### 后端

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 方式一：PostgreSQL（推荐）
docker compose up -d
export DATABASE_URL="postgresql+psycopg2://sim:sim@127.0.0.1:5432/routing_sim"
uvicorn app.main:app --reload --port 8000

# 方式二：免数据库（自动回退本地 SQLite，事件以 JSON 文本存 Text 列）
uvicorn app.main:app --reload --port 8000
```

演示场景在启动时自动播种（固定 UUID + 种子 42）。

### 前端

```bash
cd frontend
npm install
npx ng serve        # http://localhost:4200，/api 已代理到 127.0.0.1:8000
```

### 测试

```bash
cd backend && python -m pytest -q     # 15 项：确定性、不并发、放弃/整理/溢出/跨班次、API 端到端
```

## API 摘要

- `GET  /api/scenarios` / `POST /api/scenarios`
- `POST /api/runs` `{scenario_id|config, seed}` → `run_id, event_hash`
- `GET  /api/runs/{id}` → metrics + 完整事件流（含每个事件前后快照）
- `POST /api/runs/{id}/verify` → 存储事件重算哈希是否一致
- `GET  /api/runs?scenario_id=` 历史运行（场景 × 种子可追溯）

## 前端怎么「暂停查因」

「事件回放」页：播放/暂停/单步/拖动进度条，或直接点左侧事件跳转。右侧展示该事件的人话解释、
**事件前→事件后队列快照**（每通来电的已等时长、已生效的溢出规则）和事件后坐席快照
（状态点、当前绑定来电、延迟下班标记）。
