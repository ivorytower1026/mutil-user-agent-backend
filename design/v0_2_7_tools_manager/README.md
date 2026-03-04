# v0.2.7 工具管理器 - 图片分析工具

## 背景

后台需要一个工具管理库，用于给子代理和主代理提供默认工具。首个工具是图片分析工具 `analyze_image`，支持：
- 沙箱路径（自动转换为宿主机路径）
- URL
- Data URI

## 需求分析

### 核心功能
1. **图片分析工具**：根据提供的路径和 prompt 识别图片内容
2. **路径转换**：沙箱路径 `/workspace/xxx` → 宿主机路径 `workspaces/{user_id}/xxx`
3. **多源支持**：URL、Data URI、本地文件

### 技术选型
- **LLM**：使用 `flash_llm`（支持视觉模型，可通过配置管理器动态切换）
- **工具加载位置**：主代理 + 子代理
- **路径支持范围**：仅 `/workspace`（用户工作目录）

## 架构设计

### 文件结构
```
src/
├── tools_manager.py    # 新增：工具管理器（单例）
├── agent_manager.py    # 修改：集成工具管理器
└── ...
```

### 类设计

```python
# src/tools_manager.py

class ToolsManager:
    """工具管理器单例"""
    
    _instance: "ToolsManager | None" = None
    _flash_llm: ChatOpenAI | None = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def init(self, db: Session):
        """初始化，获取 flash_llm 实例"""
        self._flash_llm = get_llm_manager().get_flash_llm(db)
    
    def create_tools(self) -> list[BaseTool]:
        """创建所有工具列表"""
        return [self._create_analyze_image_tool()]
    
    def _create_analyze_image_tool(self) -> BaseTool:
        """创建图片分析工具"""
        ...
```

### 路径转换逻辑

```python
# 沙箱路径 -> 宿主机路径
def _sandbox_to_host_path(sandbox_path: str, user_id: str) -> str:
    """
    /workspace/images/test.png 
    -> workspaces/{user_id}/images/test.png
    """
    if sandbox_path.startswith("/workspace/"):
        relative = sandbox_path[len("/workspace/"):]
        return os.path.join(settings.WORKSPACE_ROOT, user_id, relative)
    raise ValueError(f"不支持的沙箱路径: {sandbox_path}")
```

### 工具函数签名

```python
def analyze_image(
    image_source: Annotated[str, "图片路径或URL，支持沙箱路径(/workspace/...)、URL、Data URI"],
    prompt: Annotated[str, "分析提示词，描述你想要了解的图片内容"],
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    分析图片内容并返回结果。
    
    支持的输入格式：
    - 沙箱路径: /workspace/images/test.png
    - URL: https://example.com/image.png
    - Data URI: data:image/png;base64,iVBORw0KGgo...
    """
    ...
```

## 改动清单

### 1. 新建文件

**src/tools_manager.py**
- 单例类 `ToolsManager`
- `analyze_image` 工具实现
- 路径转换辅助函数
- URL/Data URI 解析函数

### 2. 修改文件

**src/agent_manager.py**

```python
# 导入
from src.tools_manager import get_tools_manager

# __init__ 中添加
self.tools_manager = get_tools_manager()

# init() 中添加
self.tools_manager.init(db)

# _build_agent() 中修改
# 原: all_tools = mcp_tools + memory_tools
# 改: all_tools = mcp_tools + memory_tools + self.tools_manager.create_tools()

# _build_subagents() 中修改
# 为每个子代理添加默认工具
tools = self.tools_manager.create_tools()  # 默认工具
for server_name in config.mcp_servers or []:
    server_tools = await self.mcp_manager.get_all_tools(server_name)
    tools.extend(server_tools)
```

## API 设计

### 工具描述

```
名称: analyze_image
描述: 分析图片内容。支持沙箱路径、URL、Data URI 三种输入格式。
参数:
  - image_source: 图片路径或URL
  - prompt: 分析提示词
```

### 使用示例

```
# 沙箱路径
analyze_image("/workspace/screenshots/error.png", "这个错误信息是什么？")

# URL
analyze_image("https://example.com/diagram.png", "解释这个架构图")

# Data URI（通常由其他工具生成）
analyze_image("data:image/png;base64,...", "描述这张图片的内容")
```

## 测试计划

### 单元测试
1. `_is_url()` - URL 识别
2. `_is_data_uri()` - Data URI 识别
3. `_sandbox_to_host_path()` - 路径转换
4. `_read_local_file()` - 文件读取

### 集成测试
1. 通过主代理调用 `analyze_image` 分析沙箱图片
2. 通过子代理调用 `analyze_image` 分析 URL 图片
3. 测试不存在的路径错误处理
4. 测试非图片文件的错误处理

## 实现步骤

1. [ ] 创建 `src/tools_manager.py`
2. [ ] 实现 `ToolsManager` 单例类
3. [ ] 实现 `analyze_image` 工具
4. [ ] 修改 `src/agent_manager.py` 集成工具管理器
5. [ ] 编写测试用例
6. [ ] 更新 AGENTS.md

## 风险与注意事项

1. **图片大小限制**：大图片可能导致 LLM 调用超时或超出 token 限制
2. **路径安全**：确保路径转换不会导致目录遍历攻击
3. **并发安全**：单例模式下的 LLM 实例共享
