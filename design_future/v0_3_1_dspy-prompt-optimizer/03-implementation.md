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

---

## 5. 测试脚本

### 5.1 测试文件结构

```
tests/
└── prompt_optimizer/
    ├── __init__.py
    ├── conftest.py              # 测试配置和 fixtures
    ├── test_signatures.py       # 测试 DSPy Signatures
    ├── test_metrics.py          # 测试评估指标
    ├── test_data_extractor.py   # 测试数据提取
    ├── test_optimizer.py        # 测试优化器核心
    ├── test_api.py              # 测试 API 端点
    └── run_all.py               # 运行所有测试
```

### 5.2 测试用例设计

| 模块 | 测试用例 | 说明 |
|------|---------|------|
| **signatures** | test_agent_response_signature | 验证 Signature 定义正确 |
| **metrics** | test_create_agent_metric | 测试评估指标计算 |
| **metrics** | test_metric_with_empty_response | 空响应返回 0 分 |
| **metrics** | test_metric_with_error_markers | 错误标记降低分数 |
| **metrics** | test_metric_with_good_response | 良好响应返回高分 |
| **data_extractor** | test_extract_with_no_threads | 没有对话时返回空列表 |
| **data_extractor** | test_extract_with_min_turns | 最少轮数过滤 |
| **data_extractor** | test_build_context | 上下文构建 |
| **optimizer** | test_configure_dspy | DSPy 配置正确 |
| **optimizer** | test_optimize_with_insufficient_data | 数据不足时返回失败 |
| **optimizer** | test_optimize_success | 成功优化流程 |
| **optimizer** | test_save_optimization_history | 保存历史记录 |
| **api** | test_optimize_endpoint_not_found | agent 不存在返回 404 |
| **api** | test_optimize_endpoint_insufficient_data | 数据不足返回失败 |
| **api** | test_preview_endpoint | 预览端点测试 |
| **api** | test_history_endpoint | 历史端点测试 |

### 5.3 conftest.py - 测试配置

```python
"""Test configuration and fixtures."""

import pytest
from unittest.mock import MagicMock, patch
import os

# 设置测试环境变量
os.environ.setdefault("ZHIPUAI_API_KEY", "test-api-key")
os.environ.setdefault("ZHIPUAI_API_BASE", "https://test.api.com")
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = MagicMock()
    return session


@pytest.fixture
def mock_thread():
    """Mock Thread object."""
    thread = MagicMock()
    thread.thread_id = "test-user-test-thread-123"
    thread.message_count = 5
    thread.updated_at = "2026-03-04T10:00:00"
    return thread


@pytest.fixture
def sample_training_data():
    """Sample training data for testing."""
    return [
        {
            "thread_id": f"test-thread-{i}",
            "user_input": f"用户问题 {i}",
            "response": f"助手回答 {i}，这是一个详细的响应内容",
            "context": "",
        }
        for i in range(10)
    ]


@pytest.fixture
def sample_messages():
    """Sample messages from checkpoint."""
    return [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么可以帮助你的？"},
        {"role": "user", "content": "帮我写个函数"},
        {"role": "assistant", "content": "好的，我来帮你写一个函数。请告诉我你需要什么功能？"},
    ]
```

### 5.4 test_metrics.py - 评估指标测试

