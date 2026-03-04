# 02. 业界方案调研

## 1. 云 IDE 平台方案

### 1.1 Replit

**URL 格式**：
```
{project-name}.{username}.repl.co
```

**特点**：
- 自动检测容器内监听端口
- 多端口支持（通过不同子路径）
- 实时预览面板
- 支持 WebSocket

**端口检测机制**：
```python
# Replit 通过扫描 /proc/net/tcp 检测监听端口
# 或使用 netstat/ss 命令
ss -tln | awk 'NR>1 {print $4}' | cut -d: -f2
```

**架构参考**：
```
┌─────────────────────────────────────────────────────┐
│  User Browser                                       │
│       │                                             │
│       ▼                                             │
│  ┌─────────────┐                                   │
│  │ Replit CDN  │  (全球 CDN 加速)                  │
│  └──────┬──────┘                                   │
│         │                                           │
│         ▼                                           │
│  ┌─────────────┐                                   │
│  │   Nginx     │  (反向代理 + 负载均衡)             │
│  └──────┬──────┘                                   │
│         │                                           │
│    ┌────┴────┐                                     │
│    ▼         ▼                                     │
│  ┌─────┐   ┌─────┐                                 │
│  │Pod 1│   │Pod 2│  (Kubernetes Pods)             │
│  └─────┘   └─────┘                                 │
└─────────────────────────────────────────────────────┘
```

### 1.2 CodeSandbox

**URL 格式**：
```
{id}.csb.app          # 预览 URL
{id}-api.csb.app      # API 端点
```

**特点**：
- 基于 Docker 容器
- 沙箱隔离（Firecracker microVM）
- 短生命周期（临时预览）
- 支持在线协作

**技术栈**：
- Firecracker（轻量级虚拟机）
- SECCOMP 过滤器（系统调用限制）
- Namespace 隔离

### 1.3 GitHub Codespaces

**URL 格式**：
```
{port}-{repo}-{user}.preview.app.github.dev
```

**示例**：
```
https://3000-myrepo-myuser.preview.app.github.dev
https://8080-myrepo-myuser.preview.app.github.dev
```

**特点**：
- VS Code 集成
- 端口转发面板
- 支持私有仓库
- 可配置端口可见性（public/private）

**端口转发机制**：
```json
// .devcontainer.json
{
  "forwardPorts": [3000, 8080],
  "portsAttributes": {
    "3000": {
      "label": "Web App",
      "onAutoForward": "notify"
    }
  }
}
```

## 2. 内网穿透方案

### 2.1 frp (Fast Reverse Proxy)

**GitHub**: https://github.com/fatedier/frp (105k+ stars)

**架构**：
```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  ┌─────────┐         ┌─────────┐         ┌─────────┐   │
│  │  User   │ ──────► │  frps   │ ──────► │  frpc   │   │
│  │ Browser │         │ (Server)│         │ (Client)│   │
│  └─────────┘         └─────────┘         └────┬────┘   │
│       │                                        │         │
│       │                                    ┌───┴───┐   │
│       │                                    │ Local │   │
│       │                                    │Service│   │
│       │                                    └───────┘   │
│       │                                                │
│       └────────► Public URL: x.x.x.x:6000 ◄─────────┘│
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**配置示例**：
```toml
# frps.toml (服务端)
bindPort = 7000
vhostHTTPPort = 80

# frpc.toml (客户端)
serverAddr = "x.x.x.x"
serverPort = 7000

[[proxies]]
name = "web"
type = "http"
localPort = 8080
customDomains = ["myapp.example.com"]
```

**特点**：
- 支持 TCP/UDP/HTTP/HTTPS
- 支持子域名路由
- 支持 STCP（密钥访问）
- 支持 P2P 模式
- 带宽限制
- 负载均衡

### 2.2 ngrok

**特点**：
- 即开即用，无需配置
- 提供公共 URL
- 支持付费自定义域名

**缺点**：
- 免费版限制较多
- 依赖第三方服务
- 国内访问可能不稳定

### 2.3 Cloudflare Tunnel

**架构**：
```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   User      │ ───► │ Cloudflare  │ ───► │ cloudflared │
│             │      │    Edge     │      │   (Agent)   │
└─────────────┘      └─────────────┘      └──────┬──────┘
                                                 │
                                            ┌────┴────┐
                                            │  Local  │
                                            │ Service │
                                            └─────────┘
