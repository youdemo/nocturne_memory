"""
Browse API - Clean URI-based memory navigation

This replaces the old Entity/Relation/Chapter conceptual split with a simple
hierarchical browser. Every path is just a node with content and children.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from db import get_sqlite_client

router = APIRouter(prefix="/browse", tags=["browse"])


class NodeUpdate(BaseModel):
    content: str


@router.get("/node")
async def get_node(
    path: str = Query("", description="URI path like 'nocturne' or 'nocturne/salem'"),
    domain: str = Query("core")
):
    """
    Get a node's content and its direct children.
    
    This is the only read endpoint you need - it gives you:
    - The current node's full content (or virtual root)
    - Preview of all children (next level)
    - Breadcrumb trail for navigation
    """
    client = get_sqlite_client()
    
    if not path:
        # Virtual Root Node
        memory = {
            "content": "",
            "importance": 0,
            "disclosure": None,
            "created_at": None
        }
        # Get roots as children
        children_raw = await client.get_children(None, domain=domain)
        breadcrumbs = [{"path": "", "label": "root"}]
    else:
        # Get the node itself
        memory = await client.get_memory_by_path(path, domain=domain)
        
        if not memory:
            raise HTTPException(status_code=404, detail=f"Path not found: {domain}://{path}")
        
        # Get children
        children_raw = await client.get_children(path, domain=domain)
        
        # Build breadcrumbs
        segments = path.split("/")
        breadcrumbs = [{"path": "", "label": "root"}]
        accumulated = ""
        for seg in segments:
            accumulated = f"{accumulated}/{seg}" if accumulated else seg
            breadcrumbs.append({"path": accumulated, "label": seg})
    
    children = [
        {
            "path": c["path"],
            "name": c["path"].split("/")[-1],  # Last segment
            "importance": c["importance"],
            "content_snippet": c["content_snippet"]
        }
        for c in children_raw
    ]
    children.sort(key=lambda x: (x["importance"] if x["importance"] is not None else 999, x["path"]))
    
    return {
        "node": {
            "path": path,
            "domain": domain,
            "uri": f"{domain}://{path}",
            "name": path.split("/")[-1] if path else "root",
            "content": memory["content"],
            "importance": memory["importance"],
            "disclosure": memory["disclosure"],
            "created_at": memory["created_at"]
        },
        "children": children,
        "breadcrumbs": breadcrumbs
    }


@router.put("/node")
async def update_node(
    path: str = Query(...),
    domain: str = Query("core"),
    body: NodeUpdate = ...
):
    """
    Update a node's content.
    """
    client = get_sqlite_client()
    
    # Check exists
    memory = await client.get_memory_by_path(path, domain=domain)
    if not memory:
        raise HTTPException(status_code=404, detail=f"Path not found: {domain}://{path}")
    
    # Update (creates new version, deprecates old)
    result = await client.update_memory(
        path=path,
        domain=domain,
        content=body.content,
    )
    
    return {"success": True, "memory_id": result["new_memory_id"]}