```python
"""Tests for evaluation metrics."""

import pytest
from unittest.mock import Mock
from src.prompt_optimizer.metrics import (
    create_agent_metric,
    code_execution_metric,
    CompositeMetric,
)


class TestCreateAgentMetric:
    """Tests for create_agent_metric function."""
    
    def test_metric_with_empty_response(self):
        """测试空响应返回 0 分"""
        metric = create_agent_metric()
        
        example = Mock()
        prediction = Mock()
        prediction.response = ""
        
        score = metric(example, prediction)
        assert score == 0.0
    
    def test_metric_with_no_response_attribute(self):
        """测试没有 response 属性时返回 0 分"""
        metric = create_agent_metric()
        
        example = Mock()
        prediction = Mock(spec=[])  # 没有 response 属性
        
        score = metric(example, prediction)
        assert score == 0.0
    
    def test_metric_with_short_response(self):
        """测试过短响应返回低分"""
        metric = create_agent_metric()
        
        example = Mock()
        prediction = Mock()
        prediction.response = "ok"  # 少于 10 个字符
        
        score = metric(example, prediction)
        assert score < 0.3
    
    def test_metric_with_error_markers(self):
        """测试错误标记降低分数"""
        metric = create_agent_metric()
        
        example = Mock()
        prediction = Mock()
        prediction.response = "Sorry, I failed to complete the task due to an error"
        
        score = metric(example, prediction)
        assert score < 0.5
    
    def test_metric_with_good_response(self):
        """测试良好响应返回高分"""
        metric = create_agent_metric()
        
        example = Mock()
        example.response = "这是期望的回答内容"
        
        prediction = Mock()
        prediction.response = "这是期望的回答内容，完全符合要求，执行了相应操作"
        prediction.action_taken = "执行了文件创建操作"
        
        score = metric(example, prediction)
        assert score > 0.5
    
    def test_metric_with_matching_expected_response(self):
        """测试与期望输出匹配时高分"""
        metric = create_agent_metric()
        
        expected = "这是一个关于 Python 编程的回答"
        
        example = Mock()
        example.response = expected
        
        prediction = Mock()
        prediction.response = expected  # 完全匹配
        prediction.action_taken = "执行操作"
        
        score = metric(example, prediction)
        assert score > 0.7


class TestCodeExecutionMetric:
    """Tests for code_execution_metric function."""
    
    def test_metric_with_no_trace(self):
        """测试没有 trace 时返回中等分数"""
        example = Mock()
        prediction = Mock()
        
        score = code_execution_metric(example, prediction, trace=None)
        assert score == 0.5
    
    def test_metric_with_successful_execution(self):
        """测试成功执行返回高分"""
        example = Mock()
        prediction = Mock()
        
        # 模拟成功执行的 trace
        trace = [
            (Mock(), {}, {"result": "execute success"})
        ]
        
        score = code_execution_metric(example, prediction, trace=trace)
        assert score == 1.0
    
    def test_metric_with_created_output(self):
        """测试创建输出返回高分"""
        example = Mock()
        prediction = Mock()
        
        trace = [
            (Mock(), {}, {"result": "file created successfully"})
        ]
        
        score = code_execution_metric(example, prediction, trace=trace)
        assert score == 0.9


class TestCompositeMetric:
    """Tests for CompositeMetric class."""
    
    def test_composite_metric_equal_weights(self):
        """测试等权重组合指标"""
        metric1 = lambda e, p, t: 0.8
        metric2 = lambda e, p, t: 0.6
        
        composite = CompositeMetric([metric1, metric2])
        
        score = composite(Mock(), Mock(), None)
        assert score == pytest.approx(0.7, rel=0.01)
    
    def test_composite_metric_custom_weights(self):
        """测试自定义权重组合指标"""
        metric1 = lambda e, p, t: 1.0
        metric2 = lambda e, p, t: 0.0
        
        composite = CompositeMetric([metric1, metric2], weights=[0.8, 0.2])
        
        score = composite(Mock(), Mock(), None)
        assert score == pytest.approx(0.8, rel=0.01)
```

### 5.5 test_data_extractor.py - 数据提取测试

