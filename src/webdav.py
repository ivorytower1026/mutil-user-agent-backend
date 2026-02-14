"""WebDAV handler implementation for file operations."""
from pathlib import Path
from datetime import datetime
from xml.etree import ElementTree as ET
import shutil

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse


class WebDAVHandler:
    """WebDAV protocol handler for file operations.
    
    Implements PROPFIND, GET, PUT, MKCOL, DELETE, MOVE methods.
    """
    
    WEBDAV_NS = "{DAV:}"
    
    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root)
    
    def _user_path(self, user_id: str, rel_path: str) -> Path:
        """Safely resolve path within user's workspace.
        
        Prevents path traversal attacks by ensuring the resolved path
        stays within the user's directory.
        
        Args:
            user_id: The user ID
            rel_path: Relative path within user's workspace
            
        Returns:
            Resolved absolute path
            
        Raises:
            HTTPException: 403 if path escapes user directory
        """
        base = (self.root / user_id).resolve()
        target = (base / rel_path.lstrip('/')).resolve()
        if not str(target).startswith(str(base)):
            raise HTTPException(status_code=403, detail="Access denied")
        return target
    
    def _etag(self, path: Path) -> str:
        """Generate ETag based on file mtime and size.
        
        Args:
            path: File path
            
        Returns:
            ETag string in format "{mtime_ns}-{size}"
        """
        stat = path.stat()
        return f'"{stat.st_mtime_ns}-{stat.st_size}"'
    
    def _format_datetime(self, dt: datetime) -> str:
        """Format datetime for WebDAV responses (RFC 1123).
        
        Args:
            dt: Datetime object
            
        Returns:
            Formatted string like "Wed, 14 Feb 2026 10:00:00 GMT"
        """
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    def _build_propfind_xml(self, user_id: str, target: Path, depth: int) -> str:
        """Build PROPFIND response XML.
        
        Args:
            user_id: User ID for building href
            target: Target path (file or directory)
            depth: 0 for self only, 1 for self + children
            
        Returns:
            XML string in WebDAV multistatus format
        """
        ET.register_namespace('D', 'DAV:')
        
        multistatus = ET.Element(f"{self.WEBDAV_NS}multistatus")
        
        if target.is_file():
            self._add_response_element(multistatus, user_id, target)
        elif target.is_dir():
            self._add_response_element(multistatus, user_id, target, is_dir=True)
            if depth >= 1:
                for item in sorted(target.iterdir()):
                    is_dir = item.is_dir()
                    self._add_response_element(multistatus, user_id, item, is_dir=is_dir)
        
        return self._xml_to_string(multistatus)
    
    def _add_response_element(self, parent: ET.Element, user_id: str, path: Path, is_dir: bool = False):
        """Add a response element to the multistatus XML.
        
        Args:
            parent: Parent XML element
            user_id: User ID for building href
            path: File/directory path
            is_dir: Whether this is a directory
        """
        response = ET.SubElement(parent, f"{self.WEBDAV_NS}response")
        
        href = ET.SubElement(response, f"{self.WEBDAV_NS}href")
        rel_path = path.relative_to(self.root / user_id)
        href_path = f"/dav/{user_id}/{rel_path}".replace("\\", "/")
        if is_dir and not href_path.endswith('/'):
            href_path += '/'
        href.text = href_path
        
        propstat = ET.SubElement(response, f"{self.WEBDAV_NS}propstat")
        prop = ET.SubElement(propstat, f"{self.WEBDAV_NS}prop")
        
        displayname = ET.SubElement(prop, f"{self.WEBDAV_NS}displayname")
        displayname.text = path.name
        
        resourcetype = ET.SubElement(prop, f"{self.WEBDAV_NS}resourcetype")
        if is_dir:
            ET.SubElement(resourcetype, f"{self.WEBDAV_NS}collection")
        
        getlastmodified = ET.SubElement(prop, f"{self.WEBDAV_NS}getlastmodified")
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        getlastmodified.text = self._format_datetime(mtime)
        
        if not is_dir:
            getcontentlength = ET.SubElement(prop, f"{self.WEBDAV_NS}getcontentlength")
            getcontentlength.text = str(path.stat().st_size)
            
            getetag = ET.SubElement(prop, f"{self.WEBDAV_NS}getetag")
            getetag.text = self._etag(path)
        
        status = ET.SubElement(propstat, f"{self.WEBDAV_NS}status")
        status.text = "HTTP/1.1 200 OK"
    
    def _xml_to_string(self, element: ET.Element) -> str:
        """Convert XML element to string with declaration.
        
        Args:
            element: Root XML element
            
        Returns:
            XML string with declaration
        """
        return '<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(
            element, encoding='unicode'
        )
    
    async def propfind(self, user_id: str, path: str, depth: int = 1) -> Response:
        """PROPFIND - List directory or get file properties.
        
        Args:
            user_id: User ID
            path: Relative path within workspace
            depth: 0 for self only, 1 for self + children
            
        Returns:
            207 Multi-Status response with XML
        """
        target = self._user_path(user_id, path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Not found")
        
        xml = self._build_propfind_xml(user_id, target, depth)
        return Response(
            content=xml,
            media_type="application/xml; charset=utf-8",
            status_code=207,
            headers={"DAV": "1"}
        )
    
    async def get(self, user_id: str, path: str) -> StreamingResponse:
        """GET - Download file.
        
        Args:
            user_id: User ID
            path: Relative path to file
            
        Returns:
            StreamingResponse with file content
        """
        target = self._user_path(user_id, path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Not found or not a file")
        
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
        """PUT - Upload file.
        
        Args:
            user_id: User ID
            path: Relative path for the file
            body: File content bytes
            if_match: Optional ETag for conflict detection
            
        Returns:
            201 Created response with ETag
        """
        target = self._user_path(user_id, path)
        
        if target.exists() and if_match:
            if self._etag(target) != if_match:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "conflict", "message": "File has been modified"}
                )
        
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        
        return Response(
            status_code=201,
            headers={"ETag": self._etag(target)}
        )
    
    async def mkcol(self, user_id: str, path: str) -> Response:
        """MKCOL - Create directory.
        
        Args:
            user_id: User ID
            path: Relative path for the directory
            
        Returns:
            201 Created or 405 if exists
        """
        target = self._user_path(user_id, path)
        if target.exists():
            raise HTTPException(status_code=405, detail="Already exists")
        target.mkdir(parents=True, exist_ok=True)
        return Response(status_code=201)
    
    async def delete(self, user_id: str, path: str) -> Response:
        """DELETE - Remove file or directory.
        
        Args:
            user_id: User ID
            path: Relative path to delete
            
        Returns:
            204 No Content
        """
        target = self._user_path(user_id, path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Not found")
        
        if target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        
        return Response(status_code=204)
    
    async def move(self, user_id: str, src: str, dst: str) -> Response:
        """MOVE - Move or rename file/directory.
        
        Args:
            user_id: User ID
            src: Source relative path
            dst: Destination relative path
            
        Returns:
            201 Created
        """
        src_path = self._user_path(user_id, src)
        dst_path = self._user_path(user_id, dst)
        
        if not src_path.exists():
            raise HTTPException(status_code=404, detail="Source not found")
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        src_path.rename(dst_path)
        
        return Response(status_code=201)
