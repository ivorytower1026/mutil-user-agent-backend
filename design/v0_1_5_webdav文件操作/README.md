# v0.1.5 WebDAV 文件操作方案

> 基于标准 WebDAV 协议实现 Web 端文件管理功能

## 一、现象（实际）

1. **当前状态**：用户文件存储在 `workspaces/{user_id}/{thread_id}/`，通过 Docker volume 映射到容器内 `/workspace`
2. **Web API 缺失**：没有文件操作端点，用户只能通过 Agent 对话间接操作文件
3. **认证体系**：已有 JWT 认证，`user_id` 从 token 获取
4. **文件实际位置**：宿主机 `workspaces/` 目录，与容器通过 volume 共享

## 二、意图（期望）

1. **标准 WebDAV 协议**：前端可用 webdav.js 等现成库，无需自定义协议
2. **丝滑体验**：列表、上传、下载、编辑、删除、重命名、移动
3. **安全隔离**：每个用户只能访问自己的 workspace 目录
4. **大文件支持**：>100MB 文件分片上传
5. **并发安全**：ETag 版本检测，防止覆盖

## 三、情境（环境约束）

1. **多租户隔离**：JWT 中提取 user_id，限制访问 `workspaces/{user_id}/`
2. **与 Agent 共享**：文件操作立即可见于 Agent（同一 volume）
3. **Windows 环境**：当前开发环境为 Windows
4. **无需 Docker 交互**：直接操作宿主机文件即可
5. **Python 3.13**：使用现代 Python 特性

## 四、边界（明确不做）

1. **不做完整的 WebDAV 服务器**：只实现 PROPFIND/GET/PUT/MKCOL/DELETE/MOVE 6 个方法
2. **不做 WebDAV 锁**：不支持 LOCK/UNLOCK（简化实现）
3. **不做版本控制**：文件版本管理不在此次范围
4. **不做文件预览**：图片/PDF 等预览由前端处理
5. **不做在线 IDE**：编辑器仅满足基本需求

---

## 五、技术方案

### 5.1 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                         FastAPI App                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ /api/chat   │  │ /dav/*      │  │ /api/files/*            │  │
│  │ Agent 对话   │  │ WebDAV 操作  │  │ 分片上传等补充           │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│                           │                                      │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    JWT Auth Middleware                       ││
│  │                 提取 user_id，验证权限                        ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                   workspaces/{user_id}/
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         {thread_1}/     {thread_2}/     shared/
```

### 5.2 API 设计

#### 5.2.1 WebDAV 标准接口

| Method | 路径 | 功能 | HTTP 状态码 |
|--------|------|------|------------|
| PROPFIND | `/dav/{path:path}` | 列目录/获取属性 | 207 Multi-Status |
| GET | `/dav/{path:path}` | 下载文件 | 200 OK |
| PUT | `/dav/{path:path}` | 上传文件 | 201 Created |
| MKCOL | `/dav/{path:path}` | 创建目录 | 201 Created |
| DELETE | `/dav/{path:path}` | 删除文件/目录 | 204 No Content |
| MOVE | `/dav/{path:path}` | 移动/重命名 | 201 Created |

**PROPFIND Depth 语义**：
- `Depth: 0` - 只返回当前资源属性
- `Depth: 1` - 返回当前资源及其直接子资源（默认）

**PUT 冲突检测**：
- 请求头 `If-Match: "{etag}"` 可选
- 如果提供且 ETag 不匹配，返回 409 Conflict

**MOVE 请求头**：
- `Destination: /dav/new/path` - 目标路径

#### 5.2.2 补充 API（分片上传）

| Method | 路径 | 功能 |
|--------|------|------|
| POST | `/api/files/init-upload` | 分片上传初始化 |
| POST | `/api/files/upload-chunk` | 上传分片 |
| POST | `/api/files/complete-upload` | 合并分片 |
| DELETE | `/api/files/upload/{upload_id}` | 取消上传 |

---

## 六、数据模型

### 6.1 分片上传

```python
# api/models.py

class UploadInitRequest(BaseModel):
    filename: str
    total_chunks: int
    total_size: int
    target_path: str | None = None

class UploadInitResponse(BaseModel):
    upload_id: str
    chunk_size: int  # 10MB

class UploadChunkRequest(BaseModel):
    upload_id: str
    chunk_index: int

class UploadCompleteRequest(BaseModel):
    upload_id: str
    target_path: str

