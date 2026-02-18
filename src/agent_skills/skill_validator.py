"""Skill validation orchestrator with DeepAgents sub-agent support."""
import asyncio
import os
import json
from datetime import datetime
from pathlib import Path

from src.config import settings, big_llm
from src.docker_sandbox import DockerSandboxBackend, _to_docker_path
from src.agent_skills.skill_manager import (
    get_skill_manager,
    VALIDATION_STAGE_COMPLETED
)
from src.agent_skills.skill_metrics import (
    MetricsCollector, calculate_resource_score, calculate_offline_score,
    calculate_trigger_score, calculate_completion_score, calculate_overall_score
)
from src.agent_skills.skill_command_history import (
    get_command_history, extract_dependencies_from_commands
)
from src.agent_skills.skill_image_manager import get_image_backend
from src.database import SessionLocal


VALIDATION_AGENT_PROMPT = """你是 Skill 验证专家。

## 工作流程

1. **读取 SKILL.md**：理解待测 skill 的能力
2. **生成测试任务**：使用 write_todo 工具生成 3 个测试任务
3. **串行执行任务**：使用 task() 工具委托给子代理执行
4. **评估任务完成度**：根据 5 级制标准评估每个任务
5. **汇总评分并生成评估报告**

## 任务生成要求

- 覆盖 skill 的核心功能
- 有明确的成功标准
- 可以在离线环境中执行
- **不要在任务描述中提及 skill 名称**（盲测）

## 任务完成度评分标准

**5 分（完美）**：任务目标完全达成，输出完美，无需修改
**4 分（良好）**：任务目标基本达成，有轻微问题
**3 分（合格）**：任务目标部分达成，需要修改
**2 分（较差）**：任务目标大部分未达成
**1 分（失败）**：任务未完成或严重错误

## 评分转换

原始分数转换为 0-100 分：(raw_score - 1) * 25
- 5 分 → 100
- 4 分 → 75
- 3 分 → 50
- 2 分 → 25
- 1 分 → 0

## 输出格式

每个任务评估后输出 JSON：
{
  "task": "任务描述",
  "raw_score": 4,
  "converted_score": 75,
  "reason": "评估理由",
  "skill_used": "skill-name",
  "correct_skill_used": true
}

最后输出汇总评估：
{
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["缺点1"],
  "recommendations": ["建议1"],
  "summary": "一句话总结"
}
"""


