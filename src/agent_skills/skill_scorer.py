"""Skill 评分计算模块（3维评分）

评分维度：
- completion_score (50%): 任务完成度
- trigger_score (35%): 触发准确性
- offline_score (15%): 离线能力
"""


def calculate_completion_score(task_evaluations: list[dict]) -> float:
    """计算任务完成度评分
    
    Args:
        task_evaluations: 任务评估列表，每个包含 raw_score (1-5) 或 converted_score (0-100)
        
    Returns:
        平均完成度分数 (0-100)
    """
    if not task_evaluations:
        return 0.0
    
    scores = []
    for e in task_evaluations:
        if "converted_score" in e:
            scores.append(e["converted_score"])
        elif "raw_score" in e:
            scores.append(convert_raw_score(e["raw_score"]))
    
    return round(sum(scores) / len(scores), 1) if scores else 0.0


def convert_raw_score(raw_score: int) -> int:
    """将原始分数 (1-5) 转换为 0-100 分
    
    转换规则：
    - 5 分 → 100
    - 4 分 → 75
    - 3 分 → 50
    - 2 分 → 25
    - 1 分 → 0
    
    公式：(raw_score - 1) * 25
    """
    if raw_score < 1:
        return 0
    if raw_score > 5:
        return 100
    return (raw_score - 1) * 25


def calculate_trigger_score(task_evaluations: list[dict]) -> float:
    """计算触发准确性评分
    
    Args:
        task_evaluations: 任务评估列表，每个包含 correct_skill_used (bool)
        
    Returns:
        正确触发的任务比例 (0-100)
    """
    if not task_evaluations:
        return 0.0
    
    correct = sum(1 for e in task_evaluations if e.get("correct_skill_used", False))
    return round((correct / len(task_evaluations)) * 100, 1)


def calculate_offline_score(blocked_network_calls: int) -> int:
    """计算离线能力评分
    
    Args:
        blocked_network_calls: 违规网络调用次数
        
    Returns:
        离线能力分数 (0-100)
        
    评分规则：
    - 0 次违规 → 100
    - 1-2 次违规 → 70
    - 3+ 次违规 → 0
    """
    if blocked_network_calls == 0:
        return 100
    elif blocked_network_calls <= 2:
        return 70
    else:
        return 0


def calculate_overall_score(
    completion_score: float,
    trigger_score: float,
    offline_score: float
) -> dict:
    """计算总分（3维加权）
    
    权重：
    - completion: 50%
    - trigger: 35%
    - offline: 15%
    
    Args:
        completion_score: 任务完成度分数 (0-100)
        trigger_score: 触发准确性分数 (0-100)
        offline_score: 离线能力分数 (0-100)
        
    Returns:
        包含各维度分数和总分的字典
    """
    weights = {
        "completion": 0.50,
        "trigger": 0.35,
        "offline": 0.15
    }
    
    overall = (
        completion_score * weights["completion"] +
        trigger_score * weights["trigger"] +
        offline_score * weights["offline"]
    )
    
    return {
        "completion_score": round(completion_score, 1),
        "trigger_score": round(trigger_score, 1),
        "offline_score": offline_score,
        "overall": round(overall, 1),
        "weights": weights
    }


def is_passing(overall_score: float, threshold: float = 70.0) -> bool:
    """判断是否通过验证
    
    Args:
        overall_score: 总分
        threshold: 通过阈值，默认 70
        
    Returns:
        是否通过
    """
    return overall_score >= threshold
