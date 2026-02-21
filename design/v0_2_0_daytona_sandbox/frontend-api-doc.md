# Agent Skill 验证 API - 前端对接文档

> 版本: 2.0
> 日期: 2026-02-20

---

## 一、接口变更汇总

| 接口 | 变更类型 | 说明 |
|------|---------|------|
| `POST /api/admin/skills/upload` | 无变化 | 上传 Skill |
| `GET /api/admin/skills` | 无变化 | 列表查询 |
| `GET /api/admin/skills/{id}` | 响应字段新增 | 新增 `validation_tasks`, `last_full_test_at`, `full_test_results` |
| `POST /api/admin/skills/{id}/validate` | 无变化 | 单 Skill 验证 |
| `POST /api/admin/skills/{id}/revalidate` | 无变化 | 重新验证 |
| `POST /api/admin/skills/{id}/approve` | 无变化 | 批准入库 |
| `POST /api/admin/skills/{id}/reject` | 无变化 | 拒绝 |
| `DELETE /api/admin/skills/{id}` | 无变化 | 删除 |
| `GET /api/admin/skills/{id}/report` | 评分字段变化 | 移除 `resource_efficiency_score` |
| **新增** `POST /api/admin/skills/full-test` | 新增 | 全量测试 |
| `POST /api/admin/images/rollback` | **已废弃** | 返回 501 |

---

## 二、新增接口：全量测试

### 2.1 接口定义

```
POST /api/admin/skills/full-test
```

### 2.2 请求

无参数

### 2.3 响应

```json
{
  "status": "started",
  "message": "Full test started. Check skill statuses for progress."
}
```

### 2.4 说明

- 触发对所有已入库 Skills 的全量测试
- 每个 Skill 复用之前 3 个任务 + 新增 2 个 = 5 个任务
- 后台异步执行，需轮询各 Skill 状态查看进度
- 并发控制：最多同时测试 5 个 Skill

---

## 三、Skill 响应字段变更

### 3.1 新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `validation_tasks` | `array` | 验证时的任务列表（供全量测试复用） |
| `last_full_test_at` | `string` | 上次全量测试时间（ISO 8601） |
| `full_test_results` | `object` | 全量测试结果 |

### 3.2 评分字段变化

| 字段 | 状态 | 说明 |
|------|------|------|
| `completion_score` | 保留 | 权重 **50%**（原 40%） |
| `trigger_accuracy_score` | 保留 | 权重 **35%**（原 30%） |
| `offline_capability_score` | 保留 | 权重 **15%**（原 20%） |
| `resource_efficiency_score` | **已废弃** | 始终返回 `null` |
| `validation_score` | 保留 | 总分（0-100），通过阈值 70 |

---

## 四、TypeScript 类型定义

### 4.1 SkillResponse

```typescript
interface SkillResponse {
  skill_id: string;
  name: string;
  display_name?: string;
  description?: string;
  status: "pending" | "validating" | "approved" | "rejected";
  validation_stage?: "layer1" | "layer2" | "completed" | "failed";
  
  // 格式验证
  format_valid: boolean;
  format_errors: string[];
  format_warnings: string[];
  
  // 评分（3维）
  completion_score?: number;        // 权重 50%
  trigger_accuracy_score?: number;  // 权重 35%
  offline_capability_score?: number; // 权重 15%
  resource_efficiency_score?: null; // 已废弃，始终为 null
  validation_score?: number;        // 总分 0-100
  
  // 测试结果
  layer1_passed: boolean;
  layer2_passed: boolean;
  blind_test_passed?: boolean;
  network_test_passed?: boolean;
  offline_capable?: boolean;
  blocked_network_calls?: number;
  
  // 任务信息（新增）
  validation_tasks?: Task[];
  task_results?: TaskEvaluation[];
  
  // 全量测试（新增）
  last_full_test_at?: string;
  full_test_results?: FullTestResults;
  
  // 回归测试
  regression_results?: Record<string, RegressionResult>;
  
  // 依赖信息
  installed_dependencies?: string[];
  
  // 审核信息
  created_at?: string;
  validated_at?: string;
  approved_at?: string;
  rejected_at?: string;
  approved_by?: string;
  rejected_by?: string;
  reject_reason?: string;
}
```

### 4.2 Task

```typescript
interface Task {
  task_id: number;
  task: string;
  is_new?: boolean;  // 全量测试时新增的任务标记
}
```

### 4.3 TaskEvaluation

```typescript
interface TaskEvaluation {
  task_id: number;
  task: string;
  raw_score: number;       // 原始分数 1-5
  converted_score: number; // 转换分数 0-100
  reason: string;
  skill_used: string;
  correct_skill_used: boolean;
}
```

### 4.4 FullTestResults

```typescript
interface FullTestResults {
  passed: boolean;
  total_tested: number;
  failed_count: number;
  failed_skills: string[];
  results?: Record<string, SkillTestResult>;
}

interface SkillTestResult {
  passed: boolean;
  scores?: {
    completion_score: number;
    trigger_score: number;
    offline_score: number;
    overall: number;
  };
  error?: string;
}
```

