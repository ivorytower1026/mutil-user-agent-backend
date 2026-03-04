# 05. API 接口规范

## 1. API 端点

### 1.1 列出用户端口

```http
GET /api/ports
Authorization: Bearer {token}
```

**响应**:
```json
{
  "mappings": [
    {
      "id": 1,
      "external_url": "https://8080-user123.preview.example.com",
      "internal_port": 8080,
      "service_name": "my-web-app",
      "status": "active",
      "created_at": "2024-03-04T10:00:00Z"
    },
    {
      "id": 2,
      "external_url": "https://3000-user123.preview.example.com",
      "internal_port": 3000,
      "service_name": null,
      "status": "active",
      "created_at": "2024-03-04T11:00:00Z"
    }
  ],
  "total": 2
}
```

### 1.2 手动注册端口

```http
POST /api/ports/register
Authorization: Bearer {token}
Content-Type: application/json

{
  "internal_port": 8080,
  "service_name": "my-web-app",
  "thread_id": "user123-thread456"
}
```

**响应**:
```json
{
  "success": true,
  "external_url": "https://8080-user123.preview.example.com",
  "internal_port": 8080
}
```

**错误响应**:
```json
{
  "detail": "Port limit exceeded: User has reached max ports limit (10)"
}
```

### 1.3 自动检测端口

```http
POST /api/ports/detect
Authorization: Bearer {token}
Content-Type: application/json

{
  "thread_id": "user123-thread456"
}
```

**响应**:
```json
{
  "detected_ports": [8080, 3000, 5000],
  "registered": [
    "https://8080-user123.preview.example.com",
    "https://3000-user123.preview.example.com"
  ],
  "skipped": [
    {"port": 5000, "reason": "already_registered"}
  ]
}
```

### 1.4 取消端口映射

```http
DELETE /api/ports/{internal_port}
Authorization: Bearer {token}
```

**响应**:
```json
{
  "success": true
}
```

### 1.5 获取端口详情

```http
GET /api/ports/{internal_port}
Authorization: Bearer {token}
```

**响应**:
```json
{
  "id": 1,
  "external_url": "https://8080-user123.preview.example.com",
  "internal_port": 8080,
  "service_name": "my-web-app",
  "status": "active",
  "created_at": "2024-03-04T10:00:00Z",
  "last_accessed_at": "2024-03-04T12:00:00Z",
  "container_id": "abc123",
  "container_ip": "172.28.0.5"
}
```

## 2. API 实现代码

