"""任务存储模块 - 供全量测试复用任务"""
import json
from datetime import datetime
from typing import Any

from src.database import SessionLocal, Skill
from src.utils.get_logger import get_logger

logger = get_logger("task-store")


class TaskStore:
    """任务存储，用于保存验证任务供全量测试复用"""
    
    def save_tasks(self, skill_id: str, tasks: list[dict]) -> None:
        """保存验证任务到数据库
        
        Args:
            skill_id: Skill ID
            tasks: 任务列表
        """
        with SessionLocal() as db:
            skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
            if skill:
                skill.validation_tasks = tasks
                db.commit()
                logger.info(f"[save_tasks] 保存 {len(tasks)} 个任务 skill_id={skill_id}")
    
    def get_tasks(self, skill_id: str) -> list[dict]:
        """获取之前验证时的任务
        
        Args:
            skill_id: Skill ID
            
        Returns:
            任务列表，如果没有则返回空列表
        """
        with SessionLocal() as db:
            skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
            if skill and skill.validation_tasks:
                logger.info(f"[get_tasks] 获取到 {len(skill.validation_tasks)} 个任务 skill_id={skill_id}")
                return skill.validation_tasks
        return []
    
    def merge_tasks(self, old_tasks: list[dict], new_tasks: list[dict]) -> list[dict]:
        """合并旧任务和新任务
        
        Args:
            old_tasks: 旧任务列表
            new_tasks: 新任务列表
            
        Returns:
            合并后的任务列表
        """
        merged = list(old_tasks)
        for task in new_tasks:
            task["is_new"] = True
            merged.append(task)
        return merged
    
    def update_full_test_result(
        self, 
        skill_id: str, 
        result: dict
    ) -> None:
        """更新全量测试结果
        
        Args:
            skill_id: Skill ID
            result: 测试结果
        """
        with SessionLocal() as db:
            skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
            if skill:
                skill.full_test_results = result
                skill.last_full_test_at = datetime.utcnow()
                db.commit()
                logger.info(f"[update_full_test_result] 更新全量测试结果 skill_id={skill_id}")


_task_store = None


def get_task_store() -> TaskStore:
    """获取 TaskStore 单例"""
    global _task_store
    if _task_store is None:
        _task_store = TaskStore()
    return _task_store
