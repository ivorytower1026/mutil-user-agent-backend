# 详细实现代码

> **版本**: v0.3.1  
> **更新日期**: 2026-03-04

## 1. 文件结构

```
src/
├── prompt_optimizer/               # 新增目录
│   ├── __init__.py                # 导出和版本
│   ├── optimizer.py               # 核心优化器
│   ├── signatures.py              # DSPy Signatures
│   ├── metrics.py                 # 评估指标
│   └── data_extractor.py          # 训练数据提取
│
├── database.py                    # 新增表
└── ...

api/
├── prompt_optimizer.py            # 新增 API 端点
└── ...
```

---

## 2. 核心代码实现

### 2.1 signatures.py - DSPy Signatures

```python
"""DSPy Signatures for prompt optimization."""

import dspy
from typing import Literal


class AgentResponse(dspy.Signature):
    """Generate agent response based on user input and system prompt."""
    user_input: str = dspy.InputField(desc="用户的输入/请求")
    system_prompt: str = dspy.InputField(desc="Agent 的系统提示")
    context: str = dspy.InputField(desc="可选的上下文信息")
    response: str = dspy.OutputField(desc="Agent 的响应")
    action_taken: str = dspy.OutputField(desc="执行的操作描述")


class EvaluateResponse(dspy.Signature):
    """Evaluate the quality of an agent response."""
    user_input: str = dspy.InputField()
    agent_response: str = dspy.InputField()
    expected_outcome: str = dspy.InputField(desc="期望的结果")
    
    task_completed: bool = dspy.OutputField(desc="任务是否完成")
    quality_score: Literal["excellent", "good", "acceptable", "poor"] = dspy.OutputField()
    feedback: str = dspy.OutputField(desc="改进建议")
```

### 2.2 metrics.py - 评估指标

```python
"""Evaluation metrics for prompt optimization."""

import dspy
from typing import Optional


def create_agent_metric(threshold: float = 0.7):
    """
    创建 agent 响应评估指标
    
    Args:
        threshold: 任务完成阈值 (0-1)
    
    Returns:
        metric function
    """
    def agent_metric(
        example: dspy.Example,
        prediction: dspy.Prediction,
        trace: Optional[list] = None
    ) -> float:
        """
        评估 agent 响应质量
        
        返回 0-1 的分数
        """
        if not hasattr(prediction, "response") or not prediction.response:
            return 0.0
        
        score = 0.0
        
        # 1. 检查响应长度合理性
        if len(prediction.response) >= 10:
            score += 0.2
        
        # 2. 检查是否包含错误标记
        error_markers = ["error", "failed", "exception", "unable to", "sorry"]
        response_lower = prediction.response.lower()
        error_count = sum(1 for marker in error_markers if marker in response_lower)
        if error_count == 0:
            score += 0.2
        elif error_count <= 2:
            score += 0.1
        
        # 3. 检查是否有操作描述
        if hasattr(prediction, "action_taken") and prediction.action_taken:
            score += 0.2
        
        # 4. 如果有期望输出，计算相似度
        if hasattr(example, "response") and example.response:
            expected_words = set(example.response.lower().split())
            actual_words = set(prediction.response.lower().split())
            if expected_words:
                overlap = len(expected_words & actual_words) / len(expected_words)
                score += overlap * 0.4
        else:
            score += 0.2  # 没有期望输出时给基础分
        
        return min(score, 1.0)
    
    return agent_metric


def code_execution_metric(
    example: dspy.Example,
    prediction: dspy.Prediction,
    trace: Optional[list] = None
) -> float:
    """
    评估代码执行相关任务的指标
    
    检查是否有成功的工具调用
    """
    if not trace:
        return 0.5
    
    for step in trace:
        predictor, inputs, outputs = step
        outputs_str = str(outputs).lower()
        # 检查是否有成功的执行
        if "execute" in outputs_str and "success" in outputs_str:
            return 1.0
        if "created" in outputs_str or "written" in outputs_str:
            return 0.9
    
    return 0.5


class CompositeMetric:
    """组合多个评估指标"""
    
    def __init__(self, metrics: list, weights: list[float] | None = None):
        self.metrics = metrics
        self.weights = weights or [1.0 / len(metrics)] * len(metrics)
    
    def __call__(
        self,
        example: dspy.Example,
        prediction: dspy.Prediction,
        trace: Optional[list] = None
    ) -> float:
        scores = [
            metric(example, prediction, trace)
            for metric in self.metrics
        ]
        return sum(s * w for s, w in zip(scores, self.weights))
```