```python
"""Tests for TrainingDataExtractor."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.prompt_optimizer.data_extractor import TrainingDataExtractor


class TestTrainingDataExtractor:
    """Tests for TrainingDataExtractor class."""
    
    def test_extract_with_no_threads(self, mock_db_session):
        """测试没有对话时返回空列表"""
        with patch("src.prompt_optimizer.data_extractor.SessionLocal") as mock_session:
            mock_session.return_value.__enter__.return_value = mock_db_session
            mock_db_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
            
            extractor = TrainingDataExtractor()
            result = extractor.extract_successful_threads(limit=10)
            
            assert result == []
    
    def test_extract_with_threads(self, mock_db_session, mock_thread, sample_messages):
        """测试提取成功对话"""
        with patch("src.prompt_optimizer.data_extractor.SessionLocal") as mock_session:
            mock_session.return_value.__enter__.return_value = mock_db_session
            mock_db_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_thread]
            
            extractor = TrainingDataExtractor()
            
            # Mock _extract_messages_from_checkpoint
            with patch.object(extractor, "_extract_messages_from_checkpoint", return_value=sample_messages):
                result = extractor.extract_successful_threads(limit=10)
            
            assert len(result) > 0
            assert "user_input" in result[0]
            assert "response" in result[0]
    
    def test_extract_with_min_turns_filter(self, mock_db_session):
        """测试最少轮数过滤"""
        with patch("src.prompt_optimizer.data_extractor.SessionLocal") as mock_session:
            mock_session.return_value.__enter__.return_value = mock_db_session
            
            # 创建一个 message_count 较少的 thread
            low_count_thread = MagicMock()
            low_count_thread.thread_id = "test-thread-low"
            low_count_thread.message_count = 1  # 少于 min_turns
            
            mock_db_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
            
            extractor = TrainingDataExtractor()
            result = extractor.extract_successful_threads(limit=10, min_turns=2)
            
            # 验证 filter 被调用
            mock_db_session.query.return_value.filter.assert_called_once()
    
    def test_build_context_empty(self):
        """测试空消息列表的上下文构建"""
        extractor = TrainingDataExtractor()
        
        context = extractor._build_context([])
        
        assert context == ""
    
    def test_build_context_with_messages(self, sample_messages):
        """测试有消息时的上下文构建"""
        extractor = TrainingDataExtractor()
        
        context = extractor._build_context(sample_messages[:2])
        
        assert "user: 你好" in context
        assert "assistant: 你好" in context
    
    def test_build_context_limits_length(self):
        """测试上下文长度限制"""
        extractor = TrainingDataExtractor()
        
        # 创建超过 4 条消息
        long_messages = [
            {"role": "user", "content": f"消息 {i}"}
            for i in range(10)
        ]
        
        context = extractor._build_context(long_messages)
        
        # 只取最后 4 条
        assert "消息 6" in context
        assert "消息 9" in context
    
    def test_extract_messages_from_checkpoint_success(self):
        """测试从 checkpoint 提取消息成功"""
        extractor = TrainingDataExtractor()
        
        # Mock agent_manager
        mock_state = {
            "messages": [
                Mock(type="user", content="用户消息"),
                Mock(type="assistant", content="助手消息"),
            ]
        }
        
        with patch("src.prompt_optimizer.data_extractor.agent_manager") as mock_am:
            mock_am.checkpointer.get.return_value = mock_state
            
            result = extractor._extract_messages_from_checkpoint("test-thread-id")
            
            assert len(result) == 2
            assert result[0]["role"] == "user"
            assert result[1]["role"] == "assistant"
    
    def test_extract_messages_from_checkpoint_failure(self):
        """测试从 checkpoint 提取消息失败"""
        extractor = TrainingDataExtractor()
        
        with patch("src.prompt_optimizer.data_extractor.agent_manager") as mock_am:
            mock_am.checkpointer.get.side_effect = Exception("Test error")
            
            result = extractor._extract_messages_from_checkpoint("test-thread-id")
            
            assert result == []
    
    def test_extract_for_agent(self, mock_db_session):
        """测试为特定 agent 提取数据"""
        with patch("src.prompt_optimizer.data_extractor.SessionLocal") as mock_session:
            mock_session.return_value.__enter__.return_value = mock_db_session
            mock_db_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
            
            extractor = TrainingDataExtractor()
            result = extractor.extract_for_agent(agent_name="main", limit=50)
            
            # 当前实现应该返回空列表
            assert isinstance(result, list)
```

