# API 设计

> **版本**: v0.3.1  
> **更新日期**: 2026-03-04

## 1. API 端点概览

```
POST   /api/prompt-optimizer/optimize              # 优化 agent prompt
GET    /api/prompt-optimizer/preview/{agent_name}  # 预览训练数据
GET    /api/prompt-optimizer/history/{agent_name}  # 获取优化历史
POST   /api/prompt-optimizer/apply/{history_id}    # 应用优化结果
DELETE /api/prompt-optimizer/history/{history_id}  # 删除优化历史
```

---

## 2. 详细 API 设计

### 2.1 优化 Agent Prompt

```http
POST /api/prompt-optimizer/optimize
Content-Type: application/json

{
    "agent_name": "main",
    "sample_size": 50,
    "max_demos": 4,
    "metric_threshold": 0.6
}
```

**请求参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| agent_name | string | 是 | - | Agent 名称 (main 或 subagent name) |
| sample_size | int | 否 | 50 | 训练数据采样数量 |
| max_demos | int | 否 | 4 | 最大 few-shot 示例数 |
| metric_threshold | float | 否 | 0.6 | 评估指标阈值 (0-1) |

**响应**:

```json
{
    "success": true,
    "message": "Successfully optimized with 4 demos",
    "history_id": "uuid-xxx",
    "demo_count": 4,
    "score": 0.85,
    "demos": [
        {
            "user_input": "帮我创建一个 FastAPI 项目",
            "response": "好的，我来帮你创建..."
        }
    ]
}
```

**错误响应**:

```json
{
    "success": false,
    "message": "训练数据不足: 仅 3 条，需要至少 5 条",
    "demo_count": 0,
    "score": 0.0
}
```

---

### 2.2 预览训练数据

```http
GET /api/prompt-optimizer/preview/{agent_name}?limit=10
```

**查询参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| limit | int | 否 | 10 | 返回数量限制 |

**响应**:

```json
{
    "agent_name": "main",
    "sample_count": 45,
    "samples": [
        {
            "thread_id": "user123-thread-xxx",
            "user_input": "帮我创建一个 FastAPI 项目",
            "response": "好的，我来帮你创建一个 FastAPI 项目...",
            "context": "user: 你好\nassistant: 你好！有什么可以帮助你的？"
        }
    ]
}
```

---

### 2.3 获取优化历史

```http
GET /api/prompt-optimizer/history/{agent_name}?limit=10
```

**响应**:

```json
{
    "agent_name": "main",
    "total": 5,
    "history": [
        {
            "id": "uuid-xxx",
            "agent_name": "main",
            "optimizer_type": "bootstrap",
            "demo_count": 4,
            "score": 0.85,
            "is_applied": true,
            "applied_at": "2026-03-04T10:30:00Z",
            "created_at": "2026-03-04T10:00:00Z"
        }
    ]
}
```

---

### 2.4 应用优化结果

```http
POST /api/prompt-optimizer/apply/{history_id}
```

**响应**:

```json
{
    "success": true,
    "message": "Optimization applied to agent 'main'",
    "agent_name": "main",
    "applied_at": "2026-03-04T10:30:00Z"
}
```

---

### 2.5 删除优化历史

```http
DELETE /api/prompt-optimizer/history/{history_id}
```

**响应**:

```json
{
    "success": true,
    "message": "Optimization history deleted"
}
```

---

## 3. API 实现代码

