# Mem0 记忆系统 - 前端对接文档

> **版本**: v0.2.1  
> **更新日期**: 2026-03-04  
> **适用前端**: React/Vue/Angular 等

## 一、概述

### 1.1 变更说明

**本次架构变更**：
- Mem0 配置从环境变量改为数据库管理
- 新增 `role="embedding"` 的模型配置
- 支持前端动态切换 Embedding 模型
- 配置变更后自动重新初始化记忆系统

**影响范围**：
- LLM 配置管理界面（已有，需扩展）
- 无需新增独立界面
- Embedding 配置使用现有的 LLM 配置管理界面

### 1.2 前端需要做什么

✅ **无需新增页面**（复用现有LLM配置管理界面）  
✅ **需要支持 embedding 角色**（在角色筛选中添加）  
✅ **需要添加配置初始化提示**（首次部署时）  
✅ **需要添加 embedding_dims 字段**（extra_params 中）

---

## 二、LLM 配置管理界面

### 2.1 界面复用

**现有界面**：`/admin/llm-configs`（或类似路由）  
**复用策略**：在同一界面管理所有角色（big/flash/embedding）

**建议改进**：
- 添加角色筛选下拉框：`["all", "big", "flash", "embedding"]`
- 不同角色用不同颜色标签区分
- Embedding 配置的特殊字段提示

### 2.2 角色说明

| 角色 | 用途 | 必需字段 | 特殊字段 |
|------|------|----------|----------|
| **big** | 主模型（Agent推理、Mem0 LLM） | model_name, base_url, api_key | - |
| **flash** | 快速模型（快速响应） | model_name, base_url, api_key | - |
| **embedding** | Embedding模型（Mem0向量化） | model_name, base_url, api_key | **extra_params.embedding_dims** |

---

## 三、Embedding 配置管理

### 3.1 创建 Embedding 配置

**接口**：`POST /api/admin/llm/configs`

**请求示例**：

```json
{
  "name": "qwen3-embedding-0.6b",
  "display_name": "Qwen3 Embedding 0.6B",
  "description": "Embedding模型用于向量化文本",
  "provider": "openai",
  "base_url": "http://192.168.110.44:8008/v1",
  "api_key": "dummy-key",
  "model_name": "Qwen3-Embedding-0.6B",
  "role": "embedding",
  "temperature": 0,
  "max_tokens": 512,
  "extra_params": {
    "embedding_dims": 1024
  }
}
```

**前端表单设计建议**：

```
┌─────────────────────────────────────────────┐
│  创建 Embedding 配置                         │
├─────────────────────────────────────────────┤
│  配置名称: [qwen3-embedding-0.6b          ] │
│  显示名称: [Qwen3 Embedding 0.6B          ] │
│  描述:     [Embedding模型用于向量化文本    ] │
│                                             │
│  提供商:   [OpenAI                      ▼] │
│  API地址:  [http://192.168.110.44:8008/v1] │
│  API密钥:  [dummy-key                      ] │
│  模型名称: [Qwen3-Embedding-0.6B           ] │
│                                             │
│  角色:     [embedding                    ▼] │
│  温度:     [0                              ] │
│  最大Token: [512                           ] │
│                                             │
│  向量维度: [1024                          ] │
│  ℹ️ 用于Qdrant向量数据库配置                │
│                                             │
│  [  ] 创建后立即激活                         │
│                                             │
│        [取消]  [创建]                        │
└─────────────────────────────────────────────┘
```

**关键字段说明**：

- **role**: 必须为 `"embedding"`
- **temperature**: 通常为 `0`（Embedding不需要随机性）
- **max_tokens**: 通常为 `512`（短文本向量化）
- **extra_params.embedding_dims**: **必需**，向量维度（如 1024、768、1536）

### 3.2 查询 Embedding 配置列表

**接口**：`GET /api/admin/llm/configs?role=embedding`

**响应示例**：

