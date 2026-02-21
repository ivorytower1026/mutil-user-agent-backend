"""Skill 验证编排器 - 双 Sandbox 方案

验证流程：
1. 创建联网 Sandbox → 联网验证
2. 创建离线 Sandbox (network_block_all=True) → 离线验证
3. 销毁两个 Sandbox → 计算评分
"""
import asyncio
import json
import traceback
from pathlib import Path

from src.config import big_llm
from src.daytona_sandbox_manager import get_sandbox_manager
from src.daytona_sandbox import DaytonaSandboxBackend
from src.agent_skills.skill_manager import (
    get_skill_manager,
    STATUS_VALIDATING,
    VALIDATION_STAGE_COMPLETED,
    VALIDATION_STAGE_LAYER1,
)
from src.agent_skills.skill_scorer import (
    calculate_completion_score,
    calculate_trigger_score,
    calculate_offline_score,
    calculate_overall_score,
    is_passing,
)
from src.agent_skills.task_store import get_task_store
from src.agent_skills.prompts import (
    VALIDATION_SYSTEM_PROMPT,
    VALIDATION_PROMPT,
    OFFLINE_SYSTEM_PROMPT,
    OFFLINE_VALIDATION_PROMPT,
)
from src.database import SessionLocal
from src.utils.get_logger import get_logger

logger = get_logger("skill-validator")


