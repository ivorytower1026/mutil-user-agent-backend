# WebDAV 文件操作 - 前端对接文档

## 一、概述

本文档描述前端如何对接 v0.1.5 版本的 WebDAV 文件操作 API。

### 基础信息

- **Base URL**: `http://your-server:8006`
- **认证方式**: JWT Bearer Token
- **用户隔离**: 每个用户只能访问 `workspaces/{user_id}/` 下的文件

### 认证流程

```javascript
// 1. 注册
const registerRes = await fetch('/api/auth/register', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'user1', password: 'pass123' })
});

// 2. 登录获取 Token
const loginRes = await fetch('/api/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'user1', password: 'pass123' })
});
const { access_token } = await loginRes.json();

// 3. 后续请求携带 Token
const headers = {
  'Authorization': `Bearer ${access_token}`
};
```

---

## 二、WebDAV 接口

### 2.1 列目录 (PROPFIND)

获取目录内容或文件属性。

**请求:**
```http
PROPFIND /dav/{path} HTTP/1.1
Authorization: Bearer {token}
Depth: 1
```

**参数:**
| 参数 | 说明 |
|------|------|
| `path` | 相对路径，如 `/` 或 `/mydir` |
| `Depth` | `0`=仅当前资源，`1`=包含子资源（默认） |

**响应 (207 Multi-Status):**
```xml
<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/dav/user1/mydir/</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>mydir</D:displayname>
        <D:resourcetype><D:collection/></D:resourcetype>
        <D:getlastmodified>Sat, 14 Feb 2026 10:00:00 GMT</D:getlastmodified>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/dav/user1/mydir/file.txt</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>file.txt</D:displayname>
        <D:resourcetype/>
        <D:getlastmodified>Sat, 14 Feb 2026 10:01:00 GMT</D:getlastmodified>
        <D:getcontentlength>1024</D:getcontentlength>
        <D:getetag>"1771037758522469700-1024"</D:getetag>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>
```

**前端示例:**
```javascript
async function listDirectory(path = '/') {
  const response = await fetch(`/dav${path}`, {
    method: 'PROPFIND',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Depth': '1'
    }
  });
  
  if (response.status !== 207) {
    throw new Error(`PROPFIND failed: ${response.status}`);
  }
  
  const xml = await response.text();
  return parseWebDAVResponse(xml);
}

function parseWebDAVResponse(xml) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xml, 'application/xml');
  const responses = doc.getElementsByTagNameNS('DAV:', 'response');
  
  const items = [];
  for (const resp of responses) {
    const href = resp.getElementsByTagNameNS('DAV:', 'href')[0]?.textContent;
    const displayname = resp.getElementsByTagNameNS('DAV:', 'displayname')[0]?.textContent;
    const resourcetype = resp.getElementsByTagNameNS('DAV:', 'resourcetype')[0];
    const isDir = resourcetype?.getElementsByTagNameNS('DAV:', 'collection').length > 0;
    const contentLength = resp.getElementsByTagNameNS('DAV:', 'getcontentlength')[0]?.textContent;
    const lastModified = resp.getElementsByTagNameNS('DAV:', 'getlastmodified')[0]?.textContent;
    const etag = resp.getElementsByTagNameNS('DAV:', 'getetag')[0]?.textContent;
    
    items.push({
      href,
      name: displayname,
      type: isDir ? 'directory' : 'file',
      size: contentLength ? parseInt(contentLength) : null,
      modified: lastModified,
      etag: etag
    });
  }
  
  return items;
}
```

---

### 2.2 下载文件 (GET)

**请求:**
```http
GET /dav/{path} HTTP/1.1
Authorization: Bearer {token}
```

**响应:**
```http
HTTP/1.1 200 OK
Content-Type: application/octet-stream
ETag: "{etag}"
Content-Disposition: attachment; filename="file.txt"

{file content}
```

**前端示例:**
```javascript
async function downloadFile(path) {
  const response = await fetch(`/dav${path}`, {
    method: 'GET',
    headers: { 'Authorization': `Bearer ${token}` }
  });
  
  if (!response.ok) {
    throw new Error(`Download failed: ${response.status}`);
  }
  
  const etag = response.headers.get('ETag');
  const blob = await response.blob();
  
  return { blob, etag };
}

// 触发浏览器下载
async function downloadAndSave(path, filename) {
  const { blob } = await downloadFile(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
```