### 2.3 data_extractor.py - 训练数据提取

```python
"""Training data extractor from conversation history."""

from typing import List, Dict, Any
from sqlalchemy import desc

from src.database import SessionLocal, Thread
from src.utils.get_logger import get_logger

logger = get_logger("prompt-optimizer")


class TrainingDataExtractor:
    """从历史对话中提取训练数据"""
    
    def extract_successful_threads(
        self,
        limit: int = 100,
        min_turns: int = 2,
        user_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        提取成功的对话作为训练数据
        
        Args:
            limit: 最大提取数量
            min_turns: 最少对话轮数
            user_id: 可选的用户 ID 过滤
        
        Returns:
            训练示例列表
        """
        with SessionLocal() as db:
            query = db.query(Thread).filter(Thread.message_count >= min_turns)
            
            if user_id:
                query = query.filter(Thread.thread_id.startswith(f"{user_id}-"))
            
            threads = query.order_by(desc(Thread.updated_at)).limit(limit).all()
            
            examples = []
            for thread in threads:
                messages = self._extract_messages_from_checkpoint(thread.thread_id)
                if messages:
                    # 构建训练示例 - 配对用户和助手消息
                    for i in range(0, len(messages) - 1, 2):
                        if i + 1 < len(messages):
                            user_msg = messages[i]
                            assistant_msg = messages[i + 1]
                            
                            if user_msg.get("role") == "user" and assistant_msg.get("role") == "assistant":
                                examples.append({
                                    "thread_id": thread.thread_id,
                                    "user_input": user_msg.get("content", ""),
                                    "response": assistant_msg.get("content", ""),
                                    "context": self._build_context(messages[:i]),
                                })
            
            logger.info(f"[TrainingDataExtractor] 提取了 {len(examples)} 个训练示例")
            return examples
    
    def _extract_messages_from_checkpoint(self, thread_id: str) -> List[Dict[str, Any]]:
        """从 LangGraph checkpoint 提取消息"""
        try:
            from api.server import agent_manager
            
            config = {"configurable": {"thread_id": thread_id}}
            state = agent_manager.checkpointer.get(config)
            
            if state and "messages" in state:
                messages = state["messages"]
                return [
                    {"role": msg.type, "content": msg.content}
                    for msg in messages
                    if hasattr(msg, "type") and hasattr(msg, "content")
                ]
        except Exception as e:
            logger.warning(f"[TrainingDataExtractor] 提取消息失败 {thread_id}: {e}")
        
        return []
    
    def _build_context(self, previous_messages: List[Dict[str, Any]]) -> str:
        """构建上下文信息"""
        if not previous_messages:
            return ""
        
        context_parts = []
        for msg in previous_messages[-4:]:  # 最多取前 4 条消息作为上下文
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]  # 限制长度
            context_parts.append(f"{role}: {content}")
        
        return "\n".join(context_parts)
    
    def extract_for_agent(
        self,
        agent_name: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        为特定 agent 提取训练数据
        
        Args:
            agent_name: Agent 名称 (用于未来扩展，如按 subagent 分类)
            limit: 最大提取数量
        
        Returns:
            训练示例列表
        """
        # 当前实现：提取所有成功对话
        # 未来可扩展：根据 agent_name 筛选特定类型的对话
        return self.extract_successful_threads(limit=limit)
```

### 2.4 optimizer.py - 核心优化器

