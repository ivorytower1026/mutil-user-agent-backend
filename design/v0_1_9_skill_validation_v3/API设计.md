# API 设计

> v0.1.9 Skill 验证与管理

---

## 一、端点总览

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| `POST` | `/api/admin/skills/upload` | 上传 Skill zip | admin |
| `GET` | `/api/admin/skills` | 列表（可过滤状态） | admin |
| `GET` | `/api/admin/skills/{skill_id}` | 详情 | admin |
| `GET` | `/api/admin/skills/{skill_id}/report` | 验证报告 | admin |
| `POST` | `/api/admin/skills/{skill_id}/approve` | 批准 | admin |
| `POST` | `/api/admin/skills/{skill_id}/reject` | 拒绝 | admin |
| `POST` | `/api/admin/skills/{skill_id}/revalidate` | 重新验证 | admin |
| `DELETE` | `/api/admin/skills/{skill_id}` | 删除 | admin |
| `GET` | `/api/admin/images` | 镜像版本列表 | admin |
| `POST` | `/api/admin/images/rollback` | 回滚镜像版本 | admin |

---

## 二、请求/响应模型

### 2.1 Skill 列表项

```python
from pydantic import BaseModel

class SkillListItem(BaseModel):
    skill_id: str
    name: str
    display_name: str | None
    description: str | None
    status: str
    validation_stage: str | None
    validation_score: float | None
    layer1_passed: bool | None
    layer2_passed: bool | None
    runtime_image_version: str | None
    created_at: str
    validated_at: str | None
```

### 2.2 Skill 详情

```python
class SkillDetail(SkillListItem):
    skill_path: str
    format_valid: bool
    format_errors: list[str]
    format_warnings: list[str]
    
    # 第一层验证结果
    blind_test_passed: bool | None
    skill_triggered: bool | None
    trigger_accuracy: float | None
    network_test_passed: bool | None
    offline_capable: bool | None
    blocked_network_calls: int | None
    execution_metrics: dict | None
    task_results: list[dict] | None
    
    # 评分
    usability_score: int | None
    trigger_accuracy_score: int | None
    offline_capability_score: int | None
    resource_efficiency_score: int | None
    
    # 回归结果
    regression_results: dict | None
    
    # 依赖信息
    installed_dependencies: dict | None
    
    # 审批信息
    approved_by: str | None
    approved_at: str | None
    rejected_by: str | None
    rejected_at: str | None
    reject_reason: str | None
```

### 2.3 验证报告

```python
class TaskResult(BaseModel):
    task: str
    completed: bool
    skill_used: str | None
    correct_skill_used: bool
    execution_time_ms: int
    output_summary: str | None

class BlindTestResult(BaseModel):
    passed: bool
    skill_triggered: bool
    trigger_accuracy: float
    task_results: list[TaskResult]

class NetworkTestResult(BaseModel):
    passed: bool
    blocked_network_calls: int
    offline_capable: bool

class ExecutionMetricsResult(BaseModel):
    cpu_percent: float
    memory_mb: float
    disk_read_mb: float
    disk_write_mb: float
    execution_time_sec: float

class ScoreDetail(BaseModel):
    usability: int
    trigger_accuracy: int
    offline_capability: int
    resource_efficiency: int
    overall: float

class Layer1Report(BaseModel):
    passed: bool
    blind_test: BlindTestResult
    network_test: NetworkTestResult
    execution_metrics: ExecutionMetricsResult
    scores: ScoreDetail
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]

class RegressionSkillResult(BaseModel):
    passed: bool
    score: int | None
    tasks_completed: int | None
    error: str | None

class Layer2Report(BaseModel):
    passed: bool
    regression_results: dict[str, RegressionSkillResult]
    total_skills_tested: int
    failed_skills: list[str]

class ValidationReport(BaseModel):
    skill_id: str
    skill_name: str
    validation_stage: str
    runtime_image_version: str | None
    
    format_check: FormatCheckResult
    layer1_result: Layer1Report | None
    layer2_result: Layer2Report | None
    
    installed_dependencies: dict | None
    validated_at: str | None
    warning: str | None

class FormatCheckResult(BaseModel):
    passed: bool
    errors: list[str]
    warnings: list[str]
```

