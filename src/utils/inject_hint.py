import re


def inject_hint(message: str, hint: str) -> str:
    """注入隐藏提示（用户不可见，LLM可见）"""
    return f"[HINT_MSG]{hint}[/HINT_MSG]\n\n{message}"


def filter_hints(content: str) -> str:
    """过滤掉所有注入的隐藏提示"""
    if not content:
        return content
    pattern = r'\[HINT_MSG\].*?\[/HINT_MSG\]\s*'
    return re.sub(pattern, '', content, flags=re.DOTALL)
