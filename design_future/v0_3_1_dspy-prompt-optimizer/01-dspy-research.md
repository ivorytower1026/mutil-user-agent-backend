# DSPy 框架研究与优化器对比

> **版本**: v0.3.1  
> **更新日期**: 2026-03-04

## 1. DSPy 是什么

**DSPy (Declarative Self-improving Python)** 是斯坦福 NLP 团队开发的声明式 LLM 编程框架。

### 核心理念

**用代码代替 prompt 字符串**来构建 AI 应用，而不是手工调优 prompt。

```
传统方式                          DSPy 方式
────────                          ─────────
手写 prompt 字符串                定义 Signature (输入/输出)
    ↓                                 ↓
手动调整措辞                      选择 Module (Predict/CoT/ReAct)
    ↓                                 ↓
试错式优化                        运行 Optimizer 自动优化
    ↓                                 ↓
脆弱、难维护                      模块化、可测试、可优化
```

### 核心组件

| 组件 | 作用 | 示例 |
|------|------|------|
| **Signature** | 声明式定义输入输出 | `question -> answer: float` |
| **Module** | 可组合的处理单元 | `Predict`, `ChainOfThought`, `ReAct` |
| **Optimizer** | 自动优化 prompt 和权重 | `BootstrapFewShot`, `MIPROv2`, `GEPA` |

---

## 2. DSPy 优化器对比

### 2.1 BootstrapFewShot（推荐）

```python
optimizer = BootstrapFewShot(
    metric=your_metric,
    max_bootstrapped_demos=4,   # 自动生成的示例数
    max_labeled_demos=16,       # 标注示例数
    max_rounds=1,               # 迭代轮数
)
optimized = optimizer.compile(student=program, trainset=data)
```

**工作原理**：
```
┌─────────────────────────────────────────────────────┐
│              BootstrapFewShot 流程                   │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. Teacher Model 运行程序                           │
│     └─▶ 使用 temperature=1.0 生成多样化输出          │
│                                                     │
│  2. 收集成功轨迹 (trace)                             │
│     └─▶ 根据metric筛选成功的执行路径                 │
│                                                     │
│  3. 提取 few-shot 示例 (demos)                       │
│     └─▶ 从成功轨迹中提取输入/输出对                  │
│                                                     │
│  4. 注入到 Student Model                            │
│     └─▶ 将 demos 添加到 predictor.demos             │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**适用场景**：
- ✅ 为现有 prompt 添加高质量示例
- ✅ 快速迭代，成本低
- ✅ 适合日常优化

**成本/时间**：
- 成本：~$0.1-1
- 时间：几分钟

---

### 2.2 MIPROv2（指令优化）

```python
optimizer = MIPROv2(
    metric=your_metric,
    auto="light",  # light/medium/heavy
    num_threads=4,
)
optimized = optimizer.compile(
    student=program,
    trainset=train_data,
    valset=val_data,
)
```

**工作原理**：
```
┌─────────────────────────────────────────────────────┐
│               MIPROv2 三阶段优化                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Stage 1: Bootstrap Few-Shot Examples               │
│     └─▶ 收集成功轨迹作为示例候选                     │
│                                                     │
│  Stage 2: Propose Instruction Candidates            │
│     └─▶ 分析程序代码 + 数据 + 示例                   │
│     └─▶ 使用 LLM 生成多个指令候选                    │
│                                                     │
│  Stage 3: Bayesian Optimization                     │
│     └─▶ 使用 Optuna 搜索最优指令+示例组合            │
│     └─▶ Minibatch 评估加速                          │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**适用场景**：
- ✅ 自动生成和优化指令文本
- ✅ 重大版本更新时使用
- ✅ 需要系统性优化

**成本/时间**：
- 成本：~$2-10
- 时间：20-60 分钟

---

### 2.3 GEPA（反思性优化）

```python
def feedback_metric(gold, pred, trace, pred_name, pred_trace):
    score = compute_score(gold, pred)
    feedback = generate_feedback(pred_name, pred_trace)
    return {"score": score, "feedback": feedback}

optimizer = GEPA(
    metric=feedback_metric,
    auto="medium",
    reflection_lm=dspy.LM("openai/gpt-4o", temperature=1.0),
)
optimized = optimizer.compile(student=program, trainset=data)
```