### 2.4 上传响应

```python
class UploadResponse(BaseModel):
    skill_id: str
    name: str
    status: str
    format_valid: bool
    format_errors: list[str]
    message: str
```

### 2.5 镜像版本

```python
class ImageVersionItem(BaseModel):
    version: str
    skill_id: str | None
    skill_name: str | None
    created_at: str
    is_current: bool

class RollbackRequest(BaseModel):
    target_version: str

class RollbackResponse(BaseModel):
    current_version: str
    target_version: str
    affected_skills: list[str]  # 会被标记为 rollback_pending 的 skill
    message: str
```

---

## 三、端点详情

### 3.1 上传 Skill

```http
POST /api/admin/skills/upload
Content-Type: multipart/form-data
Authorization: Bearer {token}

file: skill.zip
```

**成功响应** `200`:
```json
{
  "skill_id": "uuid-xxx",
  "name": "csv-analyzer",
  "status": "pending",
  "format_valid": true,
  "format_errors": [],
  "message": "Skill uploaded, validation started"
}
```

**格式错误** `400`:
```json
{
  "code": "INVALID_SKILL_FORMAT",
  "message": "Missing required file: SKILL.md"
}
```

**重名错误** `409`:
```json
{
  "code": "SKILL_ALREADY_EXISTS",
  "message": "Skill 'csv-analyzer' already exists"
}
```

---

### 3.2 列表查询

```http
GET /api/admin/skills?status=pending&page=1&size=20
Authorization: Bearer {token}
```

**Query 参数**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `status` | string | - | 过滤状态（可选） |
| `validation_stage` | string | - | 过滤验证阶段（可选） |
| `page` | int | 1 | 页码 |
| `size` | int | 20 | 每页数量 |

**响应**:
```json
{
  "skills": [
    {
      "skill_id": "uuid-xxx",
      "name": "csv-analyzer",
      "display_name": "CSV Analyzer",
      "description": "CSV 数据分析工具",
      "status": "pending",
      "validation_stage": "completed",
      "validation_score": 87.5,
      "layer1_passed": true,
      "layer2_passed": true,
      "runtime_image_version": null,
      "created_at": "2026-02-16T10:00:00Z",
      "validated_at": "2026-02-16T10:10:00Z"
    }
  ],
  "total": 10,
  "page": 1,
  "size": 20
}
```

---

### 3.3 Skill 详情

```http
GET /api/admin/skills/{skill_id}
Authorization: Bearer {token}
```

**响应**:
```json
{
  "skill_id": "uuid-xxx",
  "name": "csv-analyzer",
  "display_name": "CSV Analyzer",
  "description": "CSV 数据分析工具",
  "status": "pending",
  "validation_stage": "completed",
  "skill_path": "skills_pending/csv-analyzer",
  
  "format_valid": true,
  "format_errors": [],
  "format_warnings": ["未找到 requirements.txt"],
  
  "layer1_passed": true,
  "layer2_passed": true,
  
  "blind_test_passed": true,
  "skill_triggered": true,
  "trigger_accuracy": 1.0,
  
  "network_test_passed": true,
  "offline_capable": true,
  "blocked_network_calls": 0,
  
  "execution_metrics": {
    "cpu_percent": 15.2,
    "memory_mb": 128.0,
    "disk_read_mb": 2.5,
    "disk_write_mb": 1.2,
    "execution_time_sec": 45.0
  },
  
  "task_results": [
    {
      "task": "分析 data.csv 文件，统计每列的平均值",
      "completed": true,
      "skill_used": "csv-analyzer",
      "correct_skill_used": true,
      "execution_time_ms": 2340
    }
  ],
  
  "usability_score": 85,
  "trigger_accuracy_score": 100,
  "offline_capability_score": 100,
  "resource_efficiency_score": 75,
  
  "regression_results": {
    "skill-a": {"passed": true, "score": 85},
    "skill-b": {"passed": true, "score": 90}
  },
  
  "installed_dependencies": {
    "pip": {"pandas": "2.0.0"}
  },
  
  "runtime_image_version": null,
  
  "created_at": "2026-02-16T10:00:00Z",
  "validated_at": "2026-02-16T10:10:00Z",
  "approved_by": null,
  "approved_at": null
}
```