class FileInfo(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory"]
    size: int | None = None
    modified: str | None = None
    etag: str | None = None
```

### 6.2 临时文件存储

```
workspaces/
└── .uploads/                    # 临时上传目录
    └── {upload_id}/
        ├── meta.json            # {filename, total_chunks, received: [0,1,2...], created_at}
        ├── chunk_0
        ├── chunk_1
        └── ...
```

---

## 七、文件结构

```
src/
├── webdav.py            # WebDAV 核心实现
│   ├── WebDAVHandler
│   │   ├── _user_path()     # 安全路径解析
│   │   ├── _etag()          # 生成 ETag
│   │   ├── _build_propfind_xml()  # 构建响应
│   │   ├── propfind()       # 列目录
│   │   ├── get()            # 下载
│   │   ├── put()            # 上传
│   │   ├── mkcol()          # 创建目录
│   │   ├── delete()         # 删除
│   │   └── move()           # 移动/重命名
│
├── chunk_upload.py      # 分片上传管理
│   └── ChunkUploadManager
│       ├── init()
│       ├── save_chunk()
│       ├── complete()
│       ├── cancel()
│       └── cleanup_stale()
│
api/
├── webdav.py            # WebDAV 路由
│   └── router.mount("/dav", ...)
│
├── files.py             # 补充 API 路由
│   └── router.post("/api/files/...")
│
└── models.py            # 新增 Pydantic 模型
```

---

## 八、核心实现

### 8.1 WebDAV Handler

```python
# src/webdav.py
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from datetime import datetime
import xml.etree.ElementTree as ET
import shutil

class WebDAVHandler:
    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root)
    
    def _user_path(self, user_id: str, rel_path: str) -> Path:
        """安全路径解析，防止路径穿越"""
        base = (self.root / user_id).resolve()
        target = (base / rel_path.lstrip('/')).resolve()
        if not str(target).startswith(str(base)):
            raise HTTPException(403, "Access denied")
        return target
    
    def _etag(self, path: Path) -> str:
        """生成 ETag（基于 mtime + size）"""
        stat = path.stat()
        return f'"{stat.st_mtime_ns}-{stat.st_size}"'
    
    def _build_propfind_xml(self, target: Path, depth: int) -> str:
        """构建 PROPFIND 响应 XML"""
        # 实现略，返回 WebDAV 标准格式 XML
        pass
    
    async def propfind(self, user_id: str, path: str, depth: int = 1) -> Response:
        """PROPFIND - 列目录"""
        target = self._user_path(user_id, path)
        if not target.exists():
            raise HTTPException(404, "Not found")
        
        xml = self._build_propfind_xml(target, depth)
        return Response(
            content=xml,
            media_type="application/xml; charset=utf-8",
            status_code=207,
            headers={"DAV": "1"}
        )
    
    async def get(self, user_id: str, path: str) -> StreamingResponse:
        """GET - 下载文件"""
        target = self._user_path(user_id, path)
        if not target.is_file():
            raise HTTPException(404, "Not found")
        
        def iterfile():
            with open(target, 'rb') as f:
                while chunk := f.read(64 * 1024):
                    yield chunk
        
        return StreamingResponse(
            iterfile(),
            media_type="application/octet-stream",
            headers={
                "ETag": self._etag(target),
                "Content-Disposition": f'attachment; filename="{target.name}"'
            }
        )
    
    async def put(
        self, 
        user_id: str, 
        path: str, 
        body: bytes,
        if_match: str | None = None
    ) -> Response:
        """PUT - 上传文件"""
        target = self._user_path(user_id, path)
        
        # ETag 冲突检测
        if target.exists() and if_match:
            if self._etag(target) != if_match:
                raise HTTPException(
                    409, 
                    {"error": "conflict", "message": "File has been modified"}
                )
        
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        
        return Response(
            status_code=201,
            headers={"ETag": self._etag(target)}
        )
    
    async def mkcol(self, user_id: str, path: str) -> Response:
        """MKCOL - 创建目录"""
        target = self._user_path(user_id, path)
        if target.exists():
            raise HTTPException(405, "Already exists")
        target.mkdir(parents=True, exist_ok=True)
        return Response(status_code=201)
    
    async def delete(self, user_id: str, path: str) -> Response:
        """DELETE - 删除文件/目录"""
        target = self._user_path(user_id, path)
        if not target.exists():
            raise HTTPException(404, "Not found")
        
        if target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        
        return Response(status_code=204)
    
    async def move(self, user_id: str, src: str, dst: str) -> Response:
        """MOVE - 移动/重命名"""
        src_path = self._user_path(user_id, src)
        dst_path = self._user_path(user_id, dst)
        
        if not src_path.exists():
            raise HTTPException(404, "Source not found")
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        src_path.rename(dst_path)
        
        return Response(status_code=201)
