# 07. 部署和运维指南

## 1. 部署步骤

### 1.1 Phase 1: 基础设施部署 (1-2 天)

#### Step 1: DNS 配置

```bash
# 1. 添加泛域名解析
# 类型: A
# 名称: *.preview
# 值: 服务器 IP

# 2. 验证 DNS
dig 8080-user123.preview.example.com
```

#### Step 2: 创建 Docker 网络

```bash
# 创建隔离网络
docker network create \
  --driver bridge \
  --subnet=172.28.0.0/16 \
  --gateway=172.28.0.1 \
  sandbox_network

# 验证网络
docker network ls
docker network inspect sandbox_network
```

#### Step 3: 部署 Caddy

```bash
# 创建 Caddy 配置目录
mkdir -p /etc/caddy

# 创建 Caddyfile
cat > /etc/caddy/Caddyfile << 'EOF'
{
    email admin@example.com
    admin 0.0.0.0:2019
}

*.preview.example.com {
    tls {
        dns cloudflare {env.CLOUDFLARE_API_TOKEN}
    }
    respond "Service not found" 404
}
EOF

# 启动 Caddy
docker run -d \
  --name caddy \
  --restart unless-stopped \
  -p 80:80 \
  -p 443:443 \
  -p 2019:2019 \
  -v /etc/caddy/Caddyfile:/etc/caddy/Caddyfile \
  -v caddy_data:/data \
  -v caddy_config:/config \
  -e CLOUDFLARE_API_TOKEN=your_token \
  --network sandbox_network \
  caddy:2

# 验证 Caddy
curl http://localhost:2019/config/
```

#### Step 4: 验证泛域名证书

```bash
# 检查证书
curl -v https://test.preview.example.com 2>&1 | grep "SSL certificate"

# 或使用 openssl
openssl s_client -connect test.preview.example.com:443 -servername test.preview.example.com
```

### 1.2 Phase 2: 核心功能部署 (2-3 天)

#### Step 1: 更新配置

```bash
# 添加环境变量
cat >> .env << 'EOF'

# 端口暴露配置
PREVIEW_DOMAIN=preview.example.com
CADDY_API_URL=http://caddy:2019
MAX_PORTS_PER_USER=10
PORT_MAPPING_TTL=86400
DOCKER_NETWORK_NAME=sandbox_network
DOCKER_PIDS_LIMIT=100
EOF
```

#### Step 2: 创建代码文件

```bash
# 创建目录
mkdir -p src/port_mapping

# 创建文件 (见 04_implementation.md)
touch src/port_mapping/__init__.py
touch src/port_mapping/manager.py
touch src/port_mapping/detector.py
touch src/port_mapping/caddy_client.py
touch src/port_mapping/exceptions.py
touch api/ports.py
```

#### Step 3: 更新数据库

```python
# 添加 PortMapping 模型到 src/database.py
# 运行数据库迁移
# (如果使用 Alembic)
alembic revision --autogenerate -m "add port mapping"
alembic upgrade head
```

#### Step 4: 重启服务

```bash
# 重启后端服务
uv run python main.py

# 或使用 Docker Compose
docker-compose up -d --build
```

### 1.3 Phase 3: 测试验证

```bash
# 1. 测试 API
curl -X POST http://localhost:8002/api/ports/register \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"internal_port": 8080, "thread_id": "user123-thread456"}'

# 2. 测试访问
curl https://8080-user123.preview.example.com

# 3. 测试自动检测
curl -X POST http://localhost:8002/api/ports/detect \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"thread_id": "user123-thread456"}'
```

## 2. Docker Compose 完整配置

```yaml
# docker-compose.yml

services:
  caddy:
    image: caddy:2
    container_name: caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "2019:2019"
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    environment:
      - CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}
    networks:
      - sandbox_network
    healthcheck:
      test: ["CMD", "caddy", "validate", "--config", "/etc/caddy/Caddyfile"]
      interval: 30s
      timeout: 10s
      retries: 3

  backend:
    build: .
    container_name: backend
    restart: unless-stopped
    ports:
      - "${PORT}:8002"
    volumes:
      - ${WORKSPACE_ROOT}:/workspaces
      - ${SHARED_DIR}:/shared
      - ${SKILL_DIR}:/skills
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - PREVIEW_DOMAIN=${PREVIEW_DOMAIN}
      - CADDY_API_URL=http://caddy:2019
      - DOCKER_NETWORK_NAME=sandbox_network
    networks:
      - sandbox_network
    depends_on:
      - caddy
      - redis
      - db
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8002/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:7-alpine
    container_name: redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    networks:
      - sandbox_network

  db:
    image: postgres:15
    container_name: postgres
    restart: unless-stopped
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_USER=${DB_USER}
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=${DB_NAME}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - sandbox_network

volumes:
  caddy_data:
  caddy_config:
  redis_data:
  postgres_data:

networks:
  sandbox_network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
          gateway: 172.28.0.1
```

## 3. 运维操作

### 3.1 常用命令

