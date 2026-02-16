# v0.1.9 - Agent 问答工具 (ask_user)

## 功能概述

为 Agent 添加 `ask_user` 工具，允许 Agent 在执行过程中向用户提问，用户回答后 Agent 继续执行。

## 背景

当前系统只有 `execute` 和 `write_file` 两个工具会触发中断，需要人工确认。但在很多场景下，Agent 需要主动向用户询问信息，例如：

1. 询问用户偏好（颜色、风格等）
2. 让用户选择执行方式（立即执行、稍后执行等）
3. 确认模糊的指令（"删除文件" - 哪个文件？）

## 功能特性

### 1. 多问题支持

Agent 可以一次性提出多个问题，用户需要全部回答后才能继续：

```
问题1: 你喜欢什么颜色？
  A、红色  B、绿色  C、蓝色  D、【自定义】

问题2: 你喜欢什么动物？
  A、狗  B、猫  C、【自定义】

问题3: 怎么执行？
  A、立即执行  B、审视后执行  C、【自定义】
```

### 2. 选项支持

每个问题支持多个选项，选项可以是：
- 固定值选项（如 "红色"、"绿色"）
- 自定义输入选项（允许用户输入自己的答案）

### 3. 中断优化

同时优化现有中断的显示效果：

| 工具 | 改进前 | 改进后 |
|------|--------|--------|
| execute | `info: "Executes a shell command..."` | `info: "正在执行命令: npm install"` |
| write_file | `info: "Writes to a new file..."` | `info: "正在写入文件: test.py"` |
| ask_user | 无 | `info: "Agent 提出了 3 个问题"` |

## 技术方案

### 后端

1. 新增 `ask_user` 工具，使用 `StructuredTool` 定义
2. 在 `interrupt_on` 中配置 `ask_user` 使用 `edit` 决策类型
3. 修改 `stream_resume_interrupt` 支持传递用户答案
4. 添加辅助方法优化中断信息显示

### 前端

1. 新增 `Question` 和 `QuestionOption` 类型
2. 修改 `InterruptDetail.vue` 支持渲染问答表单
3. 修改 `ChatInput.vue` 处理问答确认逻辑
4. 修改 `useChatStream.ts` 支持传递答案数组

## 文件清单

| 文件 | 修改内容 |
|------|----------|
| `src/agent_manager.py` | 新增工具、修改中断配置、优化显示 |
| `api/models.py` | `ResumeRequest` 新增 `answers` 字段 |
| `api/server.py` | `/resume` 端点支持 `answers` 参数 |
| `src/types/chat.ts` | 新增 `Question`、`QuestionOption` 类型 |
| `src/types/api.ts` | `ResumeRequest` 新增 `answers` 字段 |
| `src/components/interrupt/InterruptDetail.vue` | 支持问答表单渲染 |
| `src/components/chat/ChatInput.vue` | 处理问答确认逻辑 |
| `src/composables/useChatStream.ts` | 支持传递答案数组 |
| `src/api/sse.ts` | `streamResume` 支持 `answers` 参数 |

## 数据流

```
1. Agent 调用 ask_user(questions=[...])
   ↓
2. 触发中断，SSE 返回 interrupt 事件
   ↓
3. 前端渲染问答表单
   ↓
4. 用户选择答案
   ↓
5. 前端 POST /api/resume {action: "answer", answers: [...]}
   ↓
6. 后端使用 edit 决策注入答案
   ↓
7. 工具返回答案，Agent 继续执行
```

## 版本信息

- **版本号**: v0.1.9
- **依赖版本**: v0.1.8
- **预计工时**: 4-6 小时