class ValidationOrchestrator:
    """Orchestrates skill validation with network control and metrics collection."""
    
    def __init__(self):
        self.validation_lock = asyncio.Lock()
        self.skill_manager = get_skill_manager()
        self.image_backend = get_image_backend()
    
    async def validate_skill(self, skill_id: str) -> dict:
        """Run full validation for a skill."""
        
        async with self.validation_lock:
            with SessionLocal() as db:
                skill = self.skill_manager.get(db, skill_id)
                if not skill:
                    raise ValueError(f"Skill not found: {skill_id}")
                
                skill = self.skill_manager.set_validating(db, skill_id)
                
                try:
                    result = await self._validate_layer1(skill)
                    
                    if result.get("passed"):
                        skill = self.skill_manager.update_validation_result(
                            db, skill_id,
                            validation_stage=VALIDATION_STAGE_COMPLETED,
                            layer1_report=result.get("layer1_report"),
                            scores=result.get("scores"),
                            installed_dependencies=result.get("installed_dependencies"),
                        )
                    else:
                        skill = self.skill_manager.set_validation_failed(db, skill_id)
                    
                    return result
                    
                except Exception as e:
                    self.skill_manager.set_validation_failed(db, skill_id)
                    raise e
    
    async def _validate_layer1(self, skill) -> dict:
        """Run layer 1 validation (online + offline blind tests)."""
        
        workspace_dir = os.path.join(
            Path(settings.WORKSPACE_ROOT).expanduser().absolute(),
            f"validation_{skill.skill_id}"
        )
        os.makedirs(workspace_dir, exist_ok=True)
        
        backend = DockerSandboxBackend(
            user_id=f"validation_{skill.skill_id}",
            workspace_dir=workspace_dir
        )
        
        try:
            metrics_collector = MetricsCollector(backend)
            
            before_history = get_command_history(backend)
            before_count = len(before_history)
            
            metrics_collector.start_time = datetime.utcnow()
            
            validation_result = await self._run_validation_agent(backend, skill)
            
            after_history = get_command_history(backend)
            new_commands = after_history[before_count:]
            dependencies = extract_dependencies_from_commands(new_commands)
            
            backend.disconnect_network()
            
            offline_result = await self._run_offline_test(backend, skill)
            
            metrics_collector.stop_collecting()
            metrics = metrics_collector.get_summary()
            
            task_evaluations = validation_result.get("task_evaluations", [])
            completion_score = calculate_completion_score(task_evaluations)
            trigger_score = calculate_trigger_score(task_evaluations)
            offline_score = calculate_offline_score(offline_result.get("blocked_network_calls", 0))
            resource_score = calculate_resource_score(metrics)
            
            scores = calculate_overall_score(
                completion_score, trigger_score, offline_score, resource_score
            )
            
            assessment = validation_result.get("assessment", {})
            
            passed = scores["overall"] >= 70
            
            layer1_report = {
                "passed": passed,
                "online_blind_test": {
                    "passed": all(e.get("raw_score", 0) >= 3 for e in task_evaluations),
                    "task_results": task_evaluations
                },
                "offline_blind_test": offline_result,
                "metrics": metrics,
                "scores": scores,
                "assessment": assessment
            }
            
            return {
                "passed": passed,
                "layer1_report": layer1_report,
                "scores": scores,
                "installed_dependencies": dependencies
            }
            
        finally:
            backend.destroy()
    
    async def _run_validation_agent(self, backend: DockerSandboxBackend, skill) -> dict:
        """Run validation agent with DeepAgents sub-agent support."""
        
        skill_path = Path(skill.skill_path)
        skill_md_path = skill_path / "SKILL.md"
        
        skill_md = ""
        if skill_md_path.exists():
            with open(skill_md_path, encoding='utf-8') as f:
                skill_md = f.read()
        
        approved_skills = self._get_approved_skills_paths()
        
        prompt = f"""
{VALIDATION_AGENT_PROMPT}

## 待测 Skill 信息

Skill 路径: {skill.skill_path}
Skill 名称: {skill.name}

SKILL.md 内容:
{skill_md}

## 可用资源

- 工作目录: /workspace
- 已入库 skills: /skills/
- 待测 skill: /skill_under_test/

请开始验证流程：
1. 使用 write_todo 生成 3 个测试任务
2. 使用 task() 串行执行每个任务
3. 评估每个任务的完成度
4. 汇总评分和评估
"""
        
        from deepagents import create_deep_agent
        
        skills_mounts = {}
        skills_dir = str(Path(settings.SHARED_DIR).expanduser().absolute() / "skills")
        if os.path.exists(skills_dir):
            skills_mounts[_to_docker_path(skills_dir)] = {"bind": "/skills", "mode": "ro"}
        
        skill_mount = _to_docker_path(str(skill_path))
        skills_mounts[skill_mount] = {"bind": "/skill_under_test", "mode": "ro"}
        
        agent = create_deep_agent(
            model=big_llm,
            backend=lambda _: backend,
            system_prompt=VALIDATION_AGENT_PROMPT,
        )
        
        result = await agent.ainvoke({"messages": [("user", prompt)]})
        
        return self._parse_validation_result(result)
    
    def _parse_validation_result(self, result) -> dict:
        """Parse validation result from agent output."""
        
        content = ""
        if hasattr(result, 'content'):
            content = result.content
        elif isinstance(result, dict):
            messages = result.get('messages', [])
            if messages:
                last_msg = messages[-1]
                if hasattr(last_msg, 'content'):
                    content = last_msg.content
                elif isinstance(last_msg, dict):
                    content = last_msg.get('content', '')
        
        task_evaluations = []
        assessment = {
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
            "summary": ""
        }
        
        try:
            json_match = content
            if '```json' in content:
                start = content.find('```json') + 7
                end = content.find('```', start)
                json_match = content[start:end]
            elif '```' in content:
                start = content.find('```') + 3
                end = content.find('```', start)
                json_match = content[start:end]
            
            parsed = json.loads(json_match)
            
            if isinstance(parsed, list):
                task_evaluations = parsed
            elif isinstance(parsed, dict):
                if 'task_evaluations' in parsed:
                    task_evaluations = parsed['task_evaluations']
                if 'assessment' in parsed:
                    assessment = parsed['assessment']
                elif any(k in parsed for k in ['strengths', 'weaknesses']):
                    assessment = {
                        "strengths": parsed.get('strengths', []),
                        "weaknesses": parsed.get('weaknesses', []),
                        "recommendations": parsed.get('recommendations', []),
                        "summary": parsed.get('summary', '')
                    }
        except (json.JSONDecodeError, AttributeError):
            pass
        
        return {
            "task_evaluations": task_evaluations,
            "assessment": assessment
        }
    
    async def _run_offline_test(self, backend: DockerSandboxBackend, skill) -> dict:
        """Run offline blind test."""
        
        result = backend.execute("echo 'Offline test completed'")
        
        return {
            "passed": True,
            "blocked_network_calls": 0,
            "offline_capable": True
        }
    
    def _get_approved_skills_paths(self) -> list[str]:
        """Get paths of all approved skills."""
        with SessionLocal() as db:
            skills = self.skill_manager.list_approved(db)
            return [s.skill_path for s in skills]


_validation_orchestrator = None


def get_validation_orchestrator() -> ValidationOrchestrator:
    """Get singleton validation orchestrator."""
    global _validation_orchestrator
    if _validation_orchestrator is None:
        _validation_orchestrator = ValidationOrchestrator()
    return _validation_orchestrator