```bash
# 查看所有端口映射
redis-cli KEYS "port_map:*"

# 查看特定用户的端口
redis-cli KEYS "port_map:user123:*"

# 查看映射详情
redis-cli HGETALL "port_map:user123:thread456:8080"

# 删除映射
redis-cli DEL "port_map:user123:thread456:8080"

# 查看 Caddy 路由
curl http://localhost:2019/config/apps/http/servers/srv0/routes | jq

# 删除 Caddy 路由
curl -X DELETE http://localhost:2019/id/8080-user123.preview.example.com
```

### 3.2 监控脚本

```python
# scripts/monitor_ports.py

import redis
import time
from datetime import datetime

def monitor_ports():
    r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
    
    print(f"=== Port Mapping Monitor ===")
    print(f"Time: {datetime.now()}")
    print()
    
    total = 0
    for key in r.scan_iter("port_map:*"):
        data = r.hgetall(key)
        if data:
            total += 1
            print(f"Host: {data.get('external_host')}")
            print(f"  Port: {data.get('internal_port')}")
            print(f"  IP: {data.get('container_ip')}")
            print(f"  Last Active: {data.get('last_active')}")
            print()
    
    print(f"Total mappings: {total}")

if __name__ == "__main__":
    monitor_ports()
```

### 3.3 清理脚本

```python
# scripts/cleanup_ports.py

import redis
import time

def cleanup_inactive(max_inactive_hours=24):
    r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
    
    now = time.time()
    max_inactive_seconds = max_inactive_hours * 3600
    cleaned = 0
    
    for key in r.scan_iter("port_map:*"):
        data = r.hgetall(key)
        if not data:
            continue
        
        last_active = float(data.get("last_active", 0))
        if now - last_active > max_inactive_seconds:
            print(f"Cleaning up: {key}")
            r.delete(key)
            cleaned += 1
    
    print(f"Cleaned {cleaned} inactive mappings")
    return cleaned

if __name__ == "__main__":
    cleanup_inactive(24)
```

## 4. 故障排查

### 4.1 证书问题

```bash
# 检查证书状态
curl http://localhost:2019/certificates

# 强制续期
caddy reload --config /etc/caddy/Caddyfile

# 查看证书详情
caddy cert verify --domain preview.example.com
```

### 4.2 路由问题

```bash
# 列出所有路由
curl http://localhost:2019/config/apps/http/servers/srv0/routes | jq

# 测试特定路由
curl -H "Host: 8080-user123.preview.example.com" http://localhost/

# 检查 Caddy 日志
docker logs caddy -f
```

### 4.3 容器网络问题

```bash
# 检查容器网络
docker network inspect sandbox_network

# 检查容器 IP
docker inspect <container_id> | grep IPAddress

# 测试容器连通性
docker exec <container_id> ping caddy
```

### 4.4 Redis 问题

```bash
# 检查 Redis 连接
redis-cli ping

# 查看 Redis 内存
redis-cli info memory

# 查看 key 数量
redis-cli DBSIZE
```

## 5. 扩展到 Kubernetes

### 5.1 架构变化

```
单机 Docker                    Kubernetes 集群
─────────────                  ─────────────────
Caddy                    →     Ingress Controller
Docker Bridge Network    →     CNI (Calico/Flannel)
Redis                    →     Redis Cluster / etcd
PortMappingManager       →     Service + Ingress API
```

### 5.2 迁移步骤

1. **部署 Redis Cluster**
2. **修改 PortMappingManager** 使用 Kubernetes API
3. **创建 Ingress 规则** 替代 Caddy 路由
4. **配置 NetworkPolicy** 实现网络隔离

```yaml
# K8s Ingress 示例
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: preview-ingress
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
  - hosts:
    - "*.preview.example.com"
    secretName: preview-tls
  rules:
  - host: "*.preview.example.com"
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: preview-proxy
            port:
              number: 80
```

## 6. 安全加固

### 6.1 网络安全

```bash
# 配置防火墙
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 2019/tcp  # 仅限内部访问
ufw enable

# 限制 Caddy API 访问
# 只允许本地和 Docker 网络访问
```

### 6.2 容器安全

```yaml
# 安全配置
security_opt:
  - no-new-privileges:true
  - seccomp:seccomp-profile.json
cap_drop:
  - ALL
cap_add:
  - NET_BIND_SERVICE
read_only: true
tmpfs:
  - /tmp:size=100M
```

### 6.3 监控告警

```yaml
# Prometheus 告警规则
groups:
  - name: port_mapping
    rules:
      - alert: TooManyPortMappings
        expr: port_mappings_total > 1000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Too many port mappings"
          
      - alert: CaddyDown
        expr: up{job="caddy"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Caddy is down"
```

## 7. 备份恢复

### 7.1 Redis 备份

```bash
# 手动备份
redis-cli BGSAVE
cp /var/lib/redis/dump.rdb /backup/redis-$(date +%Y%m%d).rdb

# 自动备份 (cron)
0 2 * * * redis-cli BGSAVE && cp /var/lib/redis/dump.rdb /backup/redis-$(date +\%Y\%m\%d).rdb
```

### 7.2 恢复

```bash
# 停止 Redis
systemctl stop redis

# 恢复数据
cp /backup/redis-20240304.rdb /var/lib/redis/dump.rdb

# 启动 Redis
systemctl start redis
```