```python
# api/prompt_optimizer.py

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

from src.prompt_optimizer import PromptOptimizer, TrainingDataExtractor
from src.database import SessionLocal
from src.utils.get_logger import get_logger

logger = get_logger("prompt-optimizer-api")
router = APIRouter(prefix="/api/prompt-optimizer", tags=["prompt-optimizer"])


# ============== Request/Response Models ==============

class OptimizeRequest(BaseModel):
    agent_name: str = Field(..., description="Agent 名称")
    sample_size: int = Field(50, ge=5, le=200, description="训练数据采样数量")
    max_demos: int = Field(4, ge=1, le=10, description="最大 few-shot 示例数")
    metric_threshold: float = Field(0.6, ge=0.0, le=1.0, description="评估指标阈值")


class OptimizeResponse(BaseModel):
    success: bool
    message: str
    history_id: Optional[str] = None
    demo_count: int = 0
    score: float = 0.0
    demos: Optional[List[dict]] = None


class PreviewResponse(BaseModel):
    agent_name: str
    sample_count: int
    samples: List[dict]


class HistoryItem(BaseModel):
    id: str
    agent_name: str
    optimizer_type: str
    demo_count: int
    score: float
    is_applied: bool
    applied_at: Optional[str] = None
    created_at: Optional[str] = None


class HistoryResponse(BaseModel):
    agent_name: str
    total: int
    history: List[HistoryItem]


class ApplyResponse(BaseModel):
    success: bool
    message: str
    agent_name: Optional[str] = None
    applied_at: Optional[str] = None


# ============== API Endpoints ==============

@router.post("/optimize", response_model=OptimizeResponse)
async def optimize_agent_prompt(request: OptimizeRequest):
    """
    优化指定 agent 的 system_prompt
    
    流程：
    1. 获取当前 agent 配置的 system_prompt
    2. 从历史对话提取训练数据
    3. 运行 BootstrapFewShot 优化
    4. 保存优化结果到历史记录
    """
    from src.agent_config_manager import get_agent_config_manager
    
    logger.info(f"[optimize] 开始优化 agent: {request.agent_name}")
    
    # 1. 获取当前 prompt
    config_manager = get_agent_config_manager()
    with SessionLocal() as db:
        config = config_manager.get_config(request.agent_name, db)
        if not config:
            raise HTTPException(404, f"Agent '{request.agent_name}' not found")
        
        current_prompt = config.system_prompt
    
    # 2. 提取训练数据
    extractor = TrainingDataExtractor()
    training_data = extractor.extract_for_agent(
        agent_name=request.agent_name,
        limit=request.sample_size,
    )
    
    if len(training_data) < 5:
        return OptimizeResponse(
            success=False,
            message=f"训练数据不足: 仅 {len(training_data)} 条，需要至少 5 条",
        )
    
    # 3. 运行优化
    optimizer = PromptOptimizer()
    result = optimizer.optimize(
        current_prompt=current_prompt,
        training_examples=training_data,
        max_bootstrapped_demos=request.max_demos,
        metric_threshold=request.metric_threshold,
    )
    
    if not result["success"]:
        return OptimizeResponse(
            success=False,
            message=f"优化失败: {result.get('error', 'Unknown error')}",
        )
    
    # 4. 保存历史
    history_id = optimizer.save_optimization_history(
        agent_name=request.agent_name,
        result=result,
        config={
            "max_bootstrapped_demos": request.max_demos,
            "metric_threshold": request.metric_threshold,
        },
    )
    
    logger.info(f"[optimize] 优化完成，history_id: {history_id}")
    
    return OptimizeResponse(
        success=True,
        message=f"Successfully optimized with {result['demo_count']} demos",
        history_id=history_id,
        demo_count=result["demo_count"],
        score=result["score"],
        demos=result.get("demos", []),
    )


@router.get("/preview/{agent_name}", response_model=PreviewResponse)
async def preview_training_data(agent_name: str, limit: int = 10):
    """
    预览训练数据
    
    查看将从哪些历史对话中提取训练数据
    """
    extractor = TrainingDataExtractor()
    data = extractor.extract_for_agent(
        agent_name=agent_name,
        limit=limit,
    )
    
    return PreviewResponse(
        agent_name=agent_name,
        sample_count=len(data),
        samples=data[:limit],
    )


@router.get("/history/{agent_name}", response_model=HistoryResponse)
async def get_optimization_history(agent_name: str, limit: int = 10):
    """
    获取优化历史
    
    查看指定 agent 的所有优化记录
    """
    optimizer = PromptOptimizer()
    history = optimizer.get_optimization_history(
        agent_name=agent_name,
        limit=limit,
    )
    
    return HistoryResponse(
        agent_name=agent_name,
        total=len(history),
        history=[HistoryItem(**h) for h in history],
    )


@router.post("/apply/{history_id}", response_model=ApplyResponse)
async def apply_optimization(history_id: str):
    """
    应用优化结果
    
    将优化后的 few-shot 示例应用到 agent 配置
    """
    from src.database import PromptOptimizationHistory
    
    with SessionLocal() as db:
        history = db.query(PromptOptimizationHistory).filter(
            PromptOptimizationHistory.id == history_id
        ).first()
        
        if not history:
            raise HTTPException(404, f"Optimization history '{history_id}' not found")
        
        if history.is_applied:
            return ApplyResponse(
                success=True,
                message="Optimization already applied",
                agent_name=history.agent_name,
                applied_at=history.applied_at.isoformat() if history.applied_at else None,
            )
    
    optimizer = PromptOptimizer()
    success = optimizer.apply_optimization(
        agent_name=history.agent_name,
        history_id=history_id,
    )
    
    if success:
        return ApplyResponse(
            success=True,
            message=f"Optimization applied to agent '{history.agent_name}'",
            agent_name=history.agent_name,
            applied_at=datetime.utcnow().isoformat(),
        )
    else:
        raise HTTPException(500, "Failed to apply optimization")


@router.delete("/history/{history_id}")
async def delete_optimization_history(history_id: str):
    """
    删除优化历史
    
    仅删除未应用的优化记录
    """
    from src.database import PromptOptimizationHistory
    
    with SessionLocal() as db:
        history = db.query(PromptOptimizationHistory).filter(
            PromptOptimizationHistory.id == history_id
        ).first()
        
        if not history:
            raise HTTPException(404, f"Optimization history '{history_id}' not found")
        
        if history.is_applied:
            raise HTTPException(400, "Cannot delete applied optimization")
        
        db.delete(history)
        db.commit()
    
    return {"success": True, "message": "Optimization history deleted"}
```

