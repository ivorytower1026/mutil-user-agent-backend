# Docker 使用说明

## 快速开始

### 1. 创建挂载目录

Windows PowerShell:
```powershell
New-Item -ItemType Directory -Force -Path "D:\docker_volume\redis\data"
New-Item -ItemType Directory -Force -Path "D:\docker_volume\redis"
New-Item -ItemType Directory -Force -Path "D:\docker_volume\postgres\data"

if (-not (Test-Path "D:\docker_volume\redis\redis.conf")) {
    New-Item -ItemType File -Path "D:\docker_volume\redis\redis.conf"
}
```

Linux/Mac:
```bash
mkdir -p ~/.mutil-user-agent/redis/data
mkdir -p ~/.mutil-user-agent/postgres/data
touch ~/.mutil-user-agent/redis/redis.conf
```

### 2. 配置环境变量

编辑 `.env.docker` 文件，修改挂载路径和代理配置。

### 3. 启动所有容器

```bash
docker-compose --env-file .env.docker up -d
```

### 4. 验证服务

```bash
docker ps
docker exec -it redis redis-cli ping
docker exec -it postgres psql -U root -d agent_db -c "SELECT version();"
```

### 5. 更新应用配置

更新 `backend/.env` 文件：
```bash
DOCKER_IMAGE=python-sandbox:latest
```

### 6. 重启应用

```bash
uv run python main.py
```

## 常用命令

```bash
docker-compose logs -f
docker-compose stop
docker-compose restart
docker-compose down
docker-compose build --no-cache sandbox-builder
```

## 故障排查

详见 `design/v0_2_4_docker_compose_setup/README.md`
