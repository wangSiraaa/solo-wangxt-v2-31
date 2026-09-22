# 客服技能路由离散事件仿真系统

用于在调整排班前评估技能路由规则。系统模拟来电、排队、溢出、放弃、通话和通话后整理，不接入真实电话服务。

- 前端：Angular 19，重放后端事件、展示队列轨迹、坐席占用、等待分布与各技能服务水平。
- 后端：Python FastAPI + SimPy 离散事件仿真。
- 数据库：PostgreSQL，保存场景、随机种子和运行结果。
- 可复现：同一 `scenario_id + seed` 生成同一条事件序列；统计指标由事件日志重放计算，不由前端随机生成。

## 1. 启动

### Docker Compose

```bash
docker compose up --build
```

- API：http://localhost:8000/docs
- 前端开发服务器需单独启动（见下）；生产环境可把 `frontend/dist` 交给 Nginx。

### 本地启动后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL='postgresql+psycopg2://sim:sim@localhost:5432/call_sim'
uvicorn app.main:app --reload
```

首次启动会自动建表并写入两个内置样例。

### 本地启动前端

```bash
cd frontend
npm install
npm start
```

打开 http://localhost:4200。Vite/Angular dev server 会把 `/api` 代理到 `http://localhost:8000`。

## 2. 核心规则

### 来电

- 到达时间、语言、技能、优先级。
- 显式 `service_time`、`patience` 可固定，样例采用固定时长便于审计。
- 也支持 `arrival_profiles`，用随机种子生成泊松到达和指数服务/耐心时间。

### 坐席

- 多语言、多技能组合。
- `shift_start` / `shift_end` 上下班。
- 通话结束后进入坐席自己的 `wrap_time`。
- 坐席状态为 `busy` 或 `wrap` 时不接新电话；同一坐席不会同时服务两通电话。
- 到达下班时间时若正在通话，先完成当前通话和整理，再离线。

### 路由

- 支持 `priority_fifo` 与 `longest_waiting`。
- 优先级只改变排队顺序，不强占正在进行的通话。
- 先匹配来电原技能；溢出阈值到达后扩大允许技能集合。
- 在多名符合条件的坐席间，优先原技能匹配者，再选择技能/语言更少者，以保留稀缺通才。
- 必须满足语言要求；也可通过 `language_required=false` 关闭语言限制。

### 放弃

- 来电等待达到 `patience` 且未被接听时生成 `ABANDONED` 事件。
- 放弃事件会记录等待时长和耐心上限。

## 3. 事件即审计轨迹

每个事件包含：

- 时间、类型、消息。
- `reason.code/detail/factors`：解释为什么改变队列或坐席状态。
- `queue_before` / `queue_after`。
- `agent_before` / `agent_after` 和当时全部坐席快照。
- 来电对象及等待时长、溢出技能等。

事件类型至少包括：

- `ARRIVAL`
- `DISPATCH`
- `OVERFLOW_ELIGIBLE`
- `ABANDONED`
- `CALL_COMPLETED`
- `WRAP_COMPLETED`
- `SHIFT_START`
- `SHIFT_END`

前端时间轴只根据这些事件显示；暂停后可点击某个事件查看变化前后的队列和原因。后端 `compute_metrics(events)` 也只接收事件列表，因此等待分布、放弃率、服务水平和占用均可从同一份日志复算。

## 4. 指标

- 等待分布：`0–10s、10–20s、20–30s、30–60s、60–90s、90–120s、120–180s、180–300s、300s+`。
- 总体和分技能：
  - 来电量
  - 接听话务量
  - 放弃话务量
  - 放弃率
  - 20 秒服务水平（接听且等待 `<=20s` 的来电量 / 来电量）
  - 平均等待、最大等待
- 坐席占用：`(通话秒数 + 整理秒数) / 登录秒数`。

## 5. 两个用于证明统计来源的样例

运行：

```bash
cd backend
PYTHONPATH=. python evidence.py
```

### 5.1 跨班次 + 通话后整理：`cross_shift_wrap`

- 早班 0–100，晚班 110 上班，中间形成排班缺口。
- 早班坐席的最后通话在 90s 结束，但 20s 整理使其在 100s 下班前仍不可接新电话。
- `early-2` 在 20s 已排队，直到 110s 晚班坐席上班才接听，等待 90s。
- `late-1`、`late-2` 分别等待 100s、140s。
- 总体：4 通来电、0 放弃、20s 服务水平 25%、平均等待 82.5s。
- 晚班坐席占用 100%（150s 通话 + 60s 整理，210s 登录）。

这证明跨班次等待不是图表假数据，而是 `SHIFT_END`、`WRAP_COMPLETED`、`SHIFT_START`、`DISPATCH` 等事件连续作用的结果。

### 5.2 稀缺技能挤占 + 优先级 + 溢出：`scarce_skill_priority_and_overflow`

- 唯一通才在 0s 先服务只能由其处理的 tech 来电。
- billing 话务在其忙碌期间排队，低耐心的 `bill-wait` 40s 放弃。
- `support-overflow` 40s 可溢出到 billing，69s 可溢出到 tech。
- 100s 通才整理结束，更高优先级的 support 溢出话务抢先得到通才，较早到达的 billing 话务在 110s 放弃。
- billing：2 来电量、100% 放弃、SL20 0%。
- support：70s 接听，SL20 0%，并明确记录使用溢出技能 tech。
- tech：0s 接听，SL20 100%。

这证明优先级不会强占当前通话，但会决定稀缺坐席释放后的下一通电话；溢出阈值也可在事件中逐步追溯。

## 6. API

- `GET /api/scenarios`：场景列表。
- `POST /api/scenarios`：保存场景和默认种子。
- `GET /api/scenarios/{id}`：读取场景。
- `POST /api/simulations`：运行并持久化仿真结果。
  - Body：`{"scenario_id": 1, "seed": 9901}`
  - 也可传完整 `scenario` 做临时仿真。
- `GET /api/simulations/{run_id}`：读取已保存运行。
- `GET /health`：健康检查。

## 7. 测试

```bash
cd backend
pytest -q
```

测试覆盖：

1. 同场景同种子事件级一致。
2. 同一坐席不能同时接两通电话，整理期间阻塞分配。
3. 跨班次队列轨迹和统计值。
4. 稀缺技能、优先级、溢出和放弃原因。
5. 指标可只从事件日志重新计算。
6. API 持久化场景和运行结果。