**工作原理**：
```
┌─────────────────────────────────────────────────────┐
│               GEPA 进化式优化                        │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. 运行程序，收集失败案例                           │
│     └─▶ 识别低分或错误的执行                         │
│                                                     │
│  2. 反思分析 (Reflection)                           │
│     └─▶ 分析失败原因                                │
│     └─▶ 生成改进反馈                                │
│                                                     │
│  3. 进化指令 (Evolution)                            │
│     └─▶ 基于反馈生成新的指令变体                     │
│                                                     │
│  4. Pareto 优化选择                                 │
│     └─▶ 保留多维度最优的候选                        │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**适用场景**：
- ✅ 复杂系统，需要细粒度反馈
- ✅ 多模块 Agent 系统调优
- ✅ 需要 predictor 级别的优化

**成本/时间**：
- 成本：~$5-20
- 时间：30-120 分钟

---

### 2.4 BetterTogether（协同优化）

```python
optimizer = BetterTogether(
    metric=your_metric,
    prompt_optimizer=BootstrapFewShotWithRandomSearch(...),
    weight_optimizer=BootstrapFinetune(...),
)
optimized = optimizer.compile(
    student=program,
    trainset=data,
    strategy="p -> w -> p",  # prompt → weight → prompt
)
```

**适用场景**：
- ✅ 同时优化 prompt 和微调模型
- ❌ 需要微调资源，成本高

**成本/时间**：
- 成本：很高
- 时间：数小时

---

## 3. 优化器选择建议

| 场景 | 推荐优化器 | 理由 |
|------|-----------|------|
| **日常优化** | BootstrapFewShot | 成本低，速度快，效果稳定 |
| **版本更新** | MIPROv2 | 系统性优化指令 |
| **复杂系统** | GEPA | 细粒度反馈优化 |
| **生产部署** | BetterTogether | prompt + 权重双优化 |

### 针对本项目的选择

```
┌─────────────────────────────────────────────────────┐
│          Multi-tenant Agent Platform                │
│              优化器选择策略                          │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Phase 1 (当前): BootstrapFewShot                   │
│  ─────────────────────────────────                  │
│  • 为 agent system_prompt 添加 few-shot 示例        │
│  • 从历史成功对话提取训练数据                        │
│  • 低成本快速迭代                                   │
│                                                     │
│  Phase 2 (未来): MIPROv2                            │
│  ─────────────────────────────────                  │
│  • 自动生成优化后的指令文本                          │
│  • 重大版本更新时使用                               │
│                                                     │
│  Phase 3 (可选): GEPA                               │
│  ─────────────────────────────────                  │
│  • 复杂 subagent 系统调优                           │
│  • 需要 predictor 级别优化时使用                    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 4. DSPy 与 LangGraph/DeepAgents 的关系

### 架构对比

```
┌─────────────────────────────────────────────────────┐
│                    DSPy                             │
│  ─────────────────────────────────────              │
│  • 声明式定义 (Signature)                           │
│  • 自动优化 (Optimizer)                             │
│  • 适合：单任务优化、prompt 生成                    │
└─────────────────────────────────────────────────────┘
                      │
                      │ 可集成
                      ▼
┌─────────────────────────────────────────────────────┐
│              LangGraph + DeepAgents                 │
│  ─────────────────────────────────────              │
│  • 状态管理 (State)                                 │
│  • 工具调用 (Tools)                                 │
│  • 人机交互 (HITL)                                  │
│  • 适合：复杂 Agent 编排                           │
└─────────────────────────────────────────────────────┘
```

### 集成方式

```
DSPy 优化后的 Prompt
        │
        ▼
┌───────────────────────┐
│  AgentConfig.system_prompt  │
│  + few-shot demos           │
└───────────────────────┘
        │
        ▼
┌───────────────────────┐
│  LangGraph Agent      │
│  (DeepAgents)         │
└───────────────────────┘
```

**结论**：DSPy 和 LangGraph/DeepAgents 是互补关系，不是替代关系。

---

## 5. 参考资料

- [DSPy 官方文档](https://dspy.ai/)
- [DSPy GitHub](https://github.com/stanfordnlp/dspy)
- [DSPy 论文](https://arxiv.org/abs/2310.03714)
- [MIPROv2 论文](https://arxiv.org/abs/2406.11695)
- [GEPA 论文](https://arxiv.org/abs/2507.19457)