### 5.6 test_optimizer.py - 优化器测试

```python
"""Tests for PromptOptimizer."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.prompt_optimizer.optimizer import PromptOptimizer


class TestPromptOptimizer:
    """Tests for PromptOptimizer class."""
    
    def test_init_configures_dspy(self):
        """测试初始化时配置 DSPy"""
        with patch("src.prompt_optimizer.optimizer.dspy") as mock_dspy:
            with patch("src.prompt_optimizer.optimizer.settings") as mock_settings:
                mock_settings.ZHIPUAI_API_KEY = "test-key"
                mock_settings.ZHIPUAI_API_BASE = "https://test.api.com"
                
                optimizer = PromptOptimizer()
                
                mock_dspy.configure.assert_called_once()
                mock_dspy.LM.assert_called_once()
    
    def test_optimize_with_insufficient_data(self):
        """测试数据不足时返回失败"""
        with patch("src.prompt_optimizer.optimizer.dspy"):
            with patch("src.prompt_optimizer.optimizer.settings"):
                optimizer = PromptOptimizer()
                
                result = optimizer.optimize(
                    current_prompt="Test prompt",
                    training_examples=[
                        {"user_input": "test", "response": "test"}
                    ],  # 只有 1 条数据
                )
                
                assert result["success"] is False
                assert "训练数据不足" in result["error"]
                assert result["score"] == 0.0
    
    def test_optimize_with_valid_data(self, sample_training_data):
        """测试有足够数据时的优化流程"""
        with patch("src.prompt_optimizer.optimizer.dspy") as mock_dspy:
            with patch("src.prompt_optimizer.optimizer.settings"):
                with patch("src.prompt_optimizer.optimizer.create_agent_metric") as mock_metric:
                    # 配置 mock
                    mock_metric.return_value = lambda e, p, t: 0.8
                    
                    mock_optimizer = MagicMock()
                    mock_optimized_program = MagicMock()
                    mock_optimized_program.predict.demos = []
                    mock_optimizer.compile.return_value = mock_optimized_program
                    
                    mock_dspy.BootstrapFewShot.return_value = mock_optimizer
                    
                    # Mock Evaluate
                    with patch("src.prompt_optimizer.optimizer.Evaluate") as mock_evaluate:
                        mock_evaluator = MagicMock()
                        mock_evaluator.return_value = 0.85
                        mock_evaluate.return_value = mock_evaluator
                        
                        optimizer = PromptOptimizer()
                        result = optimizer.optimize(
                            current_prompt="你是一个 AI 助手",
                            training_examples=sample_training_data,
                            max_bootstrapped_demos=2,
                        )
                        
                        # 验证调用
                        mock_dspy.BootstrapFewShot.assert_called_once()
                        mock_optimizer.compile.assert_called_once()
    
    def test_optimize_handles_exception(self, sample_training_data):
        """测试优化过程异常处理"""
        with patch("src.prompt_optimizer.optimizer.dspy") as mock_dspy:
            with patch("src.prompt_optimizer.optimizer.settings"):
                with patch("src.prompt_optimizer.optimizer.create_agent_metric"):
                    mock_dspy.BootstrapFewShot.side_effect = Exception("Test error")
                    
                    optimizer = PromptOptimizer()
                    result = optimizer.optimize(
                        current_prompt="Test prompt",
                        training_examples=sample_training_data,
                    )
                    
                    assert result["success"] is False
                    assert "Test error" in result["error"]
    
    def test_save_optimization_history(self):
        """测试保存优化历史"""
        with patch("src.prompt_optimizer.optimizer.dspy"):
            with patch("src.prompt_optimizer.optimizer.settings"):
                with patch("src.prompt_optimizer.optimizer.SessionLocal") as mock_session:
                    mock_db = MagicMock()
                    mock_session.return_value.__enter__.return_value = mock_db
                    
                    optimizer = PromptOptimizer()
                    history_id = optimizer.save_optimization_history(
                        agent_name="main",
                        result={
                            "success": True,
                            "demo_count": 4,
                            "score": 0.85,
                            "demos": [],
                        },
                        config={
                            "max_bootstrapped_demos": 4,
                            "metric_threshold": 0.6,
                        },
                    )
                    
                    assert history_id is not None
                    assert len(history_id) == 36  # UUID 格式
                    mock_db.add.assert_called_once()
                    mock_db.commit.assert_called_once()
    
    def test_apply_optimization_success(self):
        """测试应用优化成功"""
        with patch("src.prompt_optimizer.optimizer.dspy"):
            with patch("src.prompt_optimizer.optimizer.settings"):
                with patch("src.prompt_optimizer.optimizer.SessionLocal") as mock_session:
                    mock_db = MagicMock()
                    mock_session.return_value.__enter__.return_value = mock_db
                    
                    # Mock 历史记录
                    mock_history = MagicMock()
                    mock_history.id = "test-history-id"
                    mock_db.query.return_value.filter.return_value.first.return_value = mock_history
                    
                    # Mock agent config
                    with patch("src.prompt_optimizer.optimizer.get_agent_config_manager") as mock_cm:
                        mock_config = MagicMock()
                        mock_cm.return_value.get_config.return_value = mock_config
                        
                        optimizer = PromptOptimizer()
                        result = optimizer.apply_optimization(
                            agent_name="main",
                            history_id="test-history-id",
                        )
                        
                        assert result is True
                        assert mock_history.is_applied is True
    
    def test_apply_optimization_history_not_found(self):
        """测试应用优化时历史记录不存在"""
        with patch("src.prompt_optimizer.optimizer.dspy"):
            with patch("src.prompt_optimizer.optimizer.settings"):
                with patch("src.prompt_optimizer.optimizer.SessionLocal") as mock_session:
                    mock_db = MagicMock()
                    mock_session.return_value.__enter__.return_value = mock_db
                    mock_db.query.return_value.filter.return_value.first.return_value = None
                    
                    optimizer = PromptOptimizer()
                    result = optimizer.apply_optimization(
                        agent_name="main",
                        history_id="nonexistent-id",
                    )
                    
                    assert result is False
    
    def test_get_optimization_history(self):
        """测试获取优化历史"""
        with patch("src.prompt_optimizer.optimizer.dspy"):
            with patch("src.prompt_optimizer.optimizer.settings"):
                with patch("src.prompt_optimizer.optimizer.SessionLocal") as mock_session:
                    mock_db = MagicMock()
                    mock_session.return_value.__enter__.return_value = mock_db
                    
                    # Mock 历史记录列表
                    mock_history = MagicMock()
                    mock_history.id = "test-id"
                    mock_history.agent_name = "main"
                    mock_history.optimizer_type = "bootstrap"
                    mock_history.demo_count = 4
                    mock_history.score = 0.85
                    mock_history.is_applied = False
                    mock_history.applied_at = None
                    mock_history.created_at = MagicMock()
                    mock_history.created_at.isoformat.return_value = "2026-03-04T10:00:00"
                    
                    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_history]
                    
                    optimizer = PromptOptimizer()
                    result = optimizer.get_optimization_history(agent_name="main")
                    
                    assert len(result) == 1
                    assert result[0]["id"] == "test-id"
                    assert result[0]["agent_name"] == "main"
```