```json
{
  "configs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "qwen3-embedding-0.6b",
      "display_name": "Qwen3 Embedding 0.6B",
      "description": "Embedding模型用于向量化文本",
      "provider": "openai",
      "base_url": "http://192.168.110.44:8008/v1",
      "model_name": "Qwen3-Embedding-0.6B",
      "temperature": 0,
      "max_tokens": 512,
      "extra_params": {
        "embedding_dims": 1024
      },
      "role": "embedding",
      "is_active": true,
      "created_at": "2026-03-04T10:00:00Z"
    }
  ]
}
```

### 3.3 激活 Embedding 配置

**接口**：`POST /api/admin/llm/configs/{config_id}/activate`

**请求示例**：

```bash
POST /api/admin/llm/configs/550e8400-e29b-41d4-a716-446655440000/activate
```

**响应示例**：

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "qwen3-embedding-0.6b",
  "role": "embedding",
  "is_active": true,
  "message": "Config activated"
}
```

**前端提示**：

```
⚠️ 切换 Embedding 配置后，记忆系统将自动重新初始化。
   新配置将立即生效，已保存的记忆数据不会丢失。
   
   [确认切换]  [取消]
```

---

## 四、配置初始化流程

### 4.1 首次部署检查

**前端建议逻辑**：

```javascript
// 检查是否存在 embedding 配置
async function checkEmbeddingConfig() {
  const response = await fetch('/api/admin/llm/configs?role=embedding');
  const data = await response.json();
  
  if (data.configs.length === 0) {
    // 显示初始化引导
    showEmbeddingConfigGuide();
  }
}
```

### 4.2 初始化引导界面

```
┌─────────────────────────────────────────────┐
│  ⚠️ 检测到未配置 Embedding 模型              │
├─────────────────────────────────────────────┤
│                                             │
│  Mem0 记忆系统需要 Embedding 模型来进行      │
│  向量化处理。请先创建一个 Embedding 配置。   │
│                                             │
│  推荐配置:                                   │
│  • 模型: Qwen3-Embedding-0.6B               │
│  • 维度: 1024                               │
│  • 地址: http://192.168.110.44:8008/v1     │
│                                             │
│  [使用推荐配置创建]  [手动配置]              │
│                                             │
└─────────────────────────────────────────────┘
```

**一键创建推荐配置**：

```javascript
async function createDefaultEmbeddingConfig() {
  const config = {
    name: "qwen3-embedding-0.6b",
    display_name: "Qwen3 Embedding 0.6B",
    description: "Embedding模型用于向量化文本",
    provider: "openai",
    base_url: "http://192.168.110.44:8008/v1",
    api_key: "dummy-key",
    model_name: "Qwen3-Embedding-0.6B",
    role: "embedding",
    temperature: 0,
    max_tokens: 512,
    extra_params: {
      embedding_dims: 1024
    }
  };
  
  const response = await fetch('/api/admin/llm/configs', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(config)
  });
  
  if (response.ok) {
    const data = await response.json();
    // 自动激活
    await fetch(`/api/admin/llm/configs/${data.id}/activate`, {method: 'POST'});
    alert('Embedding 配置创建并激活成功！');
  }
}
```

---

## 五、配置切换注意事项

### 5.1 Embedding 维度兼容性

**重要**：不同 Embedding 模型的维度可能不同

| 模型 | 维度 | 说明 |
|------|------|------|
| Qwen3-Embedding-0.6B | 1024 | 推荐使用 |
| text-embedding-3-small | 1536 | OpenAI |
| text-embedding-ada-002 | 1536 | OpenAI |

**前端警告**：

```
⚠️ 警告：切换到不同维度的 Embedding 模型后，
   新保存的记忆将使用新维度，可能与旧记忆不兼容。
   
   建议：
   • 清空旧记忆数据
   • 或使用相同维度的模型
   
   [我已了解，继续切换]  [取消]
