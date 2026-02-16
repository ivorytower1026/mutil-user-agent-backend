# v0.1.9 API 设计

## 一、新增/修改的 API

### 1.1 POST /api/resume/{thread_id}

修改 resume 端点以支持传递用户答案。

#### 请求体

```typescript
interface ResumeRequest {
  action: "continue" | "cancel" | "answer"
  answers?: string[]  // 当 action="answer" 时必需
}
```

#### 行为说明

| action | 描述 | answers |
|--------|------|---------|
| `continue` | 批准当前操作继续执行 | 不需要 |
| `cancel` | 取消当前操作 | 不需要 |
| `answer` | 回答 ask_user 工具的问题 | **必需**，与问题数量一致 |

#### 响应

SSE 流式响应，事件类型：

| 事件 | 描述 |
|------|------|
| `messages/partial` | LLM 输出内容 |
| `tool/start` | 工具开始执行 |
| `tool/end` | 工具执行结束 |
| `interrupt` | 再次触发中断（如果有） |
| `error` | 错误信息 |
| `end` | 流结束 |

#### 错误响应

| 状态码 | 描述 |
|--------|------|
| 400 | action 不是有效值 |
| 400 | action="answer" 但没有 answers |
| 401 | 未授权 |
| 403 | 无权访问该 thread |

---

### 1.2 interrupt 事件数据结构

SSE interrupt 事件新增 `questions` 字段。

#### 原结构

```json
{
  "event": "interrupt",
  "data": {
    "info": "Tool execution requires approval...",
    "taskName": "execute",
    "data": { ... }
  }
}
```

#### 新结构

```json
{
  "event": "interrupt",
  "data": {
    "info": "正在执行命令: npm install",
    "taskName": "执行命令",
    "data": { ... },
    "questions": null  // 普通 interrupt
  }
}
```

```json
{
  "event": "interrupt",
  "data": {
    "info": "Agent 提出了 3 个问题",
    "taskName": "用户问答",
    "data": { ... },
    "questions": [
      {
        "question": "你喜欢什么颜色?",
        "options": [
          {"label": "红色", "value": "red"},
          {"label": "绿色", "value": "green"},
          {"label": "蓝色", "value": "blue"},
          {"label": "自定义", "value": "__custom__", "allow_custom": true}
        ]
      },
      {
        "question": "你喜欢什么动物?",
        "options": [
          {"label": "狗", "value": "dog"},
          {"label": "猫", "value": "cat"},
          {"label": "自定义", "value": "__custom__", "allow_custom": true}
        ]
      },
      {
        "question": "怎么执行?",
        "options": [
          {"label": "立即执行", "value": "now"},
          {"label": "审视后执行", "value": "review"},
          {"label": "自定义", "value": "__custom__", "allow_custom": true}
        ]
      }
    ]
  }
}
```

---

## 二、数据类型定义

### 2.1 Question

```typescript
interface Question {
  question: string           // 问题文本
  options: QuestionOption[]  // 选项列表
}
```

### 2.2 QuestionOption

```typescript
interface QuestionOption {
  label: string              // 显示文本
  value: string              // 选项值
  allow_custom?: boolean     // 是否允许自定义输入（默认 false）
}
```

### 2.3 Interrupt（修改后）

```typescript
interface Interrupt {
  taskName: string
  info: string
  data?: Record<string, unknown>
  options?: InterruptOption[]   // 普通中断的选项
  questions?: Question[]        // 问答工具的问题（新增）
}
```

### 2.4 ResumeRequest（修改后）

```typescript
interface ResumeRequest {
  action: "continue" | "cancel" | "answer"
  answers?: string[]
}
```

---

## 三、工具使用示例

### 3.1 Agent 调用 ask_user

```python
# Agent 在执行过程中调用
ask_user(
    questions=[
        {
            "question": "你喜欢什么颜色?",
            "options": [
                {"label": "红色", "value": "red"},
                {"label": "绿色", "value": "green"},
                {"label": "蓝色", "value": "blue"},
                {"label": "自定义", "value": "__custom__", "allow_custom": True}
            ]
        },
        {
            "question": "怎么执行?",
            "options": [
                {"label": "立即执行", "value": "now"},
                {"label": "审视后执行", "value": "review"}
            ]
        }
    ]
)
```

### 3.2 前端处理流程

```typescript
// 1. 监听 SSE 事件
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data)
  
  if (data.event === 'interrupt') {
    if (data.questions?.length) {
      // 问答类型，显示问答表单
      showQuestionForm(data.questions)
    } else {
      // 普通中断，显示确认选项
      showConfirmDialog(data)
    }
  }
}

// 2. 用户回答后提交
async function submitAnswers(answers: string[]) {
  const response = await fetch(`/api/resume/${threadId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      action: 'answer',
      answers: answers
    })
  })
  
  // 处理流式响应...
}
```

---

## 四、错误处理

### 4.1 答案数量不匹配

```json
{
  "event": "error",
  "data": {
    "message": "answers count (2) does not match questions count (3)"
  }
}
```

### 4.2 空答案

```json
{
  "event": "error", 
  "data": {
    "message": "answer at index 1 is empty"
  }
}
```

---

## 五、兼容性

### 5.1 向后兼容

- 普通 interrupt（execute, write_file）的处理逻辑不变
- 前端如果未实现问答功能，可以忽略 `questions` 字段
- `action` 仍然支持 `continue` 和 `cancel`

### 5.2 版本检查

前端可以通过检查 `questions` 字段是否存在来判断是否是问答类型：

```typescript
function isAskUserInterrupt(data: InterruptData): boolean {
  return Array.isArray(data.questions) && data.questions.length > 0
}
```