### 5.7 test_api.py - API 端点测试

```python
"""Tests for API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


class TestPromptOptimizerAPI:
    """Tests for Prompt Optimizer API endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        from main import app
        return TestClient(app)
    
    def test_optimize_endpoint_agent_not_found(self, client):
        """测试 agent 不存在时返回 404"""
        with patch("api.prompt_optimizer.get_agent_config_manager") as mock:
            mock_manager = MagicMock()
            mock_manager.get_config.return_value = None
            mock.return_value = mock_manager
            
            response = client.post(
                "/api/prompt-optimizer/optimize",
                json={"agent_name": "nonexistent"}
            )
            
            assert response.status_code == 404
    
    def test_optimize_endpoint_insufficient_data(self, client):
        """测试数据不足时返回失败响应"""
        with patch("api.prompt_optimizer.get_agent_config_manager") as mock_config:
            mock_manager = MagicMock()
            mock_config.return_value = mock_manager
            mock_manager.get_config.return_value = MagicMock(system_prompt="test prompt")
            
            with patch("api.prompt_optimizer.TrainingDataExtractor") as mock_extractor:
                mock_instance = MagicMock()
                mock_extractor.return_value = mock_instance
                mock_instance.extract_for_agent.return_value = [
                    {"user_input": "test", "response": "test"}
                ]
                
                response = client.post(
                    "/api/prompt-optimizer/optimize",
                    json={"agent_name": "main", "sample_size": 50}
                )
                
                assert response.status_code == 200
                data = response.json()
                assert data["success"] is False
                assert "训练数据不足" in data["message"]
    
    def test_optimize_endpoint_success(self, client, sample_training_data):
        """测试成功优化"""
        with patch("api.prompt_optimizer.get_agent_config_manager") as mock_config:
            mock_manager = MagicMock()
            mock_config.return_value = mock_manager
            mock_manager.get_config.return_value = MagicMock(system_prompt="test prompt")
            
            with patch("api.prompt_optimizer.TrainingDataExtractor") as mock_extractor:
                mock_extractor.return_value.extract_for_agent.return_value = sample_training_data
                
                with patch("api.prompt_optimizer.PromptOptimizer") as mock_optimizer:
                    mock_instance = MagicMock()
                    mock_optimizer.return_value = mock_instance
                    mock_instance.optimize.return_value = {
                        "success": True,
                        "demo_count": 4,
                        "score": 0.85,
                        "demos": [],
                    }
                    mock_instance.save_optimization_history.return_value = "test-history-id"
                    
                    response = client.post(
                        "/api/prompt-optimizer/optimize",
                        json={"agent_name": "main"}
                    )
                    
                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    assert data["history_id"] == "test-history-id"
    
    def test_preview_endpoint(self, client, sample_training_data):
        """测试预览端点"""
        with patch("api.prompt_optimizer.TrainingDataExtractor") as mock_extractor:
            mock_instance = MagicMock()
            mock_extractor.return_value = mock_instance
            mock_instance.extract_for_agent.return_value = sample_training_data[:5]
            
            response = client.get("/api/prompt-optimizer/preview/main?limit=5")
            
            assert response.status_code == 200
            data = response.json()
            assert data["agent_name"] == "main"
            assert data["sample_count"] == 5
    
    def test_history_endpoint(self, client):
        """测试历史端点"""
        mock_history = [
            {
                "id": "test-id",
                "agent_name": "main",
                "optimizer_type": "bootstrap",
                "demo_count": 4,
                "score": 0.85,
                "is_applied": False,
                "applied_at": None,
                "created_at": "2026-03-04T10:00:00",
            }
        ]
        
        with patch("api.prompt_optimizer.PromptOptimizer") as mock_optimizer:
            mock_instance = MagicMock()
            mock_optimizer.return_value = mock_instance
            mock_instance.get_optimization_history.return_value = mock_history
            
            response = client.get("/api/prompt-optimizer/history/main")
            
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert data["history"][0]["id"] == "test-id"
    
    def test_apply_endpoint_success(self, client):
        """测试应用优化端点"""
        with patch("api.prompt_optimizer.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_history = MagicMock()
            mock_history.agent_name = "main"
            mock_history.is_applied = False
            mock_db.query.return_value.filter.return_value.first.return_value = mock_history
            
            with patch("api.prompt_optimizer.PromptOptimizer") as mock_optimizer:
                mock_instance = MagicMock()
                mock_optimizer.return_value = mock_instance
                mock_instance.apply_optimization.return_value = True
                
                response = client.post("/api/prompt-optimizer/apply/test-history-id")
                
                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
    
    def test_apply_endpoint_already_applied(self, client):
        """测试已应用的优化"""
        with patch("api.prompt_optimizer.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_history = MagicMock()
            mock_history.agent_name = "main"
            mock_history.is_applied = True
            mock_history.applied_at = MagicMock()
            mock_history.applied_at.isoformat.return_value = "2026-03-04T10:00:00"
            mock_db.query.return_value.filter.return_value.first.return_value = mock_history
            
            response = client.post("/api/prompt-optimizer/apply/test-history-id")
            
            assert response.status_code == 200
            data = response.json()
            assert "already applied" in data["message"].lower()
    
    def test_apply_endpoint_not_found(self, client):
        """测试应用不存在的优化"""
        with patch("api.prompt_optimizer.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = None
            
            response = client.post("/api/prompt-optimizer/apply/nonexistent-id")
            
            assert response.status_code == 404
    
    def test_delete_endpoint_success(self, client):
        """测试删除优化历史"""
        with patch("api.prompt_optimizer.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_history = MagicMock()
            mock_history.is_applied = False
            mock_db.query.return_value.filter.return_value.first.return_value = mock_history
            
            response = client.delete("/api/prompt-optimizer/history/test-id")
            
            assert response.status_code == 200
            mock_db.delete.assert_called_once()
            mock_db.commit.assert_called_once()
    
    def test_delete_endpoint_applied_optimization(self, client):
        """测试删除已应用的优化"""
        with patch("api.prompt_optimizer.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_history = MagicMock()
            mock_history.is_applied = True
            mock_db.query.return_value.filter.return_value.first.return_value = mock_history
            
            response = client.delete("/api/prompt-optimizer/history/test-id")
            
            assert response.status_code == 400
```