---

### 2.3 上传文件 (PUT)

**请求:**
```http
PUT /dav/{path} HTTP/1.1
Authorization: Bearer {token}
If-Match: "{etag}"  (可选，用于冲突检测)
Content-Type: application/octet-stream

{file content}
```

**响应:**
```http
HTTP/1.1 201 Created
ETag: "{new_etag}"
```

**冲突检测:**
- 如果提供 `If-Match` 且 ETag 不匹配，返回 `409 Conflict`
- 用于防止覆盖他人修改

**前端示例:**
```javascript
async function uploadFile(path, file, etag = null) {
  const headers = {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/octet-stream'
  };
  
  if (etag) {
    headers['If-Match'] = etag;
  }
  
  const response = await fetch(`/dav${path}`, {
    method: 'PUT',
    headers,
    body: file
  });
  
  if (response.status === 409) {
    throw new Error('File conflict: file has been modified');
  }
  
  if (response.status !== 201) {
    throw new Error(`Upload failed: ${response.status}`);
  }
  
  return response.headers.get('ETag');
}

// 示例：上传用户选择的文件
async function handleFileUpload(file) {
  const etag = await uploadFile(`/documents/${file.name}`, file);
  console.log('Uploaded with ETag:', etag);
}
```

---

### 2.4 创建目录 (MKCOL)

**请求:**
```http
MKCOL /dav/{path} HTTP/1.1
Authorization: Bearer {token}
```

**响应:**
- `201 Created` - 创建成功
- `405 Method Not Allowed` - 目录已存在

**前端示例:**
```javascript
async function createDirectory(path) {
  const response = await fetch(`/dav${path}`, {
    method: 'MKCOL',
    headers: { 'Authorization': `Bearer ${token}` }
  });
  
  if (response.status === 201) {
    return true;
  }
  if (response.status === 405) {
    throw new Error('Directory already exists');
  }
  throw new Error(`MKCOL failed: ${response.status}`);
}
```

---

### 2.5 删除文件/目录 (DELETE)

**请求:**
```http
DELETE /dav/{path} HTTP/1.1
Authorization: Bearer {token}
```

**响应:**
- `204 No Content` - 删除成功
- `404 Not Found` - 资源不存在

**前端示例:**
```javascript
async function deleteItem(path) {
  const response = await fetch(`/dav${path}`, {
    method: 'DELETE',
    headers: { 'Authorization': `Bearer ${token}` }
  });
  
  if (response.status === 204) {
    return true;
  }
  if (response.status === 404) {
    throw new Error('Item not found');
  }
  throw new Error(`DELETE failed: ${response.status}`);
}
```

---

### 2.6 移动/重命名 (MOVE)

**请求:**
```http
MOVE /dav/{source_path} HTTP/1.1
Authorization: Bearer {token}
Destination: /dav/{dest_path}
```

**响应:**
- `201 Created` - 移动成功
- `404 Not Found` - 源不存在

**前端示例:**
```javascript
async function moveItem(sourcePath, destPath) {
  const response = await fetch(`/dav${sourcePath}`, {
    method: 'MOVE',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Destination': `/dav${destPath}`
    }
  });
  
  if (response.status === 201) {
    return true;
  }
  if (response.status === 404) {
    throw new Error('Source not found');
  }
  throw new Error(`MOVE failed: ${response.status}`);
}

// 重命名示例
async function renameItem(path, newName) {
  const parentPath = path.substring(0, path.lastIndexOf('/'));
  const destPath = `${parentPath}/${newName}`;
  return moveItem(path, destPath);
}
```

---

## 三、分片上传接口（大文件）

> 适用于 >100MB 的大文件上传

### 3.1 初始化上传

**请求:**
```http
POST /api/files/init-upload HTTP/1.1
Authorization: Bearer {token}
Content-Type: application/json

{
  "filename": "large_video.mp4",
  "total_chunks": 10,
  "total_size": 104857600,
  "target_path": "videos/large_video.mp4"
}
```

