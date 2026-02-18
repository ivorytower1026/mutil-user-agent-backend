"""Metrics collector for skill validation monitoring."""
import asyncio
import time
from datetime import datetime


class MetricsCollector:
    """Collect execution metrics from Docker container."""
    
    def __init__(self, backend):
        self.backend = backend
        self.samples = []
        self.start_time = None
        self._collecting = False
    
    async def start_collecting(self, interval: float = 1.0):
        """Start collecting metrics at specified interval."""
        self.samples = []
        self.start_time = time.time()
        self._collecting = True
        
        while self._collecting:
            stats = self.backend.get_container_stats()
            stats["timestamp"] = time.time()
            self.samples.append(stats)
            await asyncio.sleep(interval)
    
    def stop_collecting(self):
        """Stop collecting metrics."""
        self._collecting = False
    
    def get_summary(self) -> dict:
        """Get summarized metrics."""
        if not self.samples:
            return {
                "cpu_percent": 0.0,
                "memory_mb": 0.0,
                "execution_time_sec": 0.0,
                "sample_count": 0
            }
        
        cpu_values = [s["cpu_percent"] for s in self.samples if "cpu_percent" in s]
        memory_values = [s["memory_mb"] for s in self.samples if "memory_mb" in s]
        
        avg_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 0.0
        max_memory = max(memory_values) if memory_values else 0.0
        
        execution_time = time.time() - self.start_time if self.start_time else 0.0
        
        return {
            "cpu_percent": round(avg_cpu, 2),
            "memory_mb": round(max_memory, 2),
            "execution_time_sec": round(execution_time, 2),
            "sample_count": len(self.samples)
        }


def calculate_resource_score(metrics: dict) -> int:
    """Calculate resource efficiency score based on metrics."""
    
    cpu = metrics.get("cpu_percent", 0)
    
    if cpu < 30:
        cpu_score = 100
    elif cpu < 60:
        cpu_score = 70
    else:
        cpu_score = 40
    
    return cpu_score


def calculate_offline_score(blocked_network_calls: int) -> int:
    """Calculate offline capability score."""
    
    if blocked_network_calls == 0:
        return 100
    elif blocked_network_calls <= 2:
        return 70
    else:
        return 0


def calculate_trigger_score(task_results: list[dict]) -> float:
    """Calculate trigger accuracy score."""
    
    if not task_results:
        return 0.0
    
    correct = sum(1 for r in task_results if r.get("correct_skill_used", False))
    return (correct / len(task_results)) * 100


def calculate_completion_score(task_evaluations: list[dict]) -> float:
    """Calculate overall completion score from task evaluations."""
    
    if not task_evaluations:
        return 0.0
    
    scores = [e.get("converted_score", 0) for e in task_evaluations]
    return sum(scores) / len(scores)


def calculate_overall_score(
    completion_score: float,
    trigger_score: float,
    offline_score: float,
    resource_score: float
) -> dict:
    """Calculate weighted overall score."""
    
    weights = {
        "completion": 0.40,
        "trigger": 0.30,
        "offline": 0.20,
        "resource": 0.10
    }
    
    overall = (
        completion_score * weights["completion"] +
        trigger_score * weights["trigger"] +
        offline_score * weights["offline"] +
        resource_score * weights["resource"]
    )
    
    return {
        "completion_score": round(completion_score, 1),
        "trigger_score": round(trigger_score, 1),
        "offline_score": offline_score,
        "resource_score": resource_score,
        "overall": round(overall, 1),
        "weights": weights
    }
