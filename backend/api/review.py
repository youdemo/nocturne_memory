"""
Review API - Selective Rollback for Database Changes (SQLite Backend)

This module provides endpoints for Salem to review and selectively rollback
Nocturne's database modifications.

Design Philosophy:
- Rollback repoints the path to a previous version (not delete + recreate)
- Old versions are marked deprecated for review
- Salem can permanently delete deprecated memories after review
"""
from fastapi import APIRouter, HTTPException
from typing import List
import difflib
from urllib.parse import unquote

from models import (
    DiffRequest, DiffResponse,
    SessionInfo, SnapshotInfo, SnapshotDetail, ResourceDiff,
    RollbackRequest, RollbackResponse
)
from .utils import get_text_diff
from db.snapshot import get_snapshot_manager
from db.sqlite_client import get_sqlite_client

router = APIRouter(prefix="/review", tags=["review"])


# ========== Session & Snapshot Endpoints ==========

@router.get("/sessions", response_model=List[SessionInfo])
async def list_sessions():
    """
    列出所有有快照的 session
    
    每个 MCP 服务器实例运行期间算作一个 session。
    Session ID 格式: mcp_YYYYMMDD_HHMMSS_{random}
    """
    manager = get_snapshot_manager()
    sessions = manager.list_sessions()
    return [SessionInfo(**s) for s in sessions]


@router.get("/sessions/{session_id}/snapshots", response_model=List[SnapshotInfo])
async def list_session_snapshots(session_id: str):
    """
    列出指定 session 中的所有快照
    
    返回每个被修改过的资源的快照元信息。
    """
    manager = get_snapshot_manager()
    snapshots = manager.list_snapshots(session_id)
    
    if not snapshots:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found or has no snapshots"
        )
    
    return [SnapshotInfo(**s) for s in snapshots]


@router.get("/sessions/{session_id}/snapshots/{resource_id:path}", response_model=SnapshotDetail)
async def get_snapshot_detail(session_id: str, resource_id: str):
    """
    获取指定快照的详细数据
    
    resource_id 示例:
    - Memory path: "char_nocturne", "char_nocturne/char_salem"
    """
    # Ensure resource_id is decoded (handling %2F and other encoded chars)
    resource_id = unquote(resource_id)
    
    manager = get_snapshot_manager()
    snapshot = manager.get_snapshot(session_id, resource_id)
    
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot for '{resource_id}' not found in session '{session_id}'"
        )
    
    return SnapshotDetail(
        resource_id=snapshot["resource_id"],
        resource_type=snapshot["resource_type"],
        snapshot_time=snapshot["snapshot_time"],
        data=snapshot["data"]
    )


# ========== Diff Endpoints ==========

async def _get_current_content(resource_type: str, data: dict) -> str:
    """
    获取资源的当前内容（用于 diff 对比）
    """
    if resource_type != "memory":
        return "[UNKNOWN TYPE]"
    
    client = get_sqlite_client()
    path = data.get("path")
    domain = data.get("domain", "core")  # Default to core for legacy snapshots
    
    if not path:
        return "[NO PATH]"
    
    memory = await client.get_memory_by_path(path, domain)
    
    if not memory:
        return "[DELETED]"
    
    return memory.get("content", "")