**参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `filename` | string | 是 | 原始文件名 |
| `total_chunks` | int | 是 | 分片总数 |
| `total_size` | int | 是 | 文件总大小（字节） |
| `target_path` | string | 否 | 目标路径（默认为文件名） |

**响应:**
```json
{
  "upload_id": "709f4536-5236-4b33-912f-aebe4785a010",
  "chunk_size": 10485760
}
```

---

### 3.2 上传分片

**请求:**
```http
POST /api/files/upload-chunk HTTP/1.1
Authorization: Bearer {token}
Content-Type: multipart/form-data

upload_id=709f4536-5236-4b33-912f-aebe4785a010
chunk_index=0
chunk=<binary data>
```

**响应:**
```json
{
  "success": true,
  "chunk_index": 0,
  "received_count": 1
}
```

---

### 3.3 完成上传

**请求:**
```http
POST /api/files/complete-upload HTTP/1.1
Authorization: Bearer {token}
Content-Type: application/json

{
  "upload_id": "709f4536-5236-4b33-912f-aebe4785a010",
  "target_path": "videos/large_video.mp4"
}
```

**响应:**
```json
{
  "success": true,
  "path": "videos/large_video.mp4"
}
```

---

### 3.4 取消上传

**请求:**
```http
DELETE /api/files/upload/{upload_id} HTTP/1.1
Authorization: Bearer {token}
```

**响应:**
```json
{
  "success": true,
  "message": "Upload cancelled"
}
```

---

### 3.5 完整分片上传示例

```javascript
const CHUNK_SIZE = 10 * 1024 * 1024; // 10MB

async function uploadLargeFile(file, targetPath, onProgress) {
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
  
  // 1. 初始化上传
  const initRes = await fetch('/api/files/init-upload', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
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
    const end = Math.min(start + CHUNK_SIZE, file.size);
    const chunk = file.slice(start, end);
    
    const formData = new FormData();
    formData.append('upload_id', upload_id);
    formData.append('chunk_index', i);
    formData.append('chunk', chunk);
    
    const chunkRes = await fetch('/api/files/upload-chunk', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData
    });
    
    if (!chunkRes.ok) {
      // 上传失败，取消
      await fetch(`/api/files/upload/${upload_id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      throw new Error(`Chunk ${i} upload failed`);
    }
    
    // 更新进度
    onProgress?.({
      uploaded: i + 1,
      total: totalChunks,
      percent: Math.round((i + 1) / totalChunks * 100)
    });
  }
  
  // 3. 完成上传
  const completeRes = await fetch('/api/files/complete-upload', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      upload_id,
      target_path: targetPath
    })
  });
  
  const result = await completeRes.json();
  return result.path;
}

// 使用示例
async function handleLargeFileUpload(file) {
  try {
    const path = await uploadLargeFile(
      file,
      `uploads/${file.name}`,
      (progress) => {
        console.log(`Progress: ${progress.percent}%`);
        document.getElementById('progress').value = progress.percent;
      }
    );
    console.log('Upload complete:', path);
  } catch (error) {
    console.error('Upload failed:', error);
  }
}
```

---

## 四、使用 webdav.js 库（推荐）

安装:
```bash
npm install webdav
```

### 4.1 初始化客户端

```javascript
import { createClient } from 'webdav';

const client = createClient('http://your-server:8006/dav', {
  headers: {
    Authorization: `Bearer ${token}`
  }
});
```

### 4.2 常用操作

```javascript
// 列目录
async function listFiles(path = '/') {
  const items = await client.getDirectoryContents(path);
  return items.map(item => ({
    name: item.basename,
    type: item.type,  // 'file' or 'directory'
    size: item.size,
    modified: item.lastmod,
    path: item.filename
  }));
}

// 创建目录
await client.createDirectory('/new-folder');

// 上传文件（小文件）
const content = await file.arrayBuffer();
await client.putFileContents(`/uploads/${file.name}`, content);

// 下载文件
const content = await client.getFileContents('/document.pdf');
const blob = new Blob([content]);

// 删除
await client.deleteFile('/old-file.txt');

// 移动/重命名
await client.moveFile('/old-name.txt', '/new-name.txt');