```python
"""DSPy-based prompt optimizer using BootstrapFewShot."""

import dspy
from typing import List, Dict, Any, Literal
import uuid

from src.config import settings
from src.database import SessionLocal, PromptOptimizationHistory
from src.utils.get_logger import get_logger
from .signatures import AgentResponse
from .metrics import create_agent_metric

logger = get_logger("prompt-optimizer")


class PromptOptimizer:
    """DSPy-based prompt optimizer using BootstrapFewShot."""
    
    def __init__(self):
        self._configure_dspy()
    
    def _configure_dspy(self):
        """配置 DSPy 使用智谱AI"""
        lm = dspy.LM(
            "openai/glm-5",
            api_key=settings.ZHIPUAI_API_KEY,
            api_base=settings.ZHIPUAI_API_BASE,
        )
        dspy.configure(lm=lm)
        logger.info("[PromptOptimizer] DSPy configured with glm-5")
    
    def optimize(
        self,
        current_prompt: str,
        training_examples: List[Dict[str, Any]],
        max_bootstrapped_demos: int = 4,
        max_labeled_demos: int = 8,
        metric_threshold: float = 0.6,
    ) -> Dict[str, Any]:
        """
        使用 BootstrapFewShot 优化 prompt
        
        Args:
            current_prompt: 当前的 system prompt
            training_examples: 训练示例
                [{"user_input": "...", "response": "...", "context": "..."}]
            max_bootstrapped_demos: 最大 bootstrap 示例数
            max_labeled_demos: 最大标注示例数
            metric_threshold: 指标阈值
        
        Returns:
            {
                "success": bool,
                "optimized_program": Module,
                "demos": list,
                "score": float,
                "error": str (if failed)
            }
        """
        
        # 1. 创建 Agent Module
        class AgentModule(dspy.Module):
            def __init__(self, system_prompt: str):
                super().__init__()
                self.predict = dspy.ChainOfThought(AgentResponse)
                self.system_prompt = system_prompt
            
            def forward(self, user_input: str, context: str = ""):
                return self.predict(
                    user_input=user_input,
                    system_prompt=self.system_prompt,
                    context=context,
                )
        
        # 2. 准备训练数据
        trainset = [
            dspy.Example(
                user_input=ex["user_input"],
                system_prompt=current_prompt,
                context=ex.get("context", ""),
                response=ex["response"],
            ).with_inputs("user_input", "system_prompt", "context")
            for ex in training_examples
            if ex.get("user_input") and ex.get("response")
        ]
        
        if len(trainset) < 5:
            return {
                "success": False,
                "error": f"训练数据不足: 仅 {len(trainset)} 条，需要至少 5 条",
                "demos": [],
                "score": 0.0,
            }
        
        logger.info(f"[PromptOptimizer] 开始优化，训练集大小: {len(trainset)}")
        
        # 3. 创建评估指标
        metric = create_agent_metric(threshold=metric_threshold)
        
        # 4. 运行 Bootstrap 优化
        try:
            optimizer = dspy.BootstrapFewShot(
                metric=metric,
                max_bootstrapped_demos=max_bootstrapped_demos,
                max_labeled_demos=max_labeled_demos,
                max_rounds=1,
            )
            
            program = AgentModule(current_prompt)
            optimized_program = optimizer.compile(
                student=program,
                trainset=trainset,
            )
            
            # 5. 评估优化效果
            from dspy.evaluate import Evaluate
            eval_set = trainset[:min(10, len(trainset))]
            evaluator = Evaluate(
                devset=eval_set,
                metric=metric,
                num_threads=1,
                display_progress=False,
            )
            score = evaluator(optimized_program)
            
            # 6. 提取 demos
            demos = []
            if hasattr(optimized_program.predict, "demos"):
                demos = [
                    {
                        "user_input": d.user_input if hasattr(d, "user_input") else "",
                        "response": d.response if hasattr(d, "response") else "",
                    }
                    for d in optimized_program.predict.demos
                ]
            
            logger.info(f"[PromptOptimizer] 优化完成，分数: {score}, demos: {len(demos)}")
            
            return {
                "success": True,
                "optimized_program": optimized_program,
                "demos": demos,
                "score": score,
                "demo_count": len(demos),
            }
            
        except Exception as e:
            logger.error(f"[PromptOptimizer] 优化失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "demos": [],
                "score": 0.0,
            }
    
    def save_optimization_history(
        self,
        agent_name: str,
        result: Dict[str, Any],
        config: Dict[str, Any],
    ) -> str:
        """
        保存优化历史到数据库
        
        Returns:
            history_id
        """
        history_id = str(uuid.uuid4())
        
        with SessionLocal() as db:
            history = PromptOptimizationHistory(
                id=history_id,
                agent_name=agent_name,
                optimizer_type="bootstrap",
                max_demos=config.get("max_bootstrapped_demos", 4),
                metric_threshold=config.get("metric_threshold", 0.6),
                demo_count=result.get("demo_count", 0),
                score=result.get("score", 0.0),
                demos_data=result.get("demos", []),
                is_applied=False,
            )
            db.add(history)
            db.commit()
        
        logger.info(f"[PromptOptimizer] 保存优化历史: {history_id}")
        return history_id
    
    def apply_optimization(
        self,
        agent_name: str,
        history_id: str,
    ) -> bool:
        """
        应用优化结果到 agent 配置
        
        Args:
            agent_name: agent 名称
            history_id: 优化历史 ID
        
        Returns:
            是否成功
        """
        from src.agent_config_manager import get_agent_config_manager
        from datetime import datetime
        
        with SessionLocal() as db:
            # 获取优化历史
            history = db.query(PromptOptimizationHistory).filter(
                PromptOptimizationHistory.id == history_id
            ).first()
            
            if not history:
                logger.error(f"[PromptOptimizer] 优化历史不存在: {history_id}")
                return False
            
            # 更新 agent 配置
            config_manager = get_agent_config_manager()
            config = config_manager.get_config(agent_name, db)
            
            if not config:
                logger.error(f"[PromptOptimizer] Agent 配置不存在: {agent_name}")
                return False
            
            # 保存优化后的 demos
            # 注意：需要扩展 AgentConfigModel 添加 optimized_demos 字段
            # 这里先更新历史记录状态
            history.is_applied = True
            history.applied_at = datetime.utcnow()
            db.commit()
            
            logger.info(f"[PromptOptimizer] 应用优化: {history_id} -> {agent_name}")
            return True
    
    def get_optimization_history(
        self,
        agent_name: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """获取优化历史"""
        with SessionLocal() as db:
            histories = (
                db.query(PromptOptimizationHistory)
                .filter(PromptOptimizationHistory.agent_name == agent_name)
                .order_by(PromptOptimizationHistory.created_at.desc())
                .limit(limit)
                .all()
            )
            
            return [
                {
                    "id": h.id,
                    "agent_name": h.agent_name,
                    "optimizer_type": h.optimizer_type,
                    "demo_count": h.demo_count,
                    "score": h.score,
                    "is_applied": h.is_applied,
                    "applied_at": h.applied_at.isoformat() if h.applied_at else None,
                    "created_at": h.created_at.isoformat() if h.created_at else None,
                }
                for h in histories
            ]
```