```

### 5.2 配置切换流程

**推荐的前端交互**：

1. 用户点击"激活"按钮
2. 显示确认对话框（说明影响）
3. 用户确认后调用激活接口
4. 显示"重新初始化中..."加载提示
5. 接口返回后显示成功消息
6. 提示用户"新配置已生效"

---

## 六、测试验证

### 6.1 前端测试清单

- [ ] 创建 embedding 配置
- [ ] 查看 embedding 配置列表
- [ ] 编辑 embedding 配置
- [ ] 激活 embedding 配置（触发重初始化）
- [ ] 删除 embedding 配置
- [ ] 切换不同维度的 embedding 配置
- [ ] 首次部署时的初始化引导

### 6.2 后端验证接口

**测试记忆功能**：

```bash
# 1. 激活 embedding 配置
POST /api/admin/llm/configs/{config_id}/activate

# 2. 测试保存记忆
POST /api/agent/chat
{
  "thread_id": "test-thread-001",
  "message": "我喜欢使用 Python 编程"
}

# 3. 测试检索记忆
POST /api/agent/chat
{
  "thread_id": "test-thread-001",
  "message": "我的编程语言偏好是什么？"
}

# 期望响应：Agent 应该能检索到之前保存的偏好
```

---

## 七、常见问题

### Q1: 切换 Embedding 配置后，旧记忆会丢失吗？

**A**: 不会。已保存的记忆向量数据存储在 Qdrant 中，配置切换不会删除数据。但不同维度的向量可能不兼容。

### Q2: 如果数据库中没有 embedding 配置会怎样？

**A**: MemoryManager 会自动 fallback 到环境变量配置。但建议始终在数据库中配置。

### Q3: 如何查看当前使用的 Embedding 配置？

**A**: 调用 `GET /api/admin/llm/configs?role=embedding`，查看 `is_active=true` 的配置。

### Q4: extra_params 中还可以添加哪些字段？

**A**: 其他自定义参数，如：
- `batch_size`: 批处理大小
- `normalize`: 是否归一化向量
- 其他模型特定参数

### Q5: 是否需要重启服务才能生效？

**A**: 不需要。激活配置后，后端会自动重新初始化 MemoryManager，立即生效。

---

## 八、API 接口汇总

### 8.1 创建配置

```
POST /api/admin/llm/configs
Content-Type: application/json

{
  "name": "qwen3-embedding-0.6b",
  "display_name": "Qwen3 Embedding 0.6B",
  "description": "Embedding模型",
  "provider": "openai",
  "base_url": "http://192.168.110.44:8008/v1",
  "api_key": "dummy-key",
  "model_name": "Qwen3-Embedding-0.6B",
  "role": "embedding",
  "temperature": 0,
  "max_tokens": 512,
  "extra_params": {
    "embedding_dims": 1024
  }
}
```

### 8.2 查询配置列表

```
GET /api/admin/llm/configs?role=embedding
```

### 8.3 查询单个配置

```
GET /api/admin/llm/configs/{config_id}
```

### 8.4 更新配置

```
PUT /api/admin/llm/configs/{config_id}
Content-Type: application/json

{
  "display_name": "Qwen3 Embedding 0.6B (Updated)",
  "base_url": "http://new-url:8008/v1",
  "extra_params": {
    "embedding_dims": 1536
  }
}
```

### 8.5 激活配置

```
POST /api/admin/llm/configs/{config_id}/activate
```

### 8.6 删除配置

```
DELETE /api/admin/llm/configs/{config_id}
```

### 8.7 测试连接

```
POST /api/admin/llm/test-connection
Content-Type: application/json

{
  "base_url": "http://192.168.110.44:8008/v1",
  "api_key": "dummy-key",
  "model_name": "Qwen3-Embedding-0.6B"
}
```

---

## 九、代码示例

### 9.1 React 示例

```jsx
import React, { useState, useEffect } from 'react';