class ValidationOrchestrator:
    """Skill 验证编排器"""
    
    def __init__(self):
        self.skill_manager = get_skill_manager()
        self.task_store = get_task_store()
        self.max_concurrent = 5
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._running_validations: dict[str, asyncio.Task] = {}
    
    async def validate_skill(self, skill_id: str) -> dict:
        """验证单个 Skill（后台任务）
        
        Args:
            skill_id: Skill ID
            
        Returns:
            验证结果
        """
        with SessionLocal() as db:
            skill = self.skill_manager.get(db, skill_id)
            if not skill:
                raise ValueError(f"Skill not found: {skill_id}")
            
            self.skill_manager.set_validating(db, skill_id)
        
        try:
            result = await self._validate_single_skill(skill)
            
            with SessionLocal() as db:
                if result["passed"]:
                    self.skill_manager.update_validation_result(
                        db, skill_id,
                        validation_stage=VALIDATION_STAGE_COMPLETED,
                        layer1_report=result.get("layer1_report"),
                        scores=result.get("scores"),
                        installed_dependencies=result.get("installed_dependencies"),
                    )
                else:
                    self.skill_manager.set_validation_failed(db, skill_id)
            
            return result
            
        except Exception as e:
            logger.error(f"[validate_skill] 验证异常: {e}\n{traceback.format_exc()}")
            with SessionLocal() as db:
                self.skill_manager.set_validation_failed(db, skill_id)
            raise
    
    async def run_full_test(self) -> dict:
        """全量测试所有已入库 Skills
        
        Returns:
            全量测试结果
        """
        with SessionLocal() as db:
            approved_skills = self.skill_manager.list_approved(db)
        
        if not approved_skills:
            return {"passed": True, "total_tested": 0, "message": "No skills to test"}
        
        logger.info(f"[run_full_test] 开始全量测试 {len(approved_skills)} 个 Skills")
        
        results = {}
        failed_skills = []
        
        async def test_skill(skill):
            async with self._semaphore:
                try:
                    result = await self._run_full_test_single(skill)
                    return skill.skill_id, result
                except Exception as e:
                    logger.error(f"[run_full_test] 测试失败 skill={skill.name}: {e}")
                    return skill.skill_id, {"passed": False, "error": str(e)}
        
        tasks = [test_skill(s) for s in approved_skills]
        completed = await asyncio.gather(*tasks)
        
        for skill_id, result in completed:
            results[skill_id] = result
            if not result.get("passed"):
                failed_skills.append(skill_id)
            self.task_store.update_full_test_result(skill_id, result)
        
        return {
            "passed": len(failed_skills) == 0,
            "total_tested": len(approved_skills),
            "failed_count": len(failed_skills),
            "failed_skills": failed_skills,
            "results": results
        }
    
    async def _validate_single_skill(self, skill) -> dict:
        """单个 Skill 的完整验证流程（双 Sandbox）
        
        流程：
        1. 创建联网 Sandbox → 联网验证
        2. 创建离线 Sandbox → 离线验证
        3. 销毁两个 Sandbox → 计算评分
        """
        logger.info(f"[_validate_single_skill] 开始验证 skill={skill.name}")
        
        manager = get_sandbox_manager()
        
        try:
            online_backend = manager.get_validation_backend(skill.skill_id)
            logger.info(f"[_validate_single_skill] 联网 Sandbox 已创建")
            
            online_result = await self._run_online_validation(online_backend, skill)
            logger.info(f"[_validate_single_skill] 联网验证完成 passed={online_result.get('passed')}")
            
            if not online_result["passed"]:
                return {
                    "passed": False,
                    "reason": "online_validation_failed",
                    "layer1_report": {
                        "passed": False,
                        "online_blind_test": online_result,
                        "offline_blind_test": None,
                        "scores": None
                    }
                }
            
            self.task_store.save_tasks(skill.skill_id, online_result["tasks"])
            logger.info(f"[_validate_single_skill] 任务已保存到数据库")
            
            offline_backend = manager.get_offline_backend(skill.skill_id)
            logger.info(f"[_validate_single_skill] 离线 Sandbox 已创建")
            
            offline_result = await self._run_offline_validation(
                offline_backend, skill, online_result["tasks"]
            )
            logger.info(f"[_validate_single_skill] 离线验证完成 passed={offline_result.get('passed')}")
            
            scores = calculate_overall_score(
                completion_score=online_result["completion_score"],
                trigger_score=online_result["trigger_score"],
                offline_score=offline_result["offline_score"]
            )
            logger.info(f"[_validate_single_skill] 评分完成 overall={scores['overall']}")
            
            passed = is_passing(scores["overall"])
            
            layer1_report = {
                "passed": passed,
                "online_blind_test": {
                    "passed": all(e.get("raw_score", 0) >= 3 for e in online_result.get("task_evaluations", [])),
                    "task_results": online_result.get("task_evaluations", [])
                },
                "offline_blind_test": offline_result,
                "scores": scores,
                "assessment": online_result.get("assessment", {})
            }
            
            return {
                "passed": passed,
                "layer1_report": layer1_report,
                "scores": scores,
                "installed_dependencies": online_result.get("installed_dependencies", [])
            }
            
        finally:
            logger.info(f"[_validate_single_skill] 销毁验证 Sandboxes")
            manager.destroy_validation_backends(skill.skill_id)
    
    async def _run_online_validation(
        self, 
        backend: DaytonaSandboxBackend, 
        skill
    ) -> dict:
        """联网验证
        
        Args:
            backend: 联网 Sandbox
            skill: Skill 对象
            
        Returns:
            验证结果
        """
        logger.info(f"[_run_online_validation] 开始联网验证 skill={skill.name}")
        
        skill_md = self._read_skill_md(skill.skill_path)
        
        prompt = VALIDATION_PROMPT.format(
            skill_name=skill.name,
            skill_md=skill_md
        )
        
        from deepagents import create_deep_agent
        
        agent = create_deep_agent(
            model=big_llm,
            backend=lambda _: backend,
            system_prompt=VALIDATION_SYSTEM_PROMPT,
        )
        
        logger.info(f"[_run_online_validation] 开始执行 Agent")
        result = await agent.ainvoke({"messages": [("user", prompt)]})
        
        parsed = self._parse_validation_result(result)
        logger.info(f"[_run_online_validation] 解析完成 tasks={len(parsed.get('tasks', []))}")
        
        completion_score = calculate_completion_score(parsed.get("task_evaluations", []))
        trigger_score = calculate_trigger_score(parsed.get("task_evaluations", []))
        
        return {
            "passed": completion_score >= 50,
            "tasks": parsed.get("tasks", []),
            "task_evaluations": parsed.get("task_evaluations", []),
            "completion_score": completion_score,
            "trigger_score": trigger_score,
            "assessment": parsed.get("assessment", {}),
            "installed_dependencies": []
        }
    
    async def _run_offline_validation(
        self, 
        backend: DaytonaSandboxBackend, 
        skill,
        tasks: list[dict]
    ) -> dict:
        """离线验证
        
        Args:
            backend: 离线 Sandbox (network_block_all=True)
            skill: Skill 对象
            tasks: 从联网验证复用的任务
            
        Returns:
            离线验证结果
        """
        logger.info(f"[_run_offline_validation] 开始离线验证 skill={skill.name}")
        
        test_result = backend.execute("curl -s --connect-timeout 2 http://google.com 2>&1 || echo 'BLOCKED'")
        output = test_result.output if hasattr(test_result, 'output') else str(test_result)
        
        if "BLOCKED" not in output and "Network is unreachable" not in output:
            logger.warning(f"[_run_offline_validation] 网络未被阻断: {output[:100]}")
        else:
            logger.info(f"[_run_offline_validation] 网络已被阻断（预期）")
        
        tasks_json = json.dumps(tasks, ensure_ascii=False, indent=2)
        prompt = OFFLINE_VALIDATION_PROMPT.format(
            skill_name=skill.name,
            tasks=tasks_json
        )
        
        from deepagents import create_deep_agent
        
        agent = create_deep_agent(
            model=big_llm,
            backend=lambda _: backend,
            system_prompt=OFFLINE_SYSTEM_PROMPT,
        )
        
        result = await agent.ainvoke({"messages": [("user", prompt)]})
        parsed = self._parse_offline_result(result)
        
        blocked_network_calls = parsed.get("blocked_network_calls", 0)
        offline_score = calculate_offline_score(blocked_network_calls)
        
        logger.info(f"[_run_offline_validation] 离线评分 blocked_calls={blocked_network_calls} score={offline_score}")
        
        return {
            "passed": offline_score >= 70,
            "blocked_network_calls": blocked_network_calls,
            "offline_score": offline_score,
            "offline_capable": blocked_network_calls == 0
        }
    
    async def _run_full_test_single(self, skill) -> dict:
        """单个 Skill 的全量测试
        
        复用之前的 3 个任务 + 新生成 2 个任务 = 5 个任务
        """
        logger.info(f"[_run_full_test_single] 开始全量测试 skill={skill.name}")
        
        old_tasks = self.task_store.get_tasks(skill.skill_id)
        new_tasks = await self._generate_extra_tasks(skill, count=2)
        
        all_tasks = self.task_store.merge_tasks(old_tasks, new_tasks)
        logger.info(f"[_run_full_test_single] 任务合并完成 old={len(old_tasks)} new={len(new_tasks)} total={len(all_tasks)}")
        
        return await self._validate_single_skill(skill)
    
    async def _generate_extra_tasks(self, skill, count: int = 2) -> list[dict]:
        """生成额外的测试任务
        
        Args:
            skill: Skill 对象
            count: 需要生成的任务数量
            
        Returns:
            新任务列表
        """
        logger.info(f"[_generate_extra_tasks] 生成 {count} 个额外任务 skill={skill.name}")
        
        existing_tasks = self.task_store.get_tasks(skill.skill_id)
        existing_descriptions = [t.get("task", "") for t in existing_tasks]
        
        skill_md = self._read_skill_md(skill.skill_path)
        
        prompt = f"""请为以下 Skill 生成 {count} 个额外的测试任务。

Skill 名称: {skill.name}

Skill 描述:
{skill_md[:1000]}

已有任务（不要重复）:
{json.dumps(existing_descriptions, ensure_ascii=False)}

要求：
1. 覆盖 Skill 还未测试的功能点
2. 增加一些边界情况测试
3. 任务应该具体、可执行

输出 JSON 数组格式：
[
  {{"task_id": 1, "task": "任务描述"}},
  ...
]
"""
        
        response = await big_llm.ainvoke(prompt)
        content = response.content if hasattr(response, 'content') else str(response)
        
        try:
            if '```json' in content:
                start = content.find('```json') + 7
                end = content.find('```', start)
                json_str = content[start:end]
            elif '[' in content:
                start = content.find('[')
                end = content.rfind(']') + 1
                json_str = content[start:end]
            else:
                json_str = content
            
            tasks = json.loads(json_str)
            for i, task in enumerate(tasks):
                task["task_id"] = len(existing_tasks) + i + 1
                task["is_new"] = True
            
            logger.info(f"[_generate_extra_tasks] 生成完成 tasks={len(tasks)}")
            return tasks
            
        except json.JSONDecodeError as e:
            logger.warning(f"[_generate_extra_tasks] JSON 解析失败: {e}")
            return []
    
    def _read_skill_md(self, skill_path: str) -> str:
        """读取 SKILL.md 内容"""
        skill_md_path = Path(skill_path) / "SKILL.md"
        if skill_md_path.exists():
            with open(skill_md_path, encoding='utf-8') as f:
                return f.read()
        return ""
    
    def _parse_validation_result(self, result) -> dict:
        """解析验证结果"""
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
        
        tasks = []
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
            
            if isinstance(parsed, dict):
                tasks = parsed.get('tasks', [])
                task_evaluations = parsed.get('task_evaluations', [])
                if 'assessment' in parsed:
                    assessment = parsed['assessment']
            elif isinstance(parsed, list):
                task_evaluations = parsed
                
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"[_parse_validation_result] JSON 解析失败: {e}")
        
        return {
            "tasks": tasks,
            "task_evaluations": task_evaluations,
            "assessment": assessment
        }
    
    def _parse_offline_result(self, result) -> dict:
        """解析离线验证结果"""
        content = ""
        if hasattr(result, 'content'):
            content = result.content
        elif isinstance(result, dict):
            messages = result.get('messages', [])
            if messages:
                last_msg = messages[-1]
                if hasattr(last_msg, 'content'):
                    content = last_msg.content
        
        try:
            if '```json' in content:
                start = content.find('```json') + 7
                end = content.find('```', start)
                json_str = content[start:end]
            elif '{' in content:
                start = content.find('{')
                end = content.rfind('}') + 1
                json_str = content[start:end]
            else:
                json_str = content
            
            return json.loads(json_str)
            
        except json.JSONDecodeError as e:
            logger.warning(f"[_parse_offline_result] JSON 解析失败: {e}")
            return {"blocked_network_calls": 0, "offline_capable": True}


_validation_orchestrator = None


def get_validation_orchestrator() -> ValidationOrchestrator:
    """获取验证编排器单例"""
    global _validation_orchestrator
    if _validation_orchestrator is None:
        _validation_orchestrator = ValidationOrchestrator()
    return _validation_orchestrator
