"""
SQLite Client for Nocturne Memory System

This module implements the SQLite-based memory storage with:
- Path-based addressing (mem://path/to/memory)
- Version control via deprecated flag
- Multiple paths (aliases) pointing to same memory
"""

import os
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from contextlib import asynccontextmanager

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey,
    create_engine, select, update, delete, func, and_, or_
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship
from dotenv import load_dotenv, find_dotenv

# Load environment variables
_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path:
    load_dotenv(_dotenv_path)

Base = declarative_base()


# =============================================================================
# ORM Models
# =============================================================================

class Memory(Base):
    """A single memory unit with content and metadata."""
    __tablename__ = "memories"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=True)  # Optional title/name
    content = Column(Text, nullable=False)
    deprecated = Column(Boolean, default=False)  # Marked for review/deletion
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship to paths
    paths = relationship("Path", back_populates="memory")


class Path(Base):
    """A path pointing to a memory. Multiple paths can point to the same memory."""
    __tablename__ = "paths"
    
    # Composite primary key: (domain, path)
    # domain examples: "core", "writer", "game"
    # path examples: "char_nocturne", "char_nocturne/char_salem"
    domain = Column(String(64), primary_key=True, default="core")
    path = Column(String(512), primary_key=True)
    memory_id = Column(Integer, ForeignKey("memories.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Context metadata (moved from Memory to Path)
    importance = Column(Integer, default=0)  # Relative importance for ranking
    disclosure = Column(Text, nullable=True)  # When to expand this memory
    
    # Relationship to memory
    memory = relationship("Memory", back_populates="paths")


# =============================================================================
# SQLite Client
# =============================================================================

class SQLiteClient:
    """
    Async SQLite client for memory operations.
    
    Core operations:
    - read: Get memory by path
    - create: New memory with auto-generated or specified title
    - update: Create new version, deprecate old, repoint path
    - add_path: Create alias to existing memory
    - search: Full-text search on title and content
    """
    
    def __init__(self, database_url: str):
        """
        Initialize the SQLite client.
        
        Args:
            database_url: SQLAlchemy async URL, e.g. 
                         "sqlite+aiosqlite:///nocturne_memory.db"
        """
        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
    
    async def init_db(self):
        """Create tables if they don't exist."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def close(self):
        """Close the database connection."""
        await self.engine.dispose()
    
    @asynccontextmanager
    async def session(self):
        """Get an async session context manager."""
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    
    # =========================================================================
    # Read Operations
    # =========================================================================
    
    async def get_memory_by_path(self, path: str, domain: str = "core") -> Optional[Dict[str, Any]]:
        """
        Get a memory by its path.
        
        Args:
            path: The path to look up
            domain: The domain/namespace (e.g., "core", "writer", "game")
            
        Returns:
            Memory dict with id, title, content, importance, disclosure, created_at
            or None if not found
        """
        async with self.session() as session:
            result = await session.execute(
                select(Memory, Path)
                .join(Path, Memory.id == Path.memory_id)
                .where(Path.domain == domain)
                .where(Path.path == path)
                .where(Memory.deprecated == False)
            )
            row = result.first()
            
            if not row:
                return None
            
            memory, path_obj = row
            return {
                "id": memory.id,
                "title": memory.title,
                "content": memory.content,
                "importance": path_obj.importance,  # From Path
                "disclosure": path_obj.disclosure,  # From Path
                "deprecated": memory.deprecated,
                "created_at": memory.created_at.isoformat() if memory.created_at else None,
                "domain": path_obj.domain,
                "path": path_obj.path
            }
    
    async def get_memory_by_id(self, memory_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a memory by its ID (including deprecated ones).
        
        Args:
            memory_id: The memory ID
            
        Returns:
            Memory dict or None if not found
        """
        async with self.session() as session:
            result = await session.execute(
                select(Memory).where(Memory.id == memory_id)
            )
            memory = result.scalar_one_or_none()
            
            if not memory:
                return None
            
            # Get all paths pointing to this memory (with domain info)
            paths_result = await session.execute(
                select(Path.domain, Path.path).where(Path.memory_id == memory_id)
            )
            # Return as list of "domain://path" URIs
            paths = [f"{row[0]}://{row[1]}" for row in paths_result.all()]
            
            return {
                "id": memory.id,
                "title": memory.title,
                "content": memory.content,
                # Importance/Disclosure removed as they are path-dependent
                "deprecated": memory.deprecated,
                "created_at": memory.created_at.isoformat() if memory.created_at else None,
                "paths": paths
            }
    
    async def get_children(self, parent_path: Optional[str] = None, domain: str = "core") -> List[Dict[str, Any]]:
        """
        Get direct children of a path.
        If parent_path is None or empty, returns root elements (paths with no '/').
        
        Args:
            parent_path: The parent path (e.g. "char_nocturne"). If None/"", gets roots.
            domain: The domain/namespace
            
        Returns:
            List of child memories with their paths
        """
        async with self.session() as session:
            query = (
                select(Memory, Path)
                .join(Path, Memory.id == Path.memory_id)
                .where(Path.domain == domain)
                .where(Memory.deprecated == False)
            )

            if not parent_path:
                # Root level: Path has no slashes
                query = query.where(Path.path.not_like("%/%"))
            else:
                # Child level: Path starts with parent/ but has no MORE slashes
                # Escape parent_path for LIKE queries to avoid wildcards matching incorrect paths
                safe_parent = parent_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                safe_prefix = f"{safe_parent}/"
                
                query = query.where(Path.path.like(f"{safe_prefix}%", escape="\\"))
                query = query.where(Path.path.not_like(f"{safe_prefix}%/%", escape="\\"))

            # Order by Path.importance
            query = query.order_by(Path.importance.asc(), Path.path)
            
            result = await session.execute(query)
            
            children = []
            for memory, path_obj in result.all():
                children.append({
                    "domain": path_obj.domain,
                    "path": path_obj.path,
                    "title": memory.title,
                    "content_snippet": memory.content[:100] + "..." if len(memory.content) > 100 else memory.content,
                    "importance": path_obj.importance,  # From Path
                    "disclosure": path_obj.disclosure   # From Path
                })
            
            return children
    
    async def get_all_paths(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all paths with their memory info.
        
        Args:
            domain: If specified, only return paths in this domain.
                    If None, return paths from all domains.
        
        Returns:
            List of path info dicts
        """
        async with self.session() as session:
            query = (
                select(Path, Memory)
                .join(Memory, Path.memory_id == Memory.id)
                .where(Memory.deprecated == False)
            )
            
            if domain is not None:
                query = query.where(Path.domain == domain)
            
            query = query.order_by(Path.domain, Path.path)
            result = await session.execute(query)
            
            paths = []
            for path_obj, memory in result.all():
                paths.append({
                    "domain": path_obj.domain,
                    "path": path_obj.path,
                    "uri": f"{path_obj.domain}://{path_obj.path}",
                    "title": memory.title,
                    "importance": path_obj.importance,  # From Path
                    "memory_id": memory.id
                })
            
            return paths
    
    # =========================================================================
    # Create Operations
    # =========================================================================
    
    async def create_memory(
        self,
        parent_path: str,
        content: str,
        importance: int,
        title: Optional[str] = None,
        disclosure: Optional[str] = None,
        domain: str = "core"
    ) -> Dict[str, Any]:
        """
        Create a new memory under a parent path.
        
        Args:
            parent_path: Parent path (e.g. "char_nocturne/char_salem")
            content: Memory content
            importance: Relative importance (lower = more important, min 0)
            title: Optional title. If None, auto-assigns numeric ID
            disclosure: When to expand this memory
            domain: The domain/namespace (e.g., "core", "writer", "game")
            
        Returns:
            Created memory info with full path
        """
        async with self.session() as session:
            # Validate parent exists (if specified)
            if parent_path:
                parent_exists = await session.execute(
                    select(Path).where(Path.domain == domain).where(Path.path == parent_path)
                )
                if not parent_exists.scalar_one_or_none():
                    raise ValueError(
                        f"Parent '{domain}://{parent_path}' does not exist. "
                        f"Create the parent first, or use '{domain}://' as root."
                    )
            
            # Determine the final path
            if title:
                # Use provided title
                final_path = f"{parent_path}/{title}" if parent_path else title
                final_title = title
            else:
                # Auto-assign numeric ID
                next_num = await self._get_next_numeric_id(session, parent_path, domain)
                final_path = f"{parent_path}/{next_num}" if parent_path else str(next_num)
                final_title = str(next_num)
            
            # Check if path already exists in this domain
            existing = await session.execute(
                select(Path).where(Path.domain == domain).where(Path.path == final_path)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Path '{domain}://{final_path}' already exists")
            
            # Create memory (content only)
            memory = Memory(
                title=final_title,
                content=content
            )
            session.add(memory)
            await session.flush()  # Get the ID
            
            # Create path (with metadata)
            path_obj = Path(
                domain=domain, 
                path=final_path, 
                memory_id=memory.id,
                importance=importance,
                disclosure=disclosure
            )
            session.add(path_obj)
            
            return {
                "id": memory.id,
                "domain": domain,
                "path": final_path,
                "uri": f"{domain}://{final_path}",
                "title": final_title,
                "importance": importance
            }
    
    async def _get_next_numeric_id(self, session: AsyncSession, parent_path: str, domain: str = "core") -> int:
        """Get the next numeric ID for auto-naming under a parent path in a domain."""
        prefix = f"{parent_path}/" if parent_path else ""
        
        # Prepare LIKE clause with escaping if parent_path exists
        if parent_path:
            safe_parent = parent_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like_pattern = f"{safe_parent}/%"
            like_clause = Path.path.like(like_pattern, escape="\\")
        else:
            like_clause = Path.path.like("%")

        result = await session.execute(
            select(Path.path)
            .where(Path.domain == domain)
            .where(like_clause)
        )
        
        max_num = 0
        for (path,) in result.all():
            remainder = path[len(prefix):] if prefix else path
            # Only consider direct children
            if "/" not in remainder:
                try:
                    num = int(remainder)
                    max_num = max(max_num, num)
                except ValueError:
                    pass
        
        return max_num + 1
    
    # =========================================================================
    # Update Operations
    # =========================================================================
    
    async def update_memory(
        self,
        path: str,
        content: Optional[str] = None,
        title: Optional[str] = None,
        importance: Optional[int] = None,
        disclosure: Optional[str] = None,
        domain: str = "core"
    ) -> Dict[str, Any]:
        """
        Update a memory (creates new version, deprecates old, repoints path).
        
        Args:
            path: Path to update
            content: New content (None = keep old)
            title: New title (None = keep old)
            importance: New importance (None = keep old)
            disclosure: New disclosure (None = keep old)
            domain: The domain/namespace (e.g., "core", "writer", "game")
            
        Returns:
            Updated memory info including old and new memory IDs
        """
        async with self.session() as session:
            # 1. Get current memory and path
            result = await session.execute(
                select(Memory, Path)
                .join(Path, Memory.id == Path.memory_id)
                .where(Path.domain == domain)
                .where(Path.path == path)
                .where(Memory.deprecated == False)
            )
            row = result.first()
            
            if not row:
                raise ValueError(f"Path '{domain}://{path}' not found or memory is deprecated")
            
            old_memory, path_obj = row
            old_id = old_memory.id
            
            # Determine if we need a new memory version (content/title change)
            # or just a path metadata update (importance/disclosure change)
            
            content_changed = content is not None and content != old_memory.content
            title_changed = title is not None and title != old_memory.title
            
            # Update Path Metadata
            if importance is not None:
                path_obj.importance = importance
            if disclosure is not None:
                path_obj.disclosure = disclosure
                
            new_memory_id = old_id
            new_title = old_memory.title
            
            if content_changed or title_changed:
                # Content changed: Create new memory version
                new_title = title if title is not None else old_memory.title
                
                new_memory = Memory(
                    title=new_title,
                    content=content if content is not None else old_memory.content
                )
                session.add(new_memory)
                await session.flush()
                new_memory_id = new_memory.id
                
                # Mark old as deprecated
                await session.execute(
                    update(Memory).where(Memory.id == old_id).values(deprecated=True)
                )
                
                # Repoint ALL paths pointing to the old memory to the new memory
                # This ensures aliases stay in sync with the content update
                await session.execute(
                    update(Path).where(Path.memory_id == old_id).values(memory_id=new_memory.id)
                )
            else:
                # Only metadata changed, just commit the path update
                session.add(path_obj)
            
            return {
                "domain": domain,
                "path": path,
                "uri": f"{domain}://{path}",
                "old_memory_id": old_id,
                "new_memory_id": new_memory_id,
                "title": new_title
            }
    
    async def rollback_to_memory(self, path: str, target_memory_id: int, domain: str = "core") -> Dict[str, Any]:
        """
        Rollback a path to point to a specific memory version.
        
        Args:
            path: Path to rollback
            target_memory_id: Memory ID to restore to
            domain: The domain/namespace (e.g., "core", "writer", "game")
            
        Returns:
            Rollback result info
        """
        async with self.session() as session:
            # 1. Get current memory_id
            result = await session.execute(
                select(Path.memory_id)
                .where(Path.domain == domain)
                .where(Path.path == path)
            )
            current_id = result.scalar_one_or_none()
            
            if current_id is None:
                raise ValueError(f"Path '{domain}://{path}' not found")
            
            # 2. Verify target memory exists
            target = await session.execute(
                select(Memory).where(Memory.id == target_memory_id)
            )
            if not target.scalar_one_or_none():
                raise ValueError(f"Target memory ID {target_memory_id} not found")
            
            # 3. Mark current as deprecated
            await session.execute(
                update(Memory).where(Memory.id == current_id).values(deprecated=True)
            )
            
            # 4. Un-deprecate target
            await session.execute(
                update(Memory).where(Memory.id == target_memory_id).values(deprecated=False)
            )
            
            # 5. Repoint ALL paths that were pointing to the old memory
            await session.execute(
                update(Path)
                .where(Path.memory_id == current_id)
                .values(memory_id=target_memory_id)
            )
            
            return {
                "domain": domain,
                "path": path,
                "uri": f"{domain}://{path}",
                "old_memory_id": current_id,
                "restored_memory_id": target_memory_id
            }
    
    # =========================================================================
    # Path Operations
    # =========================================================================
    
    async def add_path(
        self,
        new_path: str,
        target_path: str,
        new_domain: str = "core",
        target_domain: str = "core",
        importance: int = 0,
        disclosure: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create an alias path pointing to the same memory as target_path.
        
        Args:
            new_path: New path to create
            target_path: Existing path to alias
            new_domain: Domain for the new path
            target_domain: Domain of the target path
            importance: Importance for this new alias
            disclosure: Disclosure trigger for this new alias
            
        Returns:
            Created alias info
        """
        async with self.session() as session:
            # Get target memory_id
            result = await session.execute(
                select(Path.memory_id)
                .where(Path.domain == target_domain)
                .where(Path.path == target_path)
            )
            target_id = result.scalar_one_or_none()
            
            if target_id is None:
                raise ValueError(f"Target path '{target_domain}://{target_path}' not found")
            
            # Check if new path exists in the new domain
            existing = await session.execute(
                select(Path)
                .where(Path.domain == new_domain)
                .where(Path.path == new_path)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Path '{new_domain}://{new_path}' already exists")
            
            # Create alias
            path_obj = Path(
                domain=new_domain, 
                path=new_path, 
                memory_id=target_id,
                importance=importance,
                disclosure=disclosure
            )
            session.add(path_obj)
            
            return {
                "new_uri": f"{new_domain}://{new_path}",
                "target_uri": f"{target_domain}://{target_path}",
                "memory_id": target_id
            }
    
    async def remove_path(self, path: str, domain: str = "core") -> Dict[str, Any]:
        """
        Remove a path (but not the memory it points to).
        
        Args:
            path: Path to remove
            domain: The domain/namespace (e.g., "core", "writer", "game")
            
        Returns:
            Removal info
        """
        async with self.session() as session:
            result = await session.execute(
                select(Path)
                .where(Path.domain == domain)
                .where(Path.path == path)
            )
            path_obj = result.scalar_one_or_none()
            
            if not path_obj:
                raise ValueError(f"Path '{domain}://{path}' not found")
            
            memory_id = path_obj.memory_id
            await session.delete(path_obj)
            
            return {
                "removed_uri": f"{domain}://{path}",
                "memory_id": memory_id
            }

    async def restore_path(
        self, 
        path: str, 
        domain: str, 
        memory_id: int, 
        importance: int = 0, 
        disclosure: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Restore a path pointing to a specific memory ID (used for rollback).
        
        Args:
            path: Path to restore
            domain: Domain
            memory_id: Memory ID to point to
            importance: Path importance
            disclosure: Path disclosure
            
        Returns:
            Restored path info
        """
        async with self.session() as session:
            # Check if memory exists
            memory_result = await session.execute(
                select(Memory).where(Memory.id == memory_id)
            )
            if not memory_result.scalar_one_or_none():
                raise ValueError(f"Memory ID {memory_id} not found")

            # Ensure memory is not deprecated (un-deprecate if needed)
            # This is critical for rollback: if we restore a path to a memory that was
            # deprecated (e.g. by a subsequent update), we must make it visible again.
            await session.execute(
                update(Memory).where(Memory.id == memory_id).values(deprecated=False)
            )
            
            # Check if path already exists (collision)
            existing = await session.execute(
                select(Path)
                .where(Path.domain == domain)
                .where(Path.path == path)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Path '{domain}://{path}' already exists")
            
            # Create path
            path_obj = Path(
                domain=domain,
                path=path,
                memory_id=memory_id,
                importance=importance,
                disclosure=disclosure
            )
            session.add(path_obj)
            
            return {
                "uri": f"{domain}://{path}",
                "memory_id": memory_id
            }
    
    # =========================================================================
    # Search Operations
    # =========================================================================
    
    async def search(self, query: str, limit: int = 10, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search memories by title and content.
        
        Args:
            query: Search query
            limit: Max results
            domain: If specified, only search in this domain.
                    If None, search across all domains.
            
        Returns:
            List of matching memories with paths
        """
        async with self.session() as session:
            # Simple LIKE search (can be upgraded to FULLTEXT later)
            search_pattern = f"%{query}%"
            
            base_query = (
                select(Memory, Path)
                .join(Path, Memory.id == Path.memory_id)
                .where(Memory.deprecated == False)
                .where(
                    or_(
                        Memory.title.like(search_pattern),
                        Memory.content.like(search_pattern)
                    )
                )
            )
            
            if domain is not None:
                base_query = base_query.where(Path.domain == domain)
            
            # Order by Path.importance
            base_query = base_query.order_by(Path.importance.asc()).limit(limit)
            result = await session.execute(base_query)
            
            matches = []
            seen_ids = set()
            
            for memory, path_obj in result.all():
                if memory.id not in seen_ids:
                    seen_ids.add(memory.id)
                    
                    # Find match snippet
                    content_lower = memory.content.lower()
                    query_lower = query.lower()
                    pos = content_lower.find(query_lower)
                    
                    if pos >= 0:
                        start = max(0, pos - 30)
                        end = min(len(memory.content), pos + len(query) + 30)
                        snippet = "..." + memory.content[start:end] + "..."
                    else:
                        snippet = memory.content[:80] + "..."
                    
                    matches.append({
                        "domain": path_obj.domain,
                        "path": path_obj.path,
                        "uri": f"{path_obj.domain}://{path_obj.path}",
                        "title": memory.title,
                        "snippet": snippet,
                        "importance": path_obj.importance  # From Path
                    })
            
            return matches
    
    # =========================================================================
    # Deprecated Memory Operations (for Salem's review)
    # =========================================================================
    
    
    async def get_memory_version(self, memory_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific memory version by ID (including deprecated ones).
        
        Args:
            memory_id: The memory ID
            
        Returns:
            Memory details
        """
        async with self.session() as session:
            result = await session.execute(
                select(Memory).where(Memory.id == memory_id)
            )
            memory = result.scalar_one_or_none()
            
            if not memory:
                return None
            
            # Get paths pointing to this memory
            paths_result = await session.execute(
                select(Path).where(Path.memory_id == memory_id)
            )
            paths = [f"{p.domain}://{p.path}" for p in paths_result.scalars().all()]
            
            return {
                "memory_id": memory.id,
                "title": memory.title,
                "content": memory.content,
                # Importance/Disclosure removed
                "created_at": memory.created_at.isoformat() if memory.created_at else None,
                "deprecated": memory.deprecated,
                "paths": paths
            }

    async def get_deprecated_memories(self) -> List[Dict[str, Any]]:
        """
        Get all deprecated memories for Salem's review.
        
        Returns:
            List of deprecated memories
        """
        async with self.session() as session:
            result = await session.execute(
                select(Memory)
                .where(Memory.deprecated == True)
                .order_by(Memory.created_at.desc())
            )
            
            memories = []
            for memory in result.scalars().all():
                memories.append({
                    "id": memory.id,
                    "title": memory.title,
                    "content_snippet": memory.content[:200] + "..." if len(memory.content) > 200 else memory.content,
                    "created_at": memory.created_at.isoformat() if memory.created_at else None
                })
            
            return memories
    
    async def permanently_delete_memory(self, memory_id: int) -> Dict[str, Any]:
        """
        Permanently delete a memory (Salem only).
        
        Args:
            memory_id: Memory ID to delete
            
        Returns:
            Deletion info
        """
        async with self.session() as session:
            # First remove any paths pointing to this memory
            await session.execute(
                delete(Path).where(Path.memory_id == memory_id)
            )
            
            # Then delete the memory
            result = await session.execute(
                delete(Memory).where(Memory.id == memory_id)
            )
            
            if result.rowcount == 0:
                raise ValueError(f"Memory ID {memory_id} not found")
            
            return {
                "deleted_memory_id": memory_id
            }

# =============================================================================
# Global Singleton
# =============================================================================

_sqlite_client: Optional[SQLiteClient] = None


def get_sqlite_client() -> SQLiteClient:
    """Get the global SQLiteClient instance."""
    global _sqlite_client
    if _sqlite_client is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is not set. Please check your .env file.")
        _sqlite_client = SQLiteClient(database_url)
    return _sqlite_client


async def close_sqlite_client():
    """Close the global SQLiteClient connection."""
    global _sqlite_client
    if _sqlite_client:
        await _sqlite_client.close()
        _sqlite_client = None
