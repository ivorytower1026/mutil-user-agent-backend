"""Skill 格式验证模块"""
import os
from pathlib import Path
from typing import Any

from src.utils.get_logger import get_logger

logger = get_logger("format-validator")


class FormatValidator:
    """Skill 格式验证器"""
    
    def validate(self, skill_path: str) -> dict:
        """验证 Skill 格式
        
        Args:
            skill_path: Skill 目录路径
            
        Returns:
            {
                "valid": bool,
                "errors": list[str],
                "warnings": list[str],
                "metadata": dict  # 从 SKILL.md 解析的元数据
            }
        """
        errors = []
        warnings = []
        metadata = {}
        
        skill_md_result = self._check_skill_md(skill_path)
        if not skill_md_result["valid"]:
            errors.extend(skill_md_result["errors"])
            return {
                "valid": False,
                "errors": errors,
                "warnings": warnings,
                "metadata": metadata
            }
        
        metadata = skill_md_result.get("metadata", {})
        
        structure_result = self._check_file_structure(skill_path)
        warnings.extend(structure_result.get("warnings", []))
        
        field_errors = self._validate_required_fields(metadata)
        errors.extend(field_errors)
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "metadata": metadata
        }
    
    def _check_skill_md(self, skill_path: str) -> dict:
        """检查 SKILL.md 文件
        
        Args:
            skill_path: Skill 目录路径
            
        Returns:
            {"valid": bool, "errors": list, "metadata": dict}
        """
        skill_md_path = os.path.join(skill_path, "SKILL.md")
        errors = []
        metadata = {}
        
        if not os.path.exists(skill_md_path):
            errors.append("Missing SKILL.md")
            return {"valid": False, "errors": errors, "metadata": metadata}
        
        with open(skill_md_path, encoding='utf-8') as f:
            content = f.read()
        
        if not content.strip():
            errors.append("SKILL.md is empty")
            return {"valid": False, "errors": errors, "metadata": metadata}
        
        try:
            from deepagents.middleware.skills import _parse_skill_metadata
            directory_name = os.path.basename(skill_path)
            metadata = _parse_skill_metadata(content, skill_md_path, directory_name)
            
            if metadata is None:
                errors.append("Invalid frontmatter format or missing name/description")
                return {"valid": False, "errors": errors, "metadata": {}}
                
        except Exception as e:
            logger.warning(f"[_check_skill_md] 解析 SKILL.md 失败: {e}")
            errors.append(f"Failed to parse SKILL.md: {e}")
            return {"valid": False, "errors": errors, "metadata": metadata}
        
        return {"valid": True, "errors": [], "metadata": metadata}
    
    def _check_file_structure(self, skill_path: str) -> dict:
        """检查文件结构
        
        Args:
            skill_path: Skill 目录路径
            
        Returns:
            {"warnings": list}
        """
        warnings = []
        
        scripts_path = os.path.join(skill_path, "scripts")
        if not os.path.exists(scripts_path):
            warnings.append("No scripts/ directory (optional)")
        
        return {"warnings": warnings}
    
    def _validate_required_fields(self, metadata: dict) -> list[str]:
        """验证必填字段
        
        Args:
            metadata: 从 SKILL.md 解析的元数据
            
        Returns:
            错误列表
        """
        errors = []
        
        if not metadata.get("name"):
            errors.append("Missing required field: name")
        
        if not metadata.get("description"):
            errors.append("Missing required field: description")
        
        return errors


def validate_skill_format(skill_path: str) -> tuple[bool, list[str], list[str], dict]:
    """验证 Skill 格式（便捷函数）
    
    Args:
        skill_path: Skill 目录路径
        
    Returns:
        (valid, errors, warnings, metadata)
    """
    validator = FormatValidator()
    result = validator.validate(skill_path)
    return (
        result["valid"],
        result["errors"],
        result["warnings"],
        result["metadata"]
    )