### 4.5 RegressionResult

```typescript
interface RegressionResult {
  passed: boolean;
  score?: number;
  tasks_completed?: number;
  total_tasks?: number;
  error?: string;
}
```

---

## 五、验证报告变更

### 5.1 接口

```
GET /api/admin/skills/{id}/report
```

### 5.2 响应

```json
{
  "content": "# Skill 验证报告\n\n...",
  "content_type": "markdown"
}
```

### 5.3 评分表格变化

**旧版（4维）**：

| 维度 | 权重 |
|------|------|
| 任务完成度 | 40% |
| 触发准确性 | 30% |
| 离线能力 | 20% |
| 资源效率 | 10% |

**新版（3维）**：

| 维度 | 权重 |
|------|------|
| 任务完成度 | **50%** |
| 触发准确性 | **35%** |
| 离线能力 | **15%** |
| ~~资源效率~~ | ~~已移除~~ |

---

## 六、废弃接口

### 6.1 镜像回滚

```
POST /api/admin/images/rollback
```

**响应**：

```json
{
  "detail": "Image rollback is deprecated. Use Daytona Snapshots instead."
}
```

**状态码**：`501 Not Implemented`

**前端处理**：移除或禁用镜像回滚相关 UI

---

## 七、验证状态流转

```
┌─────────┐
│ pending │ ←─────────────────────┐
└────┬────┘                       │
     │ validate                   │
     ↓                            │
┌───────────┐                     │
│ validating│                     │
└─────┬─────┘                     │
      │                           │
      ├── passed ──→ completed ──→ approved
      │                           ↑
      │                           │
      └── failed ──→ failed ─────┘
                         │
                         │ revalidate
                         └───────────┘
```

### 7.1 状态说明

| 状态 | 说明 |
|------|------|
| `pending` | 待验证，可点击"开始验证" |
| `validating` | 验证中，显示进度 |
| `completed` | 验证完成，可审批 |
| `approved` | 已入库 |
| `rejected` | 已拒绝，可重新验证 |
| `failed` | 验证失败，可重试 |

---

## 八、前端 UI 建议修改

### 8.1 评分展示

**修改前**：
```
任务完成度: 40/100 (权重 40%)
触发准确性: 30/100 (权重 30%)
离线能力:   20/100 (权重 20%)
资源效率:   10/100 (权重 10%)
───────────────────────────
总分:       70/100
```

**修改后**：
```
任务完成度: 50/100 (权重 50%)
触发准确性: 35/100 (权重 35%)
离线能力:   15/100 (权重 15%)
───────────────────────────
总分:       75/100
```

### 8.2 全量测试按钮

**位置**：Skill 列表页顶部

**文案**：`全量测试`

**点击后**：
1. 调用 `POST /api/admin/skills/full-test`
2. 显示提示："全量测试已启动，请刷新查看进度"
3. 按钮变为禁用状态，显示 loading

### 8.3 任务列表展示（可选）

在 Skill 详情页展示 `validation_tasks`：

```
验证任务：
1. [任务描述1]
2. [任务描述2]
3. [任务描述3]
```

全量测试后：
```
验证任务：
1. [任务描述1]
2. [任务描述2]
3. [任务描述3]
4. [新增任务1] 🆕
5. [新增任务2] 🆕
```

### 8.4 移除资源效率显示

- 评分卡片中移除"资源效率"项
- 表格中移除 `resource_efficiency_score` 列

### 8.5 废弃镜像回滚

- 移除"镜像管理"或"回滚"相关页面/按钮
- 如需保留入口，显示"已迁移到 Daytona Snapshot"

---

## 九、错误码

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 / 状态不允许操作 |
| 401 | 未授权 |
| 403 | 非管理员 |
| 404 | Skill 不存在 |
| 500 | 服务器内部错误 |
| 501 | 接口已废弃 |

---

## 十、示例调用

### 10.1 上传并验证 Skill

```typescript
// 1. 上传
const formData = new FormData();
formData.append('file', zipFile);

const uploadRes = await fetch('/api/admin/skills/upload', {
  method: 'POST',
  body: formData,
  headers: { 'Authorization': `Bearer ${token}` }
});
const skill = await uploadRes.json();

// 2. 验证
const validateRes = await fetch(`/api/admin/skills/${skill.skill_id}/validate`, {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${token}` }
});
const result = await validateRes.json();

// 3. 检查结果
if (result.result.passed) {
  // 4. 批准
  await fetch(`/api/admin/skills/${skill.skill_id}/approve`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` }
  });
}
```

### 10.2 全量测试

```typescript
const res = await fetch('/api/admin/skills/full-test', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${token}` }
});
const result = await res.json();

if (result.status === 'started') {
  // 显示提示，轮询状态
  setTimeout(() => {
    // 刷新 Skill 列表查看进度
    fetchSkills();
  }, 5000);
}
```