```python
# api/ports.py

from fastapi import APIRouter, Depends, HTTPException, Header
from typing import Optional
from pydantic import BaseModel, Field

from src.auth import get_current_user_id
from src.port_mapping import get_port_manager, PortMappingError, PortLimitExceeded
from src.docker_sandbox import get_thread_backend


router = APIRouter(prefix="/api/ports", tags=["ports"])


class PortRegisterRequest(BaseModel):
    internal_port: int = Field(..., ge=1024, le=65535)
    service_name: Optional[str] = Field(None, max_length=100)
    thread_id: str


class PortDetectRequest(BaseModel):
    thread_id: str


class PortMappingResponse(BaseModel):
    id: int
    external_url: str
    internal_port: int
    service_name: Optional[str]
    status: str
    created_at: str


class PortListResponse(BaseModel):
    mappings: list[PortMappingResponse]
    total: int


class PortRegisterResponse(BaseModel):
    success: bool
    external_url: str
    internal_port: int


class PortDetectResponse(BaseModel):
    detected_ports: list[int]
    registered: list[str]
    skipped: list[dict]


@router.get("", response_model=PortListResponse)
async def list_user_ports(
    user_id: str = Depends(get_current_user_id)
):
    """列出用户所有暴露的端口"""
    manager = get_port_manager()
    mappings = manager.list_user_ports(user_id)
    
    return PortListResponse(
        mappings=[
            PortMappingResponse(
                id=i,
                external_url=f"https://{m.external_host}",
                internal_port=m.internal_port,
                service_name=m.service_name,
                status=m.status,
                created_at=m.created_at
            )
            for i, m in enumerate(mappings)
        ],
        total=len(mappings)
    )


@router.post("/register", response_model=PortRegisterResponse)
async def register_port(
    request: PortRegisterRequest,
    user_id: str = Depends(get_current_user_id)
):
    """手动注册端口暴露"""
    if not request.thread_id.startswith(user_id):
        raise HTTPException(status_code=403, detail="Thread does not belong to user")
    
    try:
        backend = get_thread_backend(request.thread_id)
        container_ip = backend.get_container_ip()
        
        if not container_ip:
            raise HTTPException(
                status_code=400,
                detail="Cannot get container IP, ensure container is running"
            )
        
        manager = get_port_manager()
        external_url = manager.register(
            user_id=user_id,
            thread_id=request.thread_id,
            internal_port=request.internal_port,
            container_ip=container_ip,
            service_name=request.service_name
        )
        
        return PortRegisterResponse(
            success=True,
            external_url=external_url,
            internal_port=request.internal_port
        )
        
    except PortLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except PortMappingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/detect", response_model=PortDetectResponse)
async def detect_ports(
    request: PortDetectRequest,
    user_id: str = Depends(get_current_user_id)
):
    """检测并自动注册容器内的监听端口"""
    if not request.thread_id.startswith(user_id):
        raise HTTPException(status_code=403, detail="Thread does not belong to user")
    
    backend = get_thread_backend(request.thread_id)
    manager = get_port_manager()
    
    detected_ports = backend.detect_listening_ports()
    registered = []
    skipped = []
    
    for port in detected_ports:
        existing = manager.get_mapping(user_id, port)
        if existing:
            skipped.append({"port": port, "reason": "already_registered"})
            continue
        
        try:
            url = backend.auto_register_ports(manager, {port: None})
            if url:
                registered.extend(url)
        except Exception as e:
            skipped.append({"port": port, "reason": str(e)})
    
    return PortDetectResponse(
        detected_ports=detected_ports,
        registered=registered,
        skipped=skipped
    )


@router.delete("/{internal_port}")
async def unregister_port(
    internal_port: int,
    user_id: str = Depends(get_current_user_id)
):
    """取消端口暴露"""
    manager = get_port_manager()
    success = manager.unregister(user_id, internal_port)
    
    if not success:
        raise HTTPException(status_code=404, detail="Port mapping not found")
    
    return {"success": True}


@router.get("/{internal_port}", response_model=PortMappingResponse)
async def get_port_detail(
    internal_port: int,
    user_id: str = Depends(get_current_user_id)
):
    """获取端口详情"""
    manager = get_port_manager()
    mapping = manager.get_mapping(user_id, internal_port)
    
    if not mapping:
        raise HTTPException(status_code=404, detail="Port mapping not found")
    
    return PortMappingResponse(
        id=0,
        external_url=f"https://{mapping.external_host}",
        internal_port=mapping.internal_port,
        service_name=mapping.service_name,
        status=mapping.status,
        created_at=mapping.created_at
    )
```

## 3. 注册路由

```python
# main.py

from api.ports import router as ports_router

app.include_router(ports_router)
```

## 4. 错误码

| 状态码 | 错误类型 | 描述 |
|--------|----------|------|
| 200 | 成功 | 请求成功 |
| 201 | 已创建 | 端口映射创建成功 |
| 400 | 请求错误 | 端口无效或已被阻止 |
| 403 | 禁止访问 | 无权操作该资源 |
| 404 | 未找到 | 端口映射不存在 |
| 409 | 冲突 | 端口已映射 |
| 429 | 请求过多 | 超过端口限制 |
| 500 | 服务器错误 | 内部错误 |

## 5. WebSocket 事件 (可选)

```python
# 实时推送端口变化

from fastapi import WebSocket

@router.websocket("/ws/ports")
async def ports_websocket(
    websocket: WebSocket,
    user_id: str = Depends(get_current_user_id)
):
    await websocket.accept()
    
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
            elif data == "list":
                manager = get_port_manager()
                mappings = manager.list_user_ports(user_id)
                await websocket.send_json({
                    "type": "list",
                    "data": [
                        {
                            "port": m.internal_port,
                            "url": f"https://{m.external_host}",
                            "status": m.status
                        }
                        for m in mappings
                    ]
                })
    except Exception:
        pass
```

## 6. OpenAPI 文档

启动服务后访问：
- Swagger UI: `http://localhost:8002/docs`
- ReDoc: `http://localhost:8002/redoc`
- OpenAPI JSON: `http://localhost:8002/openapi.json`