### 2.5 __init__.py - 模块导出

```python
"""DSPy Prompt Optimizer for Multi-tenant AI Agent Platform."""

from .optimizer import PromptOptimizer
from .data_extractor import TrainingDataExtractor
from .metrics import create_agent_metric, code_execution_metric, CompositeMetric

__all__ = [
    "PromptOptimizer",
    "TrainingDataExtractor",
    "create_agent_metric",
    "code_execution_metric",
    "CompositeMetric",
]

__version__ = "0.3.1"
```

---

## 3. 数据库扩展

### 3.1 新增表定义

```python
# src/database.py 新增

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON

class PromptOptimizationHistory(Base):
    """Prompt 优化历史记录"""
    __tablename__ = "prompt_optimization_history"
    
    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_name = Column(String(64), nullable=False, index=True)
    
    # 优化配置
    optimizer_type = Column(String(32), default="bootstrap")
    max_demos = Column(Integer)
    metric_threshold = Column(Float)
    
    # 优化结果
    demo_count = Column(Integer)
    score = Column(Float)
    demos_data = Column(JSON)  # 序列化的 few-shot 示例
    
    # 状态
    is_applied = Column(Boolean, default=False)
    applied_at = Column(DateTime)
    
    created_at = Column(DateTime, server_default=func.now())
```

---

## 4. 依赖更新

### 4.1 pyproject.toml

```toml
[project]
dependencies = [
    # ... 现有依赖
    "dspy-ai>=2.5.0",
]
```

### 4.2 安装命令

```bash
uv add dspy-ai
# 或
uv sync
```