---

### 3.4 验证报告

```http
GET /api/admin/skills/{skill_id}/report
Authorization: Bearer {token}
```

**成功响应（验证完成）**:
```json
{
  "skill_id": "uuid-xxx",
  "skill_name": "csv-analyzer",
  "validation_stage": "completed",
  "runtime_image_version": null,
  
  "format_check": {
    "passed": true,
    "errors": [],
    "warnings": ["未找到 requirements.txt"]
  },
  
  "layer1_result": {
    "passed": true,
    "blind_test": {
      "passed": true,
      "skill_triggered": true,
      "trigger_accuracy": 1.0,
      "task_results": [
        {
          "task": "分析 data.csv 文件，统计每列的平均值",
          "completed": true,
          "skill_used": "csv-analyzer",
          "correct_skill_used": true,
          "execution_time_ms": 2340,
          "output_summary": "成功统计了 5 列数据..."
        },
        {
          "task": "读取 sales.csv，计算月度销售额总和",
          "completed": true,
          "skill_used": "csv-analyzer",
          "correct_skill_used": true,
          "execution_time_ms": 1890,
          "output_summary": "计算得出月度销售额..."
        },
        {
          "task": "检查 users.csv 的数据完整性",
          "completed": true,
          "skill_used": "csv-analyzer",
          "correct_skill_used": true,
          "execution_time_ms": 1560,
          "output_summary": "发现 3 条数据存在空值..."
        }
      ]
    },
    "network_test": {
      "passed": true,
      "blocked_network_calls": 0,
      "offline_capable": true
    },
    "execution_metrics": {
      "cpu_percent": 15.2,
      "memory_mb": 128.0,
      "disk_read_mb": 2.5,
      "disk_write_mb": 1.2,
      "execution_time_sec": 45.0
    },
    "scores": {
      "usability": 85,
      "trigger_accuracy": 100,
      "offline_capability": 100,
      "resource_efficiency": 75,
      "overall": 90.0
    },
    "summary": "该 Skill 在离线环境下表现优秀，Agent 能准确识别并调用",
    "strengths": [
      "触发准确性高，3个任务全部正确使用",
      "完全离线可用，无网络依赖",
      "资源占用适中"
    ],
    "weaknesses": [
      "大文件处理时内存占用略高"
    ],
    "recommendations": [
      "考虑增加流式处理支持以降低内存峰值"
    ]
  },
  
  "layer2_result": {
    "passed": true,
    "regression_results": {
      "skill-a": {
        "passed": true,
        "score": 85,
        "tasks_completed": 3,
        "error": null
      },
      "skill-b": {
        "passed": true,
        "score": 90,
        "tasks_completed": 3,
        "error": null
      }
    },
    "total_skills_tested": 2,
    "failed_skills": []
  },
  
  "installed_dependencies": {
    "pip": {"pandas": "2.0.0"},
    "npm": {},
    "system": {}
  },
  
  "validated_at": "2026-02-16T10:10:00Z",
  "warning": null
}
```

**验证进行中**:
```json
{
  "skill_id": "uuid-xxx",
  "skill_name": "csv-analyzer",
  "validation_stage": "layer1",
  "layer1_result": null,
  "layer2_result": null,
  "message": "Validation in progress (layer 1)"
}
```

**第一层验证失败**:
```json
{
  "skill_id": "uuid-xxx",
  "skill_name": "web-fetcher",
  "validation_stage": "failed",
  
  "layer1_result": {
    "passed": false,
    "blind_test": {
      "passed": false,
      "skill_triggered": true,
      "trigger_accuracy": 0.33,
      "task_results": [...]
    },
    "network_test": {
      "passed": false,
      "blocked_network_calls": 5,
      "offline_capable": false
    },
    "scores": {
      "usability": 30,
      "trigger_accuracy": 33,
      "offline_capability": 0,
      "resource_efficiency": 90,
      "overall": 33.25
    },
    "summary": "该 Skill 强依赖网络，无法在离线环境使用",
    "weaknesses": ["无法离线运行"],
    "recommendations": ["考虑增加离线缓存机制"]
  },
  
  "layer2_result": null,
  "warning": "验证评分（33.25）低于阈值（70）"
}
```