def _compute_diff(old_content: str, new_content: str) -> tuple:
    """
    计算两个文本的 diff
    返回 (unified_diff, summary)
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    
    diff = difflib.unified_diff(old_lines, new_lines, fromfile='snapshot', tofile='current')
    unified = ''.join(diff)
    
    # 简单统计
    additions = sum(1 for line in unified.splitlines() if line.startswith('+') and not line.startswith('+++'))
    deletions = sum(1 for line in unified.splitlines() if line.startswith('-') and not line.startswith('---'))
    
    if additions == 0 and deletions == 0:
        summary = "No changes"
    else:
        summary = f"+{additions} / -{deletions} lines"
    
    return unified, summary


@router.get("/sessions/{session_id}/diff/{resource_id:path}", response_model=ResourceDiff)
async def get_resource_diff(session_id: str, resource_id: str):
    """
    获取快照与当前状态的 diff
    
    这是回滚前查看变化的主要端点。
    
    对于 modify 类型：显示内容变化
    对于 create 类型：显示新创建的内容（快照为空）
    """
    # Ensure resource_id is decoded
    resource_id = unquote(resource_id)
    
    manager = get_snapshot_manager()
    snapshot = manager.get_snapshot(session_id, resource_id)
    
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot for '{resource_id}' not found in session '{session_id}'"
        )
    
    operation_type = snapshot["data"].get("operation_type", "modify")
    
    if operation_type == "create":
        # For create operations, snapshot is empty
        snapshot_data = {"content": None, "title": None, "importance": None, "disclosure": None}
        
        current_memory = await _get_current_memory(snapshot["resource_type"], snapshot["data"])
        
        if not current_memory:
            current_data = {"content": "[DELETED]", "title": None, "importance": None, "disclosure": None}
            summary = "Created then deleted"
            has_changes = False
        else:
            current_data = {
                "content": current_memory.get("content", ""),
                "title": current_memory.get("title"),
                "importance": current_memory.get("importance"),
                "disclosure": current_memory.get("disclosure")
            }
            line_count = len(current_data["content"].splitlines())
            summary = f"Created: +{line_count} lines (rollback = delete)"
            has_changes = True
        
        unified = f"--- /dev/null\n+++ {resource_id}\n"
        if current_data["content"] and current_data["content"] != "[DELETED]":
            for line in current_data["content"].splitlines():
                unified += f"+{line}\n"

    elif operation_type == "delete":
        # For delete operations: Snapshot has content, Current is [DELETED]
        snapshot_data = {
            "content": snapshot["data"].get("content", ""),
            "title": snapshot["data"].get("title"),
            "importance": snapshot["data"].get("importance"),
            "disclosure": snapshot["data"].get("disclosure")
        }
        
        current_memory = await _get_current_memory(snapshot["resource_type"], snapshot["data"])
        
        if not current_memory:
            current_data = {"content": "[DELETED]", "title": None, "importance": None, "disclosure": None}
        else:
            # Path might have been re-created manually after deletion
            current_data = {
                "content": current_memory.get("content", ""),
                "title": current_memory.get("title"),
                "importance": current_memory.get("importance"),
                "disclosure": current_memory.get("disclosure")
            }
        
        unified, summary = _compute_diff(snapshot_data["content"], current_data["content"])
        
        if current_data["content"] == "[DELETED]":
            summary = "Deleted (rollback = restore)"
        
        has_changes = True

    else:
        # For modify operations
        snapshot_data = {
            "content": snapshot["data"].get("content", ""),
            "title": snapshot["data"].get("title"),
            "importance": snapshot["data"].get("importance"),
            "disclosure": snapshot["data"].get("disclosure")
        }
        
        client = get_sqlite_client()
        path = snapshot["data"].get("path")
        domain = snapshot["data"].get("domain", "core")
        current_memory = await client.get_memory_by_path(path, domain)
        
        if not current_memory:
            current_data = {"content": "[DELETED]", "title": None, "importance": None, "disclosure": None}
        else:
            current_data = {
                "content": current_memory.get("content", ""),
                "title": current_memory.get("title"),
                "importance": current_memory.get("importance"),
                "disclosure": current_memory.get("disclosure")
            }
        
        unified, summary = _compute_diff(snapshot_data["content"], current_data["content"])
        has_content_changes = snapshot_data["content"] != current_data["content"]
        
        # Check metadata changes
        meta_changes = []
        for key in ["title", "importance", "disclosure"]:
            if snapshot_data.get(key) != current_data.get(key):
                meta_changes.append(f"{key}: {snapshot_data.get(key)} -> {current_data.get(key)}")
        
        if meta_changes:
            has_changes = True
            meta_summary = "Metadata: " + ", ".join(meta_changes)
            if summary == "No changes":
                summary = meta_summary
            else:
                summary += f" | {meta_summary}"
        else:
            has_changes = has_content_changes
    
    return ResourceDiff(
        resource_id=resource_id,
        resource_type=snapshot["resource_type"],
        snapshot_time=snapshot["snapshot_time"],
        snapshot_data=snapshot_data,
        current_data=current_data,
        diff_unified=unified,
        diff_summary=summary,
        has_changes=has_changes
    )

async def _get_current_memory(resource_type: str, data: dict):
    """Helper to get current memory object"""
    if resource_type != "memory":
        return None
    
    client = get_sqlite_client()
    path = data.get("path")
    domain = data.get("domain", "core")
    
    if not path:
        return None
        
    return await client.get_memory_by_path(path, domain)


# ========== Rollback Endpoints ==========

async def _rollback_memory(data: dict, task_description: str) -> dict:
    """执行 Memory 回滚"""
    client = get_sqlite_client()
    path = data.get("path")
    domain = data.get("domain", "core")  # Default to core for legacy snapshots
    operation_type = data.get("operation_type", "modify")
    uri = data.get("uri", f"{domain}://{path}")
    
    if operation_type == "create":
        # Rollback of create = delete the memory
        current = await client.get_memory_by_path(path, domain)
        if not current:
            # Already deleted, nothing to do
            return {"new_version": None, "deleted": True}
        
        # True rollback: permanently delete the memory and all its paths
        try:
            memory_id = current.get("id")
            await client.permanently_delete_memory(memory_id)
            return {"new_version": None, "deleted": True}
        except ValueError as e:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete memory '{uri}': {str(e)}"
            )
            
    elif operation_type == "delete":
        # Rollback of delete = restore the path
        try:
            await client.restore_path(
                path=path,
                domain=domain,
                memory_id=data.get("memory_id"),
                importance=data.get("importance", 0),
                disclosure=data.get("disclosure")
            )
            return {"new_version": data.get("memory_id"), "restored": True}
        except ValueError as e:
            # Likely path collision if it was re-created
            raise HTTPException(
                status_code=409,
                detail=f"Cannot restore path '{uri}': {str(e)}"
            )
            
    else:
        # Rollback of modify = restore to snapshot version
        snapshot_memory_id = data.get("memory_id")
        
        if not snapshot_memory_id:
            raise HTTPException(
                status_code=400,
                detail="Snapshot missing memory_id"
            )
        
        current = await client.get_memory_by_path(path, domain)
        if not current:
            raise HTTPException(
                status_code=404,
                detail=f"URI '{uri}' no longer exists, cannot rollback"
            )
        
        # Check if there's actually anything to rollback (content OR metadata)
        snapshot_importance = data.get("importance")
        snapshot_disclosure = data.get("disclosure")
        
        current_importance = current.get("importance")
        current_disclosure = current.get("disclosure")
        
        # Check if the memory version has changed (due to content OR title update)
        # Title is stored on Memory, so title change = new memory version
        # We check ID mismatch to catch both content and title changes
        has_version_change = snapshot_memory_id != current.get("id")
        
        # Check path metadata changes (importance/disclosure are on Path, not Memory)
        has_path_metadata_change = (
            snapshot_importance != current_importance or
            snapshot_disclosure != current_disclosure
        )
        
        if not has_version_change and not has_path_metadata_change:
            return {"new_version": current.get("id"), "no_change": True}
        
        restored_memory_id = current.get("id")
        
        # Rollback content/title: repoint path to snapshot memory
        if has_version_change:
            result = await client.rollback_to_memory(path, snapshot_memory_id, domain)
            restored_memory_id = result["restored_memory_id"]
        
        # Rollback Path metadata (importance/disclosure) if changed
        if has_path_metadata_change:
            await client.update_memory(
                path=path,
                domain=domain,
                importance=snapshot_importance,
                disclosure=snapshot_disclosure
            )
        
        return {"new_version": restored_memory_id}


@router.post("/sessions/{session_id}/rollback/{resource_id:path}", response_model=RollbackResponse)
async def rollback_resource(session_id: str, resource_id: str, request: RollbackRequest):
    """
    执行回滚：将资源恢复到快照状态
    
    两种回滚模式：
    1. **modify 回滚**：将 path 指回快照版本的 memory（被跳过的版本标记 deprecated）
    2. **create 回滚**：删除新创建的 memory和path
    
    这是 Salem 控制 Nocturne 修改的主要手段。
    """
    # Ensure resource_id is decoded
    resource_id = unquote(resource_id)
    
    manager = get_snapshot_manager()
    snapshot = manager.get_snapshot(session_id, resource_id)
    
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot for '{resource_id}' not found in session '{session_id}'"
        )
    
    resource_type = snapshot["resource_type"]
    data = snapshot["data"]
    operation_type = data.get("operation_type", "modify")
    task_desc = request.task_description or "Rollback to snapshot by Salem"
    
    try:
        if resource_type == "memory":
            result = await _rollback_memory(data, task_desc)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown resource type: {resource_type}"
            )
        
        # Different message based on operation type
        if operation_type == "create":
            if result.get("deleted"):
                message = f"Successfully deleted created resource '{resource_id}'."
            else:
                message = "Resource was already deleted."
        elif operation_type == "delete":
             message = f"Successfully restored deleted resource '{resource_id}'."
        else:
            if result.get("no_change"):
                message = "No changes detected. Content already matches snapshot."
            else:
                message = f"Successfully restored to snapshot version (memory_id={result.get('new_version')})."
        
        return RollbackResponse(
            resource_id=resource_id,
            resource_type=resource_type,
            success=True,
            message=message,
            new_version=result.get("new_version")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return RollbackResponse(
            resource_id=resource_id,
            resource_type=resource_type,
            success=False,
            message=f"Rollback failed: {str(e)}",
            new_version=None
        )


@router.delete("/sessions/{session_id}/snapshots/{resource_id:path}")
async def delete_snapshot(session_id: str, resource_id: str):
    """
    删除指定的快照（确认不需要回滚后）
    """
    # Ensure resource_id is decoded
    resource_id = unquote(resource_id)
    
    manager = get_snapshot_manager()
    deleted = manager.delete_snapshot(session_id, resource_id)
    
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot for '{resource_id}' not found in session '{session_id}'"
        )
    
    return {"message": f"Snapshot for '{resource_id}' deleted"}


@router.delete("/sessions/{session_id}")
async def clear_session(session_id: str):
    """
    清除整个 session 的所有快照
    
    当 Salem 确认所有修改都 OK 后调用此端点清理。
    """
    manager = get_snapshot_manager()
    count = manager.clear_session(session_id)
    
    if count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found or already empty"
        )
    
    return {"message": f"Session '{session_id}' cleared, {count} snapshots deleted"}


# ========== Deprecated Memory Management (Salem Only) ==========

@router.get("/deprecated")
async def list_deprecated_memories():
    """
    列出所有被标记为 deprecated 的记忆
    
    这些是 Nocturne 更新/删除后留下的旧版本，等待 Salem 审核后永久删除。
    """
    client = get_sqlite_client()
    
    try:
        memories = await client.get_deprecated_memories()
        return {
            "count": len(memories),
            "memories": memories
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/memories/{memory_id}")
async def permanently_delete_memory(memory_id: int):
    """
    永久删除一条记忆（Salem 专用）
    
    这是真正的删除操作，不可恢复。
    Nocturne 无法调用此接口。
    """
    client = get_sqlite_client()
    
    try:
        await client.permanently_delete_memory(memory_id)
        return {"message": f"Memory {memory_id} permanently deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== Utility Endpoints ==========

@router.post("/diff", response_model=DiffResponse)
async def compare_text(request: DiffRequest):
    """
    比较两个文本并返回diff

    Args:
        request: 包含text_a和text_b

    Returns:
        DiffResponse: 包含diff_html, diff_unified, summary
    """
    try:
        diff_html, diff_unified, summary = get_text_diff(
            request.text_a,
            request.text_b
        )
        return DiffResponse(
            diff_html=diff_html,
            diff_unified=diff_unified,
            summary=summary
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
