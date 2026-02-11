from fastapi import APIRouter, HTTPException
from db import get_sqlite_client

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.get("/orphans")
async def get_orphans():
    """
    Get all orphan memories (both deprecated and truly orphaned).
    
    - deprecated: old versions created by update_memory (has migrated_to)
    - orphaned: non-deprecated memories with no paths pointing to them
    
    Includes migration target paths for deprecated memories so Salem can see
    where the memory used to live without clicking into each one.
    """
    client = get_sqlite_client()
    return await client.get_all_orphan_memories()


@router.get("/orphans/{memory_id}")
async def get_orphan_detail(memory_id: int):
    """
    Get full detail of an orphan memory, including migration target's
    full content for diff comparison.
    """
    client = get_sqlite_client()
    detail = await client.get_orphan_detail(memory_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")
    return detail


@router.delete("/orphans/{memory_id}")
async def delete_orphan(memory_id: int):
    """
    Permanently delete an orphan memory.
    This action is irreversible. Repairs the version chain if applicable.
    
    Safety: The orphan check (deprecated or path-less) and the deletion
    run inside the same DB transaction, eliminating TOCTOU races.
    """
    client = get_sqlite_client()
    try:
        result = await client.permanently_delete_memory(
            memory_id, require_orphan=True
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=409, detail=str(e))