**回归验证失败**:
```json
{
  "skill_id": "uuid-xxx",
  "skill_name": "new-processor",
  "validation_stage": "failed",
  
  "layer1_result": {
    "passed": true,
    "scores": {"overall": 85}
  },
  
  "layer2_result": {
    "passed": false,
    "regression_results": {
      "skill-a": {
        "passed": true,
        "score": 85,
        "tasks_completed": 3,
        "error": null
      },
      "skill-b": {
        "passed": false,
        "score": 40,
        "tasks_completed": 1,
        "error": "numpy 版本冲突导致导入失败"
      }
    },
    "total_skills_tested": 2,
    "failed_skills": ["skill-b"]
  },
  
  "warning": "回归验证失败，skill-b 受到影响"
}
```

---

### 3.5 批准 Skill

```http
POST /api/admin/skills/{skill_id}/approve
Authorization: Bearer {token}
```

**说明**：管理员审核验证报告后，决定批准该 Skill 入库。批准时会自动 commit 容器为新镜像版本。

**前置条件**：
- `validation_stage` = `completed`（两层验证都已完成）
- `layer1_passed` = `true`
- `layer2_passed` = `true`

**批准时执行的操作**：
1. commit 验证容器为新镜像版本
2. 更新生产镜像版本号
3. 移动 skill 文件到 skills/ 目录
4. 更新 skill 状态为 approved

**响应**:
```json
{
  "skill_id": "uuid-xxx",
  "name": "csv-analyzer",
  "status": "approved",
  "runtime_image_version": "v1.3",
  "approved_at": "2026-02-16T10:30:00Z",
  "message": "Skill approved and available to agents"
}
```

---

### 3.6 拒绝 Skill

```http
POST /api/admin/skills/{skill_id}/reject
Content-Type: application/json
Authorization: Bearer {token}

{
  "reason": "Validation score too low"
}
```

**响应**:
```json
{
  "skill_id": "uuid-xxx",
  "status": "rejected",
  "rejected_at": "2026-02-16T10:30:00Z",
  "reject_reason": "Validation score too low"
}
```

---

### 3.7 重新验证

```http
POST /api/admin/skills/{skill_id}/revalidate
Authorization: Bearer {token}
```

**响应**:
```json
{
  "skill_id": "uuid-xxx",
  "status": "validating",
  "validation_stage": "layer1",
  "message": "Validation started"
}
```

**验证中** `409`:
```json
{
  "code": "VALIDATION_IN_PROGRESS",
  "message": "Another skill is being validated, please wait"
}
```

---

### 3.8 删除 Skill

```http
DELETE /api/admin/skills/{skill_id}
Authorization: Bearer {token}
```

**可删除状态**：`rejected`、`approved`

**响应**:
```json
{
  "skill_id": "uuid-xxx",
  "status": "deleted",
  "message": "Skill deleted successfully"
}
```

---

### 3.9 镜像版本列表

```http
GET /api/admin/images
Authorization: Bearer {token}
```

**响应**:
```json
{
  "versions": [
    {
      "version": "v1.3",
      "skill_id": "uuid-3",
      "skill_name": "csv-analyzer",
      "created_at": "2026-02-16T10:30:00Z",
      "is_current": true
    },
    {
      "version": "v1.2",
      "skill_id": "uuid-2",
      "skill_name": "json-processor",
      "created_at": "2026-02-15T14:00:00Z",
      "is_current": false
    },
    {
      "version": "v1.1",
      "skill_id": "uuid-1",
      "skill_name": "data-validator",
      "created_at": "2026-02-14T09:00:00Z",
      "is_current": false
    }
  ],
  "current_version": "v1.3",
  "total": 3
}
```

---

### 3.10 回滚镜像版本

```http
POST /api/admin/images/rollback
Content-Type: application/json
Authorization: Bearer {token}

{
  "target_version": "v1.2"
}
```

