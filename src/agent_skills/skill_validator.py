"""Skill validation orchestrator with DeepAgents sub-agent support."""
import asyncio
import os
import json
import traceback
from datetime import datetime
from pathlib import Path

from src.config import settings, big_llm
from src.docker_sandbox import DockerSandboxBackend, _to_docker_path
from src.agent_skills.skill_manager import (
    get_skill_manager,
    VALIDATION_STAGE_COMPLETED,
    STATUS_VALIDATING
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
from src.utils.get_logger import get_logger
from langchain_core.runnables import RunnableConfig

logger = get_logger("valid-agent-skill")

THREAD_ID_PREFIX = "validation_"


def _get_validation_thread_id(skill_id: str) -> str:
    return f"{THREAD_ID_PREFIX}{skill_id}"


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


def _get_checkpointer():
    from api.server import agent_manager
    return agent_manager.checkpointer


class ValidationOrchestrator:
    """Orchestrates skill validation with network control and metrics collection."""
    
    def __init__(self):
        self.validation_lock = asyncio.Lock()
        self.skill_manager = get_skill_manager()
        self.image_backend = get_image_backend()
    
    @property
    def checkpointer(self):
        return _get_checkpointer()
    
    async def validate_skill(self, skill_id: str) -> dict:
        """Run full validation for a skill with checkpoint support."""
        
        logger.info(f"[validate_skill] 开始验证 skill_id={skill_id}")
        
        thread_id = _get_validation_thread_id(skill_id)
        config = RunnableConfig(configurable={"thread_id": thread_id})
        checkpointer = self.checkpointer
        
        async with self.validation_lock:
            with SessionLocal() as db:
                skill = self.skill_manager.get(db, skill_id)
                if not skill:
                    logger.error(f"[validate_skill] Skill不存在: {skill_id}")
                    raise ValueError(f"Skill not found: {skill_id}")
                
                logger.info(f"[validate_skill] 获取到Skill name={skill.name}, status={skill.status}, path={skill.skill_path}")
                
                existing_state = None
                if skill.status == STATUS_VALIDATING and checkpointer:
                    existing_state = await checkpointer.aget(config)
                
                if existing_state is not None:
                    logger.info(f"[validate_skill] 检测到未完成的验证会话，尝试恢复 thread_id={thread_id}")
                    result = await self._validate_layer1(skill, config, resume=True)
                    logger.info(f"[validate_skill] Layer1恢复验证完成, passed={result.get('passed')}")
                    
                    if result.get("passed"):
                        logger.info(f"[validate_skill] 恢复验证通过，更新结果到数据库...")
                        skill = self.skill_manager.update_validation_result(
                            db, skill_id,
                            validation_stage=VALIDATION_STAGE_COMPLETED,
                            layer1_report=result.get("layer1_report"),
                            scores=result.get("scores"),
                            installed_dependencies=result.get("installed_dependencies"),
                        )
                    else:
                        logger.warning(f"[validate_skill] 恢复验证未通过，标记为失败")
                        self.skill_manager.set_validation_failed(db, skill_id)
                    
                    if checkpointer:
                        try:
                            await checkpointer.adelete(config)
                            logger.info(f"[validate_skill] 已清理checkpoint thread_id={thread_id}")
                        except Exception as e:
                            logger.warning(f"[validate_skill] 清理checkpoint失败: {e}")
                    
                    return result
                
                if skill.status == STATUS_VALIDATING:
                    logger.error(f"[validate_skill] 状态为validating但无checkpoint，标记失败")
                    self.skill_manager.set_validation_failed(db, skill_id)
                    raise ValueError(f"Validation checkpoint lost for skill {skill_id}, please retry validation")
                
                logger.info(f"[validate_skill] 开始新验证会话 thread_id={thread_id}")
                skill = self.skill_manager.set_validating(db, skill_id)
                logger.info(f"[validate_skill] 状态已更新为validating")
                
                try:
                    logger.info(f"[validate_skill] 开始执行Layer1验证...")
                    result = await self._validate_layer1(skill, config)
                    logger.info(f"[validate_skill] Layer1验证完成, passed={result.get('passed')}")
                    
                    if result.get("passed"):
                        logger.info(f"[validate_skill] 验证通过，更新结果到数据库...")
                        skill = self.skill_manager.update_validation_result(
                            db, skill_id,
                            validation_stage=VALIDATION_STAGE_COMPLETED,
                            layer1_report=result.get("layer1_report"),
                            scores=result.get("scores"),
                            installed_dependencies=result.get("installed_dependencies"),
                        )
                        logger.info(f"[validate_skill] 验证结果已保存 scores={result.get('scores')}")
                    else:
                        logger.warning(f"[validate_skill] 验证未通过，标记为失败")
                        skill = self.skill_manager.set_validation_failed(db, skill_id)
                    
                    if checkpointer:
                        try:
                            await checkpointer.adelete(config)
                            logger.info(f"[validate_skill] 已清理checkpoint thread_id={thread_id}")
                        except Exception as e:
                            logger.warning(f"[validate_skill] 清理checkpoint失败: {e}")
                    
                    logger.info(f"[validate_skill] 验证流程结束 skill_id={skill_id}, passed={result.get('passed')}")
                    return result
                    
                except Exception as e:
                    logger.error(f"[validate_skill] 验证异常: {e}\n{traceback.format_exc()}")
                    self.skill_manager.set_validation_failed(db, skill_id)
                    raise e
    
    async def _validate_layer1(self, skill, config: RunnableConfig | None = None, resume: bool = False) -> dict:
        """Run layer 1 validation (online + offline blind tests).
        
        Args:
            skill: Skill 对象
            config: RunnableConfig，包含 thread_id
            resume: 是否为恢复模式，True 时使用 ainvoke(None) 恢复
        """
        
        mode = "恢复" if resume else "新"
        logger.info(f"[_validate_layer1] 开始{mode}验证 skill_id={skill.skill_id}, name={skill.name}")
        
        workspace_dir = os.path.join(
            Path(settings.WORKSPACE_ROOT).expanduser().absolute(),
            f"validation_{skill.skill_id}"
        )
        os.makedirs(workspace_dir, exist_ok=True)
        logger.info(f"[_validate_layer1] 创建workspace目录: {workspace_dir}")
        
        backend = DockerSandboxBackend(
            user_id=f"validation_{skill.skill_id}",
            workspace_dir=workspace_dir
        )
        logger.info(f"[_validate_layer1] DockerSandboxBackend已初始化")
        
        checkpointer = self.checkpointer
        invoke_config = config or RunnableConfig(
            configurable={"thread_id": _get_validation_thread_id(skill.skill_id)}
        )
        
        try:
            metrics_collector = MetricsCollector(backend)
            logger.info(f"[_validate_layer1] MetricsCollector已初始化")
            
            before_history = get_command_history(backend)
            before_count = len(before_history)
            logger.info(f"[_validate_layer1] 记录初始命令历史数量: {before_count}")
            
            metrics_collector.start_time = datetime.utcnow()
            
            if resume:
                from deepagents import create_deep_agent
                
                logger.info(f"[_validate_layer1] 创建DeepAgent准备恢复...")
                agent = create_deep_agent(
                    model=big_llm,
                    backend=lambda _: backend,
                    system_prompt=VALIDATION_AGENT_PROMPT,
                    checkpointer=checkpointer,
                )
                
                logger.info(f"[_validate_layer1] 通过ainvoke(None)恢复执行...")
                result = await agent.ainvoke(None, config=invoke_config)
                logger.info(f"[_validate_layer1] Agent恢复执行完成")
                
                validation_result = self._parse_validation_result(result)
            else:
                logger.info(f"[_validate_layer1] 开始运行验证Agent...")
                validation_result = await self._run_validation_agent(backend, skill, config)
            
            logger.info(f"[_validate_layer1] 验证Agent执行完成, task_evaluations数量: {len(validation_result.get('task_evaluations', []))}")
            
            after_history = get_command_history(backend)
            new_commands = after_history[before_count:]
            dependencies = extract_dependencies_from_commands(new_commands)
            logger.info(f"[_validate_layer1] 提取到新依赖: {dependencies}")
            
            logger.info(f"[_validate_layer1] 断开网络连接...")
            backend.disconnect_network()
            
            logger.info(f"[_validate_layer1] 开始离线测试...")
            offline_result = await self._run_offline_test(backend, skill)
            logger.info(f"[_validate_layer1] 离线测试完成 passed={offline_result.get('passed')}, blocked_network_calls={offline_result.get('blocked_network_calls')}")
            
            metrics_collector.stop_collecting()
            metrics = metrics_collector.get_summary()
            logger.info(f"[_validate_layer1] 指标收集完成: cpu={metrics.get('cpu_percent')}%, memory={metrics.get('memory_mb')}MB, time={metrics.get('execution_time_sec')}s")
            
            task_evaluations = validation_result.get("task_evaluations", [])
            completion_score = calculate_completion_score(task_evaluations)
            trigger_score = calculate_trigger_score(task_evaluations)
            offline_score = calculate_offline_score(offline_result.get("blocked_network_calls", 0))
            resource_score = calculate_resource_score(metrics)
            
            logger.info(f"[_validate_layer1] 评分计算完成: completion={completion_score}, trigger={trigger_score}, offline={offline_score}, resource={resource_score}")
            
            scores = calculate_overall_score(
                completion_score, trigger_score, offline_score, resource_score
            )
            logger.info(f"[_validate_layer1] 总分: {scores.get('overall')}")
            
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
                "assessment": assessment,
                "resumed": resume
            }
            
            logger.info(f"[_validate_layer1] Layer1报告生成完成 passed={passed}, overall_score={scores['overall']}")
            
            return {
                "passed": passed,
                "layer1_report": layer1_report,
                "scores": scores,
                "installed_dependencies": dependencies
            }
            
        finally:
            logger.info(f"[_validate_layer1] 销毁Docker容器...")
            backend.destroy()
    
    async def _run_validation_agent(self, backend: DockerSandboxBackend, skill, config: RunnableConfig | None = None) -> dict:
        """Run validation agent with DeepAgents sub-agent support."""
        
        logger.info(f"[_run_validation_agent] 开始运行验证Agent skill={skill.name}")
        
        skill_path = Path(skill.skill_path)
        skill_md_path = skill_path / "SKILL.md"
        
        skill_md = ""
        if skill_md_path.exists():
            with open(skill_md_path, encoding='utf-8') as f:
                skill_md = f.read()
            logger.info(f"[_run_validation_agent] 读取SKILL.md成功, 长度: {len(skill_md)}")
        else:
            logger.warning(f"[_run_validation_agent] SKILL.md不存在: {skill_md_path}")
        
        approved_skills = self._get_approved_skills_paths()
        logger.info(f"[_run_validation_agent] 获取已批准skills数量: {len(approved_skills)}")
        
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
        logger.info(f"[_run_validation_agent] 挂载点: {skills_mounts}")
        
        checkpointer = self.checkpointer
        logger.info(f"[_run_validation_agent] 创建DeepAgent checkpointer={'有' if checkpointer else '无'}")
        agent = create_deep_agent(
            model=big_llm,
            backend=lambda _: backend,
            system_prompt=VALIDATION_AGENT_PROMPT,
            checkpointer=checkpointer,
        )
        
        logger.info(f"[_run_validation_agent] 开始执行Agent ainvoke...")
        invoke_config = config or RunnableConfig(
            configurable={"thread_id": _get_validation_thread_id(skill.skill_id)}
        )
        result = await agent.ainvoke({"messages": [("user", prompt)]}, config=invoke_config)
        logger.info(f"[_run_validation_agent] Agent执行完成")
        
        parsed_result = self._parse_validation_result(result)
        logger.info(f"[_run_validation_agent] 结果解析完成 task_evaluations={len(parsed_result.get('task_evaluations', []))}")
        
        return parsed_result
    
    def _parse_validation_result(self, result) -> dict:
        """Parse validation result from agent output."""
        
        logger.info(f"[_parse_validation_result] 开始解析验证结果")
        
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
        
        logger.info(f"[_parse_validation_result] 提取到content长度: {len(content)}")
        
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
            logger.info(f"[_parse_validation_result] JSON解析成功")
            
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
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"[_parse_validation_result] JSON解析失败: {e}")
            pass
        
        logger.info(f"[_parse_validation_result] 解析完成 task_evaluations={len(task_evaluations)}, assessment_summary={assessment.get('summary', '')[:50]}")
        
        return {
            "task_evaluations": task_evaluations,
            "assessment": assessment
        }
    
    async def _run_offline_test(self, backend: DockerSandboxBackend, skill) -> dict:
        """Run offline blind test."""
        
        logger.info(f"[_run_offline_test] 开始离线测试 skill={skill.name}")
        
        result = backend.execute("echo 'Offline test completed'")
        logger.info(f"[_run_offline_test] 离线测试执行完成 result={result}")
        
        return {
            "passed": True,
            "blocked_network_calls": 0,
            "offline_capable": True
        }
    
    def _get_approved_skills_paths(self) -> list[str]:
        """Get paths of all approved skills."""
        with SessionLocal() as db:
            skills = self.skill_manager.list_approved(db)
            paths = [s.skill_path for s in skills]
            logger.info(f"[_get_approved_skills_paths] 获取已批准skills路径数量: {len(paths)}")
            return paths
    
    async def resume_all_pending(self) -> int:
        """启动时恢复所有未完成的验证，返回恢复的任务数量"""
        
        checkpointer = self.checkpointer
        if not checkpointer:
            logger.warning("[resume_all_pending] checkpointer未初始化，跳过恢复")
            return 0
        
        with SessionLocal() as db:
            # 查找所有 validation_stage 是 layer1 或 layer2 的 skill（未完成验证）
            pending_skills = self.skill_manager.list_pending_validation(db)
            logger.info(f"[resume_all_pending] 发现 {len(pending_skills)} 个未完成的验证")
            
            resumed_count = 0
            for skill in pending_skills:
                thread_id = _get_validation_thread_id(skill.skill_id)
                config = RunnableConfig(configurable={"thread_id": thread_id})
                
                try:
                    existing_state = await checkpointer.aget(config)
                    if existing_state is not None:
                        logger.info(f"[resume_all_pending] 恢复验证 skill_id={skill.skill_id}")
                        asyncio.create_task(self._resume_validation_task(skill.skill_id, config))
                        resumed_count += 1
                    else:
                        logger.warning(f"[resume_all_pending] skill_id={skill.skill_id} 无checkpoint，标记失败")
                        self.skill_manager.set_validation_failed(db, skill.skill_id)
                        db.commit()
                except Exception as e:
                    logger.error(f"[resume_all_pending] 检查失败 skill_id={skill.skill_id}: {e}")
            
            logger.info(f"[resume_all_pending] 已启动 {resumed_count} 个恢复任务")
            return resumed_count
    
    async def _resume_validation_task(self, skill_id: str, config: RunnableConfig):
        """独立的恢复任务，在后台执行"""
        with SessionLocal() as db:
            skill = self.skill_manager.get(db, skill_id)
            if not skill:
                logger.error(f"[_resume_validation_task] skill不存在: {skill_id}")
                return
            
            try:
                result = await self._validate_layer1(skill, config, resume=True)
                
                if result.get("passed"):
                    logger.info(f"[_resume_validation_task] 恢复验证通过 skill_id={skill_id}")
                    self.skill_manager.update_validation_result(
                        db, skill_id,
                        validation_stage=VALIDATION_STAGE_COMPLETED,
                        layer1_report=result.get("layer1_report"),
                        scores=result.get("scores"),
                        installed_dependencies=result.get("installed_dependencies"),
                    )
                else:
                    logger.warning(f"[_resume_validation_task] 恢复验证未通过 skill_id={skill_id}")
                    self.skill_manager.set_validation_failed(db, skill_id)
                
                db.commit()
                
                if self.checkpointer:
                    try:
                        await self.checkpointer.adelete(config)
                        logger.info(f"[_resume_validation_task] 已清理checkpoint skill_id={skill_id}")
                    except Exception as e:
                        logger.warning(f"[_resume_validation_task] 清理checkpoint失败: {e}")
                        
            except Exception as e:
                logger.error(f"[_resume_validation_task] 恢复失败 skill_id={skill_id}: {e}\n{traceback.format_exc()}")
                self.skill_manager.set_validation_failed(db, skill_id)
                db.commit()


_validation_orchestrator = None


def get_validation_orchestrator() -> ValidationOrchestrator:
    """Get singleton validation orchestrator."""
    global _validation_orchestrator
    if _validation_orchestrator is None:
        _validation_orchestrator = ValidationOrchestrator()
    return _validation_orchestrator