---

## 4. 路由注册

```python
# main.py 或 api/__init__.py

from api.prompt_optimizer import router as prompt_optimizer_router

app.include_router(prompt_optimizer_router)
```

---

## 5. 使用示例

### 5.1 cURL 示例

```bash
# 优化 main agent 的 prompt
curl -X POST http://localhost:8002/api/prompt-optimizer/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "main",
    "sample_size": 50,
    "max_demos": 4
  }'

# 预览训练数据
curl http://localhost:8002/api/prompt-optimizer/preview/main?limit=5

# 查看优化历史
curl http://localhost:8002/api/prompt-optimizer/history/main

# 应用优化结果
curl -X POST http://localhost:8002/api/prompt-optimizer/apply/{history_id}
```

### 5.2 Python 客户端示例

```python
import requests

BASE_URL = "http://localhost:8002/api/prompt-optimizer"

# 1. 优化 prompt
response = requests.post(f"{BASE_URL}/optimize", json={
    "agent_name": "main",
    "sample_size": 50,
    "max_demos": 4,
})
result = response.json()
print(f"优化结果: {result}")

if result["success"]:
    history_id = result["history_id"]
    
    # 2. 应用优化
    apply_response = requests.post(f"{BASE_URL}/apply/{history_id}")
    print(f"应用结果: {apply_response.json()}")
```

---

## 6. 前端集成建议

### 6.1 管理界面

```
┌─────────────────────────────────────────────────────────────┐
│                    Prompt 优化管理                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  选择 Agent: [main ▼]                                       │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 当前 System Prompt                                   │   │
│  │ ┌─────────────────────────────────────────────────┐ │   │
│  │ │ 用户的工作目录在/workspace中...                   │ │   │
│  │ │ ...                                             │ │   │
│  │ └─────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  训练数据: 45 条成功对话                                     │
│  [预览数据]                                                 │
│                                                             │
│  优化参数:                                                   │
│  - 采样数量: [50]                                           │
│  - 最大示例: [4]                                            │
│  - 评估阈值: [0.6]                                          │
│                                                             │
│  [开始优化]                                                 │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│  优化历史:                                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ #1 | 2026-03-04 10:00 | 分数: 0.85 | 示例: 4 | [应用]│   │
│  │ #2 | 2026-03-03 15:30 | 分数: 0.82 | 示例: 3 | [应用]│   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 优化进度显示

```
┌─────────────────────────────────────────────────────────────┐
│                    正在优化...                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ████████████████████░░░░░░░░░░ 60%                         │
│                                                             │
│  当前步骤: 收集成功轨迹                                      │
│  已处理: 30/50 条对话                                        │
│  成功: 28 条                                                │
│                                                             │
│  预计剩余时间: 2 分钟                                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
