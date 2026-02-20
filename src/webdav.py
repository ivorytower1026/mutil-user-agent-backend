"""WebDAV handler implementation using Daytona FS API."""
from datetime import datetime
from xml.etree import ElementTree as ET
from urllib.parse import quote
from io import BytesIO

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

from src.daytona_sandbox_manager import get_sandbox_manager


class WebDAVHandler:
    """WebDAV protocol handler using Daytona FS API."""
    
    WEBDAV_NS = "{DAV:}"
    
    def __init__(self):
        self._sandbox_manager = get_sandbox_manager()
    
    def _get_sandbox(self, user_id: str):
        """获取用户的 Files Sandbox"""
        return self._sandbox_manager.get_files_backend(user_id)
    
    def _format_datetime(self, dt: datetime) -> str:
        """Format datetime for WebDAV responses (RFC 1123)."""
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    def _build_propfind_xml(self, user_id: str, path: str, files: list) -> str:
        """Build PROPFIND response XML."""
        ET.register_namespace('D', 'DAV:')
        
        multistatus = ET.Element(f"{self.WEBDAV_NS}multistatus")
        
        for file_info in files:
            self._add_response_element(multistatus, user_id, path, file_info)
        
        return self._xml_to_string(multistatus)
    
    def _add_response_element(self, parent: ET.Element, user_id: str, base_path: str, file_info: dict):
        """Add a response element to the multistatus XML."""
        response = ET.SubElement(parent, f"{self.WEBDAV_NS}response")
        
        href = ET.SubElement(response, f"{self.WEBDAV_NS}href")
        name = file_info.get('name', 'unknown')
        is_dir = file_info.get('is_dir', False)
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
        getlastmodified.text = self._format_datetime(datetime.now())
        
        if not is_dir:
            getcontentlength = ET.SubElement(prop, f"{self.WEBDAV_NS}getcontentlength")
            getcontentlength.text = str(file_info.get('size', 0))
        
        status = ET.SubElement(propstat, f"{self.WEBDAV_NS}status")
        status.text = "HTTP/1.1 200 OK"
    
    def _xml_to_string(self, element: ET.Element) -> str:
        """Convert XML element to string with declaration."""
        return '<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(
            element, encoding='unicode'
        )
    
    async def propfind(self, user_id: str, path: str, depth: int = 1) -> Response:
        """PROPFIND - List directory or get file properties."""
        sandbox = self._get_sandbox(user_id)
        files = sandbox.fs_list(path)
        xml = self._build_propfind_xml(user_id, path, files)
        return Response(
            content=xml,
            media_type="application/xml; charset=utf-8",
            status_code=207,
            headers={"DAV": "1"}
        )
    
    async def get(self, user_id: str, path: str) -> StreamingResponse:
        """GET - Download file."""
        sandbox = self._get_sandbox(user_id)
        try:
            content = sandbox.fs_download(path)
        except Exception:
            raise HTTPException(status_code=404, detail="Not found or not a file")
        
        def iter_content():
            yield content
        
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
    
    async def put(
        self,
        user_id: str,
        path: str,
        body: bytes,
        if_match: str | None = None
    ) -> Response:
        """PUT - Upload file with ETag support."""
        sandbox = self._get_sandbox(user_id)
        
        if if_match is not None:
            current_etag = sandbox.fs_get_etag(path)
            if current_etag is None:
                raise HTTPException(status_code=404, detail="File not found for ETag check")
            if current_etag != if_match:
                raise HTTPException(status_code=409, detail="ETag mismatch - file was modified")
        
        etag = sandbox.fs_upload(path, body)
        return Response(status_code=201, headers={"ETag": etag})
    
    async def mkcol(self, user_id: str, path: str) -> Response:
        """MKCOL - Create directory."""
        sandbox = self._get_sandbox(user_id)
        sandbox.execute(f"mkdir -p /home/daytona/{path}")
        return Response(status_code=201)
    
    async def delete(self, user_id: str, path: str) -> Response:
        """DELETE - Remove file or directory."""
        sandbox = self._get_sandbox(user_id)
        try:
            sandbox.fs_delete(path)
        except Exception:
            raise HTTPException(status_code=404, detail="Not found")
        return Response(status_code=204)
    
    async def move(self, user_id: str, src: str, dst: str) -> Response:
        """MOVE - Move or rename file/directory."""
        sandbox = self._get_sandbox(user_id)
        result = sandbox.execute(f"mv /home/daytona/{src} /home/daytona/{dst}")
        if result.exit_code != 0:
            raise HTTPException(status_code=404, detail="Source not found")
        return Response(status_code=201)