// 检查文件是否存在
const exists = await client.exists('/some-file.txt');
```

### 4.3 大文件分片上传

由于 webdav.js 不直接支持分片上传，大文件建议使用本项目的 `/api/files/*` 接口。

---

## 五、错误处理

### HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 204 | 删除成功（无内容） |
| 207 | Multi-Status（WebDAV 专用） |
| 400 | 请求参数错误 |
| 401 | 未认证（Token 无效或过期） |
| 403 | 禁止访问（路径穿越等） |
| 404 | 资源不存在 |
| 405 | 方法不允许（如目录已存在） |
| 409 | 冲突（ETag 不匹配） |
| 422 | 请求格式错误 |

### 错误响应格式

```json
{
  "detail": "Error message"
}
```

### 统一错误处理示例

```javascript
class APIError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Authorization': `Bearer ${token}`,
      ...options.headers
    }
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new APIError(response.status, error.detail);
  }
  
  return response;
}

// 使用
try {
  await request('/dav/documents/', { method: 'MKCOL' });
} catch (error) {
  if (error instanceof APIError) {
    if (error.status === 401) {
      // Token 过期，重新登录
      await relogin();
    } else if (error.status === 403) {
      alert('无权访问此资源');
    } else {
      alert(`操作失败: ${error.message}`);
    }
  }
}
```

---

## 六、完整示例：文件管理器组件

```jsx
import React, { useState, useEffect } from 'react';
import { createClient } from 'webdav';

function FileManager({ token }) {
  const [client] = useState(() => createClient('/dav', {
    headers: { Authorization: `Bearer ${token}` }
  }));
  const [items, setItems] = useState([]);
  const [currentPath, setCurrentPath] = useState('/');
  const [loading, setLoading] = useState(false);

  // 加载目录
  const loadDirectory = async (path) => {
    setLoading(true);
    try {
      const contents = await client.getDirectoryContents(path);
      setItems(contents);
      setCurrentPath(path);
    } catch (error) {
      console.error('Failed to load directory:', error);
    } finally {
      setLoading(false);
    }
  };

  // 初始加载
  useEffect(() => {
    loadDirectory('/');
  }, []);

  // 进入目录
  const enterDirectory = (item) => {
    if (item.type === 'directory') {
      loadDirectory(item.filename);
    }
  };

  // 上传文件
  const uploadFile = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    try {
      const content = await file.arrayBuffer();
      await client.putFileContents(`${currentPath}${file.name}`, content);
      loadDirectory(currentPath); // 刷新
    } catch (error) {
      console.error('Upload failed:', error);
    }
  };

  // 删除
  const deleteItem = async (item) => {
    if (!confirm(`确定删除 ${item.basename}?`)) return;

    try {
      await client.deleteFile(item.filename);
      loadDirectory(currentPath); // 刷新
    } catch (error) {
      console.error('Delete failed:', error);
    }
  };

  // 下载
  const downloadItem = async (item) => {
    const content = await client.getFileContents(item.filename);
    const blob = new Blob([content]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = item.basename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="file-manager">
      <div className="toolbar">
        <button onClick={() => loadDirectory('/')}>根目录</button>
        <input type="file" onChange={uploadFile} />
      </div>

      <div className="breadcrumb">{currentPath}</div>

      {loading ? (
        <div>加载中...</div>
      ) : (
        <ul className="file-list">
          {items.map(item => (
            <li key={item.filename}>
              <span onClick={() => enterDirectory(item)}>
                {item.type === 'directory' ? '📁' : '📄'} {item.basename}
              </span>
              {item.type === 'file' && (
                <>
                  <button onClick={() => downloadItem(item)}>下载</button>
                  <button onClick={() => deleteItem(item)}>删除</button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default FileManager;
```

---

## 七、注意事项

1. **认证**: 所有请求必须携带有效的 JWT Token
2. **路径隔离**: 用户只能访问自己的 workspace，尝试访问他人目录返回 403
3. **路径穿越**: `../` 等路径穿越攻击会被阻止
4. **分片大小**: 建议使用 10MB 分片，与后端保持一致
5. **临时文件**: 未完成的分片上传会在 24 小时后自动清理
6. **ETag**: 用于乐观锁，防止并发覆盖
7. **编码**: 文件名统一使用 UTF-8