function EmbeddingConfigManager() {
  const [configs, setConfigs] = useState([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  
  useEffect(() => {
    loadConfigs();
  }, []);
  
  const loadConfigs = async () => {
    const response = await fetch('/api/admin/llm/configs?role=embedding');
    const data = await response.json();
    setConfigs(data.configs);
  };
  
  const activateConfig = async (configId) => {
    if (!confirm('切换 Embedding 配置后，记忆系统将重新初始化。确认继续？')) {
      return;
    }
    
    const response = await fetch(`/api/admin/llm/configs/${configId}/activate`, {
      method: 'POST'
    });
    
    if (response.ok) {
      alert('配置已激活，记忆系统已重新初始化');
      loadConfigs();
    }
  };
  
  return (
    <div>
      <h2>Embedding 配置管理</h2>
      
      {configs.length === 0 && (
        <div className="alert alert-warning">
          ⚠️ 未检测到 Embedding 配置，请先创建。
          <button onClick={() => setShowCreateModal(true)}>
            创建配置
          </button>
        </div>
      )}
      
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>模型</th>
            <th>维度</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {configs.map(config => (
            <tr key={config.id}>
              <td>{config.display_name}</td>
              <td>{config.model_name}</td>
              <td>{config.extra_params?.embedding_dims || '-'}</td>
              <td>
                {config.is_active ? 
                  <span className="badge badge-success">激活</span> : 
                  <span className="badge badge-secondary">未激活</span>
                }
              </td>
              <td>
                {!config.is_active && (
                  <button onClick={() => activateConfig(config.id)}>
                    激活
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      
      <button onClick={() => setShowCreateModal(true)}>
        创建新配置
      </button>
      
      {showCreateModal && (
        <CreateEmbeddingConfigModal 
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => {
            setShowCreateModal(false);
            loadConfigs();
          }}
        />
      )}
    </div>
  );
}
```

### 9.2 Vue 3 示例

```vue
<template>
  <div>
    <h2>Embedding 配置管理</h2>
    
    <div v-if="configs.length === 0" class="alert alert-warning">
      ⚠️ 未检测到 Embedding 配置，请先创建。
      <button @click="showCreateModal = true">创建配置</button>
    </div>
    
    <table>
      <thead>
        <tr>
          <th>名称</th>
          <th>模型</th>
          <th>维度</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="config in configs" :key="config.id">
          <td>{{ config.display_name }}</td>
          <td>{{ config.model_name }}</td>
          <td>{{ config.extra_params?.embedding_dims || '-' }}</td>
          <td>
            <span :class="config.is_active ? 'badge-success' : 'badge-secondary'">
              {{ config.is_active ? '激活' : '未激活' }}
            </span>
          </td>
          <td>
            <button 
              v-if="!config.is_active" 
              @click="activateConfig(config.id)"
            >
              激活
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    
    <button @click="showCreateModal = true">创建新配置</button>
    
    <CreateEmbeddingConfigModal 
      v-if="showCreateModal"
      @close="showCreateModal = false"
      @success="handleCreateSuccess"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';

const configs = ref([]);
const showCreateModal = ref(false);

const loadConfigs = async () => {
  const response = await fetch('/api/admin/llm/configs?role=embedding');
  const data = await response.json();
  configs.value = data.configs;
};

const activateConfig = async (configId) => {
  if (!confirm('切换 Embedding 配置后，记忆系统将重新初始化。确认继续？')) {
    return;
  }
  
  const response = await fetch(`/api/admin/llm/configs/${configId}/activate`, {
    method: 'POST'
  });
  
  if (response.ok) {
    alert('配置已激活，记忆系统已重新初始化');
    loadConfigs();
  }
};

const handleCreateSuccess = () => {
  showCreateModal.value = false;
  loadConfigs();
};

onMounted(() => {
  loadConfigs();
});
</script>
```

---

## 十、总结

### 前端工作清单

- [x] 复用现有 LLM 配置管理界面
- [ ] 添加角色筛选（支持 embedding）
- [ ] 添加 embedding_dims 字段输入
- [ ] 添加首次部署引导提示
- [ ] 添加配置切换确认对话框
- [ ] 添加维度兼容性警告
- [ ] 测试配置 CRUD 功能
- [ ] 测试配置激活功能

### 关键点

1. **无需新增页面**：完全复用现有界面
2. **角色区分**：通过 `role="embedding"` 标识
3. **必需字段**：`extra_params.embedding_dims`
4. **热更新**：激活配置后自动重初始化
5. **维度兼容**：切换不同维度模型时警告用户

---

**文档版本**: v1.0  
**最后更新**: 2026-03-04  
**维护者**: Backend Team