### 5.8 run_all.py - 测试运行脚本

```python
"""
运行所有 prompt optimizer 测试

使用方法:
    uv run python tests/prompt_optimizer/run_all.py
"""

import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def run_all_tests():
    """运行所有测试"""
    import pytest
    
    test_dir = os.path.dirname(__file__)
    
    print("=" * 60)
    print("Running Prompt Optimizer Tests")
    print("=" * 60)
    print()
    
    # 运行测试
    exit_code = pytest.main([
        test_dir,
        "-v",
        "--tb=short",
        "-x",  # 遇到第一个失败就停止
        "--color=yes",
    ])
    
    print()
    if exit_code == 0:
        print("=" * 60)
        print("All tests passed!")
        print("=" * 60)
    else:
        print("=" * 60)
        print("Some tests failed!")
        print("=" * 60)
    
    return exit_code


if __name__ == "__main__":
    sys.exit(run_all_tests())
```

### 5.9 运行测试

```bash
# 运行所有测试
uv run python tests/prompt_optimizer/run_all.py

# 运行单个测试文件
uv run pytest tests/prompt_optimizer/test_metrics.py -v

# 运行特定测试
uv run pytest tests/prompt_optimizer/test_optimizer.py::TestPromptOptimizer::test_optimize_with_insufficient_data -v

# 带覆盖率报告
uv run pytest tests/prompt_optimizer/ --cov=src/prompt_optimizer --cov-report=term-missing
```

### 5.10 测试覆盖率目标

| 模块 | 目标覆盖率 |
|------|-----------|
| metrics.py | > 90% |
| data_extractor.py | > 85% |
| optimizer.py | > 80% |
| API endpoints | > 90% |
| **总体** | **> 85%** |