**响应**:
```json
{
  "current_version": "v1.3",
  "target_version": "v1.2",
  "affected_skills": ["csv-analyzer"],
  "message": "Rollback to v1.2 completed. 1 skill marked as rollback_pending"
}
```

**受影响的 skill 会被标记为 `status=rollback_pending`，需要重新验证。**

---

## 四、错误响应格式

所有错误使用统一格式：

```json
{
  "code": "ERROR_CODE",
  "message": "Human readable error message",
  "details": {}
}
```

### 错误码列表

| 错误码 | HTTP 状态 | 说明 |
|--------|-----------|------|
| `UNAUTHORIZED` | 401 | 未登录或 Token 无效 |
| `FORBIDDEN` | 403 | 非管理员 |
| `SKILL_NOT_FOUND` | 404 | Skill 不存在 |
| `SKILL_ALREADY_EXISTS` | 409 | Skill 名称已存在 |
| `INVALID_SKILL_FORMAT` | 400 | Skill 格式错误 |
| `INVALID_ZIP` | 400 | zip 文件无效 |
| `VALIDATION_IN_PROGRESS` | 409 | 正在验证另一个 Skill |
| `INVALID_STATUS_TRANSITION` | 400 | 非法状态转换 |
| `VALIDATION_NOT_COMPLETED` | 400 | 验证未完成 |
| `FILE_TOO_LARGE` | 413 | 文件超过 50MB |
| `DEPENDENCY_INSTALL_FAILED` | 500 | 依赖安装失败 |
| `REGRESSION_FAILED` | 400 | 回归验证失败 |
| `IMAGE_NOT_FOUND` | 404 | 镜像版本不存在 |

---

## 五、评分维度说明

| 维度 | 评分范围 | 权重 | 评估内容 |
|------|----------|------|----------|
| **易用性** | 0-100 | 25% | 任务完成质量、输出可读性、错误处理 |
| **触发准确性** | 0-100 | 30% | 盲测中 Agent 选择正确 skill 的比例 |
| **离线能力** | 0-100 | 25% | 是否有网络依赖、被阻止的网络调用次数 |
| **资源效率** | 0-100 | 20% | CPU/内存使用、执行时间 |

**总体评分计算**：
```
overall_score = 
    usability_score × 0.25 +
    trigger_accuracy_score × 0.30 +
    offline_capability_score × 0.25 +
    resource_efficiency_score × 0.20
```

---

## 六、完整请求流程示例

### 6.1 上传-验证-审批流程

```bash
# Step 1: 上传
curl -X POST "http://localhost:8002/api/admin/skills/upload" \
  -H "Authorization: Bearer {admin_token}" \
  -F "file=@csv-analyzer.zip"

# 响应: {"skill_id": "uuid-xxx", "status": "pending", ...}

# Step 2: 轮询状态（等待验证完成）
curl -X GET "http://localhost:8002/api/admin/skills/uuid-xxx" \
  -H "Authorization: Bearer {admin_token}"

# 响应: {"status": "pending", "validation_stage": "completed", ...}

# Step 3: 查看验证报告
curl -X GET "http://localhost:8002/api/admin/skills/uuid-xxx/report" \
  -H "Authorization: Bearer {admin_token}"

# Step 4: 批准入库
curl -X POST "http://localhost:8002/api/admin/skills/uuid-xxx/approve" \
  -H "Authorization: Bearer {admin_token}"

# 响应: {"status": "approved", "runtime_image_version": "v1.3", ...}
```

### 6.2 回滚流程

```bash
# Step 1: 查看镜像版本
curl -X GET "http://localhost:8002/api/admin/images" \
  -H "Authorization: Bearer {admin_token}"

# Step 2: 回滚到指定版本
curl -X POST "http://localhost:8002/api/admin/images/rollback" \
  -H "Authorization: Bearer {admin_token}" \
  -H "Content-Type: application/json" \
  -d '{"target_version": "v1.2"}'

# 响应: {"affected_skills": ["csv-analyzer"], ...}

# Step 3: 查看受影响的 skill
curl -X GET "http://localhost:8002/api/admin/skills?status=rollback_pending" \
  -H "Authorization: Bearer {admin_token}"
```