```

### 8.2 分片上传管理

```python
# src/chunk_upload.py
import json
import uuid
from pathlib import Path
from datetime import datetime, timedelta

class ChunkUploadManager:
    CHUNK_SIZE = 10 * 1024 * 1024  # 10MB
    EXPIRE_HOURS = 24
    
    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root)
        self.upload_dir = self.root / ".uploads"
        self.upload_dir.mkdir(exist_ok=True)
    
    def init(self, user_id: str, filename: str, total_chunks: int, 
             total_size: int) -> str:
        """初始化上传，返回 upload_id"""
        upload_id = str(uuid.uuid4())
        upload_path = self.upload_dir / upload_id
        upload_path.mkdir()
        
        meta = {
            "user_id": user_id,
            "filename": filename,
            "total_chunks": total_chunks,
            "total_size": total_size,
            "received": [],
            "created_at": datetime.now().isoformat()
        }
        (upload_path / "meta.json").write_text(json.dumps(meta))
        
        return upload_id
    
    def save_chunk(self, upload_id: str, chunk_index: int, data: bytes) -> bool:
        """保存分片"""
        meta = self._load_meta(upload_id)
        chunk_path = self.upload_dir / upload_id / f"chunk_{chunk_index}"
        chunk_path.write_bytes(data)
        
        if chunk_index not in meta["received"]:
            meta["received"].append(chunk_index)
            self._save_meta(upload_id, meta)
        
        return True
    
    def complete(self, upload_id: str, user_id: str, target_path: str) -> Path:
        """合并分片到目标位置"""
        meta = self._load_meta(upload_id)
        
        if len(meta["received"]) != meta["total_chunks"]:
            raise ValueError("Not all chunks received")
        
        # 目标路径
        base = (self.root / user_id).resolve()
        target = (base / target_path.lstrip('/')).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        
        # 合并文件
        with open(target, 'wb') as outfile:
            for i in range(meta["total_chunks"]):
                chunk_path = self.upload_dir / upload_id / f"chunk_{i}"
                outfile.write(chunk_path.read_bytes())
        
        # 清理临时文件
        self.cancel(upload_id)
        
        return target
    
    def cancel(self, upload_id: str) -> None:
        """取消上传，清理临时文件"""
        import shutil
        upload_path = self.upload_dir / upload_id
        if upload_path.exists():
            shutil.rmtree(upload_path)
    
    def cleanup_stale(self) -> int:
        """清理过期的临时文件（启动时调用）"""
        count = 0
        threshold = datetime.now() - timedelta(hours=self.EXPIRE_HOURS)
        
        for upload_dir in self.upload_dir.iterdir():
            if not upload_dir.is_dir():
                continue
            try:
                meta = json.loads((upload_dir / "meta.json").read_text())
                created = datetime.fromisoformat(meta["created_at"])
                if created < threshold:
                    self.cancel(upload_dir.name)
                    count += 1
            except Exception:
                pass
        
        return count
    
    def _load_meta(self, upload_id: str) -> dict:
        meta_path = self.upload_dir / upload_id / "meta.json"
        return json.loads(meta_path.read_text())
    
    def _save_meta(self, upload_id: str, meta: dict) -> None:
        meta_path = self.upload_dir / upload_id / "meta.json"
        meta_path.write_text(json.dumps(meta))
```

### 8.3 API 路由

```python
# api/webdav.py
from fastapi import APIRouter, Request, Depends, Header
from fastapi.responses import Response
from src.webdav import WebDAVHandler
from src.auth import get_current_user
from src.config import settings

router = APIRouter()
webdav = WebDAVHandler(settings.WORKSPACE_ROOT)

