# Daytona 重构实施检查清单

## Phase 1: 基础设施准备

- [ ] 部署 Daytona Server
  ```bash
  docker-compose -f docker-compose.daytona.yaml up -d
  ```
- [ ] 验证 Daytona Server 运行
  ```bash
  curl http://localhost:3986/health
  ```
- [ ] 验证 MinIO 访问
  ```
  http://localhost:9001
  用户名: minioadmin
  密码: minioadmin
  ```
- [ ] 更新依赖 `pyproject.toml`
  - [ ] 移除 `docker>=7.1.0`
  - [ ] 添加 `daytona-sdk>=0.10.0`
- [ ] 运行 `uv sync`
- [ ] 更新 `src/config.py`
  - [ ] 添加 DAYTONA_API_KEY
  - [ ] 添加 DAYTONA_API_URL
  - [ ] 添加 DAYTONA_TARGET
  - [ ] 添加 DAYTONA_AUTO_STOP_INTERVAL (15 min)
  - [ ] 添加 DAYTONA_AUTO_DELETE_INTERVAL (120 min)
  - [ ] 添加 DAYTONA_FILES_SANDBOX_AUTO_STOP (60 min)
  - [ ] 添加 DAYTONA_VOLUME_SIZE_GB
  - [ ] 添加 DAYTONA_BASE_SNAPSHOT
- [ ] 更新 `.env` 文件

## Phase 2: 数据库模型

- [ ] 更新 `src/database.py`
  - [ ] 添加 Volume 模型
  - [ ] 添加 Sandbox 模型（包含 sandbox_type 字段）
  - [ ] 添加 Snapshot 模型
  - [ ] Skill 模型添加 snapshot_id 字段
- [ ] 启动应用自动创建表

## Phase 3: Daytona 集成层

- [ ] 创建 `src/daytona_client.py`
  - [ ] 实现单例模式
  - [ ] 初始化 Daytona SDK 客户端
- [ ] 创建 `src/daytona_sandbox.py`
  - [ ] 实现 execute()
  - [ ] 实现 upload_files()
  - [ ] 实现 download_files()
  - [ ] 实现 fs_download() / fs_upload() / fs_list() / fs_delete()
  - [ ] 实现 destroy()
- [ ] 创建 `src/daytona_sandbox_manager.py`
  - [ ] 实现 get_thread_backend() - Agent Sandbox
  - [ ] 实现 get_files_backend() - Files Sandbox
  - [ ] 实现 _create_agent_sandbox()
  - [ ] 实现 _create_files_sandbox()
  - [ ] 实现 destroy_thread_backend()
- [ ] 创建 `src/daytona_volume_manager.py`
  - [ ] 实现 get_or_create_volume()
- [ ] 创建 `src/daytona_snapshot_manager.py`
  - [ ] 实现 create_skill_snapshot()
  - [ ] 实现 get_skill_snapshot()

## Phase 4: 服务层适配

- [ ] 更新 `src/agent_manager.py`
  - [ ] 导入改为 DaytonaSandboxManager
  - [ ] 使用 get_thread_backend() 获取 Agent Sandbox
- [ ] 更新 `src/webdav.py`
  - [ ] 改用 Daytona FS API
  - [ ] 使用 get_files_backend() 获取 Files Sandbox
  - [ ] 实现 propfind / get / put / delete / move
- [ ] 更新 `src/chunk_upload.py`
  - [ ] 改用 Daytona Volume
- [ ] 更新 `src/agent_skills/skill_validator.py`
  - [ ] 适配新沙箱接口

## Phase 5: API 层适配

- [ ] 更新 `api/server.py`
  - [ ] 导入改为 destroy_thread_backend from daytona_sandbox_manager
- [ ] 更新 `api/files.py`
  - [ ] 适配 Daytona Volume
- [ ] 更新 `api/admin.py`
  - [ ] /images → /snapshots
  - [ ] 更新 rollback 逻辑

## Phase 6: 清理与测试

- [ ] 删除 `src/docker_sandbox.py`
- [ ] 删除 `src/agent_skills/skill_image_manager.py`
- [ ] 更新 `AGENTS.md`
- [ ] 运行测试
  ```bash
  uv run python -m tests.skill_admin.run_all
  ```
- [ ] 手动测试
  - [ ] 创建会话 → 检查 Agent Sandbox 创建
  - [ ] 发送消息 → 检查命令执行
  - [ ] 上传文件 → 检查 Files Sandbox 创建
  - [ ] WebDAV 访问 → 检查文件列表/下载/上传
  - [ ] 多线程并发 → 检查会话隔离
  - [ ] Skill 验证 → 检查 Snapshot 创建

## 验收标准

### 功能验收
- [ ] 所有 API 接口正常工作
- [ ] 多线程并发无状态冲突（每线程独立 Sandbox）
- [ ] WebDAV 文件操作正常（使用 Files Sandbox）
- [ ] 文件上传/下载正常
- [ ] Skill 验证流程正常
- [ ] Snapshot 创建/使用正常

### Sandbox 生命周期验收
- [ ] Agent Sandbox: auto-stop 15min 正常
- [ ] Agent Sandbox: auto-delete 2h 正常
- [ ] Files Sandbox: auto-stop 60min 正常
- [ ] Volume 数据持久化正常（Sandbox 销毁后数据保留）

### 隔离性验收
- [ ] 同一用户多线程：各线程 Sandbox 独立
- [ ] 同一用户多线程：共享同一个 Volume
- [ ] Agent Sandbox 与 Files Sandbox 不互相干扰

## 关键配置确认

```bash
# Agent Sandbox
DAYTONA_AUTO_STOP_INTERVAL=15      # 15 分钟无活动停止
DAYTONA_AUTO_DELETE_INTERVAL=120   # 2 小时后删除

# Files Sandbox (WebDAV)
DAYTONA_FILES_SANDBOX_AUTO_STOP=60 # 60 分钟无活动停止

# Volume
DAYTONA_VOLUME_SIZE_GB=10          # 每个 Volume 10GB
```
