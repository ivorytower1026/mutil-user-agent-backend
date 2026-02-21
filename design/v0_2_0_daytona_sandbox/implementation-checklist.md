# Daytona 重构实施检查清单（极简版）

## Step 1: 配置和依赖

- [ ] 更新 `pyproject.toml`
  - [ ] 移除 `docker>=7.1.0`
  - [ ] 添加 `daytona-sdk>=0.10.0`
- [ ] 运行 `uv sync`
- [ ] 更新 `src/config.py`
  - [ ] 添加 DAYTONA_API_KEY
  - [ ] 添加 DAYTONA_API_URL
  - [ ] 添加 DAYTONA_AUTO_STOP_INTERVAL (15 min)
  - [ ] 添加 DAYTONA_FILES_SANDBOX_AUTO_STOP (60 min)
- [ ] 更新 `.env` 文件

## Step 2: 核心文件

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
  - [ ] 实现 get_thread_backend()
  - [ ] 实现 get_files_backend()
  - [ ] 实现 destroy_thread_backend()
  - [ ] 纯内存缓存（无数据库）

## Step 3: 集成

- [ ] 修改 `src/agent_manager.py`
  - [ ] 导入改为 get_sandbox_manager
  - [ ] 使用 get_thread_backend()
  - [ ] 使用 destroy_thread_backend()
- [ ] 修改 `src/webdav.py`
  - [ ] 改用 Daytona FS API
  - [ ] 使用 get_files_backend()
- [ ] 修改 `api/server.py`
  - [ ] 导入改为 get_sandbox_manager
  - [ ] 使用 destroy_thread_backend()

## Step 4: 测试

- [ ] 创建 `tests/test_daytona_sandbox.py`
- [ ] 运行测试
  ```bash
  uv run python tests/test_daytona_sandbox.py
  ```
- [ ] 验收项
  - [ ] Agent Sandbox 创建/执行/销毁正常
  - [ ] Files Sandbox 上传/下载/列出/删除正常
  - [ ] Volume 持久化正常（不同 Sandbox 共享数据）

## Step 5: 清理

- [ ] 删除 `src/docker_sandbox.py`
- [ ] 更新 `AGENTS.md`

---

## 验收总表

| 验收项 | 状态 |
|--------|------|
| 依赖安装成功 | [ ] |
| 配置项加载正常 | [ ] |
| 核心文件创建成功 | [ ] |
| 服务能正常启动 | [ ] |
| Agent Sandbox 创建正常 | [ ] |
| Agent 命令执行正常 | [ ] |
| Agent 文件操作正常 | [ ] |
| Files Sandbox 创建正常 | [ ] |
| WebDAV 上传正常 | [ ] |
| WebDAV 下载正常 | [ ] |
| WebDAV 列出正常 | [ ] |
| WebDAV 删除正常 | [ ] |
| Volume 持久化正常 | [ ] |
| 旧代码已清理 | [ ] |

---

## 关键配置确认

```bash
# .env
DAYTONA_API_KEY=dtn_xxx
DAYTONA_API_URL=http://localhost:3000/api
DAYTONA_AUTO_STOP_INTERVAL=15
DAYTONA_FILES_SANDBOX_AUTO_STOP=60
```

## 极简方案特点

- ❌ 不需要数据库表
- ❌ 不需要 VolumeManager
- ❌ 不需要 SnapshotManager
- ✅ 纯内存缓存
- ✅ Daytona 自动管理一切