@router.api_route("/{path:path}", methods=["PROPFIND", "GET", "PUT", "MKCOL", "DELETE", "MOVE"])
async def webdav_handler(
    request: Request,
    path: str,
    user_id: str = Depends(get_current_user),
    depth: int = Header(default=1, alias="Depth"),
    destination: str | None = Header(default=None, alias="Destination"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    if request.method == "PROPFIND":
        return await webdav.propfind(user_id, path, depth)
    
    elif request.method == "GET":
        return await webdav.get(user_id, path)
    
    elif request.method == "PUT":
        body = await request.body()
        return await webdav.put(user_id, path, body, if_match)
    
    elif request.method == "MKCOL":
        return await webdav.mkcol(user_id, path)
    
    elif request.method == "DELETE":
        return await webdav.delete(user_id, path)
    
    elif request.method == "MOVE":
        if not destination:
            from fastapi import HTTPException
            raise HTTPException(400, "Destination header required")
        # 解析 destination，提取路径
        dst_path = destination.split("/dav/")[-1]
        return await webdav.move(user_id, path, dst_path)
```

---

## 九、前端集成

### 9.1 使用 webdav.js

```bash
npm install webdav
```

```javascript
// 前端代码示例
import { createClient } from "webdav";

const client = createClient("/dav", {
  headers: {
    Authorization: `Bearer ${localStorage.getItem("token")}`
  }
});

// 列目录
async function listFiles(path = "/") {
  const items = await client.getDirectoryContents(path);
  return items.map(item => ({
    name: item.basename,
    type: item.type,  // 'file' or 'directory'
    size: item.size,
    modified: item.lastmod
  }));
}

// 上传文件
async function uploadFile(path, file) {
  const content = await file.arrayBuffer();
  await client.putFileContents(path, content);
}

// 下载文件
async function downloadFile(path) {
  const content = await client.getFileContents(path);
  return content;
}

// 创建目录
async function createDirectory(path) {
  await client.createDirectory(path);
}

// 删除
async function deleteItem(path) {
  await client.deleteFile(path);
}

// 重命名/移动
async function moveItem(src, dst) {
  await client.moveFile(src, dst);
}
```

### 9.2 分片上传（大文件）

```javascript
// 分片上传示例
const CHUNK_SIZE = 10 * 1024 * 1024; // 10MB

async function uploadLargeFile(file, targetPath, onProgress) {
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
  
  // 1. 初始化
  const initRes = await fetch("/api/files/init-upload", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`
    },
    body: JSON.stringify({
      filename: file.name,
      total_chunks: totalChunks,
      total_size: file.size,
      target_path: targetPath
    })
  });
  const { upload_id } = await initRes.json();
  
  // 2. 分片上传
  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const chunk = file.slice(start, start + CHUNK_SIZE);
    
    const formData = new FormData();
    formData.append("upload_id", upload_id);
    formData.append("chunk_index", i);
    formData.append("chunk", chunk);
    
    await fetch("/api/files/upload-chunk", {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` },
      body: formData
    });
    
    onProgress?.((i + 1) / totalChunks * 100);
  }
  
  // 3. 完成
  await fetch("/api/files/complete-upload", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`
    },
    body: JSON.stringify({
      upload_id,
      target_path: targetPath
    })
  });
}
```

---

## 十、实现计划

| 阶段 | 任务 | 文件 | 工时 |
|------|------|------|------|
| **P0** | WebDAV 核心 | `src/webdav.py`, `api/webdav.py` | 1天 |
| **P1** | 分片上传 | `src/chunk_upload.py`, `api/files.py` | 0.5天 |
| **P2** | ETag 冲突检测 | 集成到 WebDAV Handler | 0.5天 |
| **P3** | 临时文件清理 | 启动时调用 `cleanup_stale()` | 0.5天 |
| **P4** | 测试 | `tests/test_webdav.py` | 0.5天 |

**总计：3天**

---

## 十一、注意事项

### 11.1 安全考虑

1. **路径穿越防护**：`_user_path()` 必须校验最终路径在用户目录内
2. **JWT 认证**：所有请求必须携带有效 token
3. **文件大小限制**：单次 PUT 限制（如 100MB），超过用分片上传
4. **临时文件清理**：启动时 + 定时清理过期上传

### 11.2 性能优化

1. **流式传输**：GET 使用 `StreamingResponse`，避免大文件读入内存
2. **分片大小**：10MB 是合理的平衡点
3. **ETag 计算**：基于 mtime + size，避免计算完整 hash

### 11.3 兼容性

1. **Windows 路径**：使用 `pathlib.Path` 自动处理
2. **编码**：统一 UTF-8
3. **前端库**：webdav.js 兼容主流浏览器
