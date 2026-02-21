"""WebDAV 处理器 - 操作本地文件系统"""
import shutil
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

from src.config import settings
from src.utils.get_logger import get_logger

logger = get_logger("webdav")


class WebDAVHandler:
    """WebDAV 协议处理器 - 本地文件系统"""
    
    WEBDAV_NS = "{DAV:}"
    
    def __init__(self):
        self._base_dir = Path(settings.WORKSPACE_ROOT)
    
    def _get_user_dir(self, user_id: str) -> Path:
        return self._base_dir / user_id
    
    def _get_path(self, user_id: str, path: str) -> Path:
        return self._get_user_dir(user_id) / path
    
    def _format_datetime(self, dt: datetime) -> str:
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    def _build_propfind_xml(self, user_id: str, path: str, files: list) -> str:
        ET.register_namespace('D', 'DAV:')
        multistatus = ET.Element(f"{self.WEBDAV_NS}multistatus")
        
        for file_info in files:
            self._add_response_element(multistatus, user_id, path, file_info)
        
        return '<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(
            multistatus, encoding='unicode'
        )
    
    def _add_response_element(self, parent, user_id: str, base_path: str, file_info: dict):
        response = ET.SubElement(parent, f"{self.WEBDAV_NS}response")
        
        href = ET.SubElement(response, f"{self.WEBDAV_NS}href")
        name = file_info["name"]
        is_dir = file_info["is_dir"]
        href_path = f"/dav/{user_id}/{base_path}/{name}".replace("//", "/")
        if is_dir and not href_path.endswith('/'):
            href_path += '/'
        href.text = href_path
        
        propstat = ET.SubElement(response, f"{self.WEBDAV_NS}propstat")
        prop = ET.SubElement(propstat, f"{self.WEBDAV_NS}prop")
        
        displayname = ET.SubElement(prop, f"{self.WEBDAV_NS}displayname")
        displayname.text = name
        
        resourcetype = ET.SubElement(prop, f"{self.WEBDAV_NS}resourcetype")
        if is_dir:
            ET.SubElement(resourcetype, f"{self.WEBDAV_NS}collection")
        
        getlastmodified = ET.SubElement(prop, f"{self.WEBDAV_NS}getlastmodified")
        getlastmodified.text = self._format_datetime(file_info.get("mtime", datetime.now()))
        
        if not is_dir:
            getcontentlength = ET.SubElement(prop, f"{self.WEBDAV_NS}getcontentlength")
            getcontentlength.text = str(file_info.get("size", 0))
        
        status = ET.SubElement(propstat, f"{self.WEBDAV_NS}status")
        status.text = "HTTP/1.1 200 OK"
    
    async def propfind(self, user_id: str, path: str, depth: int = 1) -> Response:
        """PROPFIND - 列出目录"""
        dir_path = self._get_path(user_id, path)
        
        files = []
        if dir_path.exists() and dir_path.is_dir():
            for item in dir_path.iterdir():
                stat = item.stat()
                files.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "size": stat.st_size if item.is_file() else 0,
                    "mtime": datetime.fromtimestamp(stat.st_mtime)
                })
        
        xml = self._build_propfind_xml(user_id, path, files)
        return Response(
            content=xml,
            media_type="application/xml; charset=utf-8",
            status_code=207,
            headers={"DAV": "1"}
        )
    
    async def get(self, user_id: str, path: str) -> StreamingResponse:
        """GET - 下载文件"""
        file_path = self._get_path(user_id, path)
        
        if not file_path.exists() or file_path.is_dir():
            raise HTTPException(status_code=404, detail="Not found")
        
        def iter_content():
            yield file_path.read_bytes()
        
        filename = path.split('/')[-1]
        filename_ascii = filename.encode('ascii', 'replace').decode('ascii')
        filename_utf8 = quote(filename, safe='')
        
        return StreamingResponse(
            iter_content(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{filename_utf8}"
            }
        )
    
    async def put(self, user_id: str, path: str, body: bytes, thread_id: str | None = None) -> Response:
        """PUT - 上传文件"""
        file_path = self._get_path(user_id, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(body)
        
        logger.info(f"[WebDAV] PUT {path} ({len(body)} bytes)")
        
        if thread_id:
            try:
                from src.workspace_sync import get_sync_service
                get_sync_service().on_local_file_change(user_id, thread_id, path, body)
            except Exception as e:
                logger.warning(f"[WebDAV] Sync failed: {e}")
        
        return Response(status_code=201)
    
    async def mkcol(self, user_id: str, path: str) -> Response:
        """MKCOL - 创建目录"""
        dir_path = self._get_path(user_id, path)
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"[WebDAV] MKCOL {path}")
        return Response(status_code=201)
    
    async def delete(self, user_id: str, path: str, thread_id: str | None = None) -> Response:
        """DELETE - 删除文件或目录"""
        file_path = self._get_path(user_id, path)
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Not found")
        
        if file_path.is_dir():
            shutil.rmtree(file_path)
        else:
            file_path.unlink()
        
        logger.info(f"[WebDAV] DELETE {path}")
        
        if thread_id:
            try:
                from src.workspace_sync import get_sync_service
                get_sync_service().on_local_file_delete(user_id, thread_id, path)
            except Exception as e:
                logger.warning(f"[WebDAV] Sync delete failed: {e}")
        
        return Response(status_code=204)
    
    async def move(self, user_id: str, src: str, dst: str) -> Response:
        """MOVE - 移动或重命名"""
        src_path = self._get_path(user_id, src)
        dst_path = self._get_path(user_id, dst)
        
        if not src_path.exists():
            raise HTTPException(status_code=404, detail="Source not found")
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        src_path.rename(dst_path)
        
        logger.info(f"[WebDAV] MOVE {src} -> {dst}")
        return Response(status_code=201)
