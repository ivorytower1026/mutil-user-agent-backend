# 需求描述

因为用户需要的是开箱即用的agent，而不是复杂的ai coding配置，所以需要做一些封装，以及简化配置的功能；

另一方面，因为agent的执行是不受控的，为了防止对宿主机造成污染，因此需要将用户工作目录映射到沙箱中，各种命令执行也在沙箱中执行。



# 架构图

顶层架构图

![image-20260210105302827](../assets/image-20260210105302827.png)

```cmd
Host
 ├─ deepagents（调度层）
 │   ├─ userA-thread-1 ─┐
 │   ├─ userA-thread-2 ─┼──► sandbox1 (container)
 │   └─ userB-thread-3 ─┘
 │
 └─ Docker
     ├─ sandbox1
     │   ├─ /workspace (rw, userA)
     │   └─ /shared (ro)
     └─ sandbox2
         ├─ /workspace (rw, userB)
         └─ /shared (ro)

```



# 技术架构

前端：

npm、vue、ts、Vuetify

后端：

uv、python、fastapi、langgraph、deepagents

部署：

docker、postgres

通信协议：

sse



# 用户隔离方案

1、用户线程隔离，利用langgraph的线程id来进行隔离，不同用户只能有自己的线程

2、环境隔离，agent操作的环境都在docker容器中，避免污染宿主机环境



# 用户交互

用户通过web页面的对话框【类似chatgpt的对话界面】与后台agent进行交互，发起任务/人工审核/开启新对话

创建一个新用户后就会给用户创建一个工作空间，映射到当前宿主机的某个目录上，每个用户的目录都不冲突，并挂载到docker上

why？

因为这种方式学习和使用成本都是最低的，基于对话模型，利用对话功能



# 需要探讨的问题

1、多用户怎么使用langgraph的能力thread_id来区分

使用{user_id}-{uuid}来区分不同的线程

2、deepagents中的SandboxBackendProtocol和docker如何构建沙箱环境【如何做到不影响宿主机】

使用docker命令启动容器，每个用户都是不同的容器，然后都将工作空间挂载到宿主机的某个位置上

3、多轮hitl怎么实现？

先只支持interrupt敏感操作，如修改文件/执行shell命令，后续支持自定义

4、agent的用途是什么？

agent的用途是通用Agent，支持在断网环境下【内网】，也能很好的完成任务，主要依赖这个agent的实现+agent skills【当下最火】的配合

5、资源问题？