```

**特点**：
- 免费
- 自动 HTTPS
- DDoS 防护
- 支持自定义域名

## 3. Kubernetes 方案

### 3.1 多租户隔离模式

**命名空间隔离**：
```yaml
# 每个租户一个命名空间
apiVersion: v1
kind: Namespace
metadata:
  name: tenant-user123
  labels:
    tenant: user123
```

**网络策略**：
```yaml
# 默认拒绝跨命名空间通信
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-from-other-namespaces
spec:
  podSelector: {}
  ingress:
  - from:
    - podSelector: {}
```

**资源配额**：
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: tenant-quota
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8"
    limits.memory: 16Gi
    pods: "10"
```

### 3.2 Ingress 路由

**基于子域名**：
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: user-service
  annotations:
    kubernetes.io/ingress.class: nginx
spec:
  rules:
  - host: "8080-user123.preview.example.com"
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: user123-service
            port:
              number: 8080
```

### 3.3 NodePort vs LoadBalancer vs Ingress

| 类型 | 端口范围 | 外部访问 | 适用场景 |
|------|----------|----------|----------|
| NodePort | 30000-32767 | IP:NodePort | 开发测试 |
| LoadBalancer | 任意 | 云厂商 LB | 生产环境 |
| Ingress | 80/443 | 域名路由 | 多服务共享 |

## 4. 安全隔离技术

### 4.1 容器级别

| 技术 | 隔离程度 | 性能影响 | 适用场景 |
|------|----------|----------|----------|
| **Docker 默认** | 低 | 无 | 开发环境 |
| **User Namespace** | 中 | 低 | 多租户 |
| **gVisor** | 高 | 中 | 不可信代码 |
| **Kata Containers** | 最高 | 高 | 金融/政务 |
| **Firecracker** | 高 | 低 | Serverless |

### 4.2 网络隔离

```
┌─────────────────────────────────────────────────────┐
│                    网络隔离方案                      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Level 1: 端口级别                                  │
│  ├── 仅暴露必要端口                                 │
│  └── 使用非特权端口 (>1024)                        │
│                                                     │
│  Level 2: 容器级别                                  │
│  ├── Docker Bridge 网络                             │
│  └── 容器间默认隔离                                 │
│                                                     │
│  Level 3: 用户级别                                  │
│  ├── 每用户独立网络命名空间                         │
│  └── Network Policy 限制                            │
│                                                     │
│  Level 4: 应用级别                                  │
│  ├── TLS 加密                                       │
│  └── 认证授权                                       │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 4.3 资源限制

**Docker 资源限制**：
```bash
docker run \
  --cpus="1.0" \           # CPU 限制
  --memory="2g" \          # 内存限制
  --pids-limit=100 \       # 进程数限制
  --ulimit nproc=100 \     # 用户进程限制
  --device-read-bps=/dev/sda:10mb \   # 读带宽
  --device-write-bps=/dev/sda:10mb \  # 写带宽
  myimage
```

**cgroups v2 配置**：
```bash
# CPU 限制
echo 100000 > /sys/fs/cgroup/user123/cpu.max

# 内存限制
echo 2G > /sys/fs/cgroup/user123/memory.max

# IO 限制
echo "254:0 10485760" > /sys/fs/cgroup/user123/io.max
```

## 5. 最佳实践总结

### 5.1 URL 设计原则

1. **可预测性**：用户能预知自己服务的 URL
2. **唯一性**：避免冲突
3. **可读性**：易于理解和记忆
4. **安全性**：不暴露敏感信息

**推荐格式**：
```
{port}-{user_id}.preview.domain.com
{service_name}-{user_id}.preview.domain.com
```

### 5.2 端口管理策略

1. **端口池管理**：预分配端口范围
2. **自动回收**：超时未使用的端口回收
3. **冲突检测**：注册前检查冲突
4. **限制数量**：每用户最大端口数限制

### 5.3 安全建议

1. **最小权限**：仅暴露必要端口
2. **网络隔离**：用户间网络隔离
3. **资源限制**：防止资源滥用
4. **审计日志**：记录所有操作
5. **定期清理**：清理僵尸服务

## 6. 技术选型建议

| 场景 | 推荐方案 | 理由 |
|------|----------|------|
| 小规模 (< 100 用户) | Docker + Caddy | 简单易维护 |
| 中规模 (100-1000 用户) | Docker + Caddy + Redis | 扩展性好 |
| 大规模 (> 1000 用户) | Kubernetes + Ingress | 高可用可扩展 |
| 高安全要求 | gVisor/Kata | 强隔离 |
| Serverless | Firecracker | 快速启动 |
