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
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    create_engine,
    select,
    update,
    delete,
    func,
    and_,
    or_,
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
    """A single memory unit with content and metadata.

    Note: The 'title' column was removed. A memory's display name is now
    derived from the last segment of its path(s) in the paths table.
    Existing DB columns named 'title' are simply ignored by SQLAlchemy.

    Version chain: When a memory is updated, the old version's `migrated_to`
    field points to the new version's ID, forming a singly-linked list:
        Memory(id=1, migrated_to=5) → Memory(id=5, migrated_to=12) → Memory(id=12, migrated_to=NULL)
    When a middle node is permanently deleted, the chain is repaired by
    skipping over it (A→B→C, delete B → A→C).
    """

    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    deprecated = Column(Boolean, default=False)  # Marked for review/deletion
    migrated_to = Column(
        Integer, nullable=True
    )  # Points to successor memory ID (version chain)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship to paths
    paths = relationship("Path", back_populates="memory")


class Path(Base):
    """A path pointing to a memory. Multiple paths can point to the same memory."""

    __tablename__ = "paths"

    # Composite primary key: (domain, path)
    # domain examples: "core", "writer", "game"
    # path examples: "nocturne", "nocturne/salem"
    domain = Column(String(64), primary_key=True, default="core")
    path = Column(String(512), primary_key=True)
    memory_id = Column(Integer, ForeignKey("memories.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Context metadata (moved from Memory to Path)
    priority = Column(Integer, default=0)  # Relative priority for ranking
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
    - create: New memory with auto-generated or specified path segment
    - update: Create new version, deprecate old, repoint path
    - add_path: Create alias to existing memory
    - search: Substring search on path and content
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
        """Create tables if they don't exist, and run migrations for schema changes."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Migration: add migrated_to column if not present (for existing DBs)
            await conn.run_sync(self._migrate_add_migrated_to)

    @staticmethod
    def _migrate_add_migrated_to(connection):
        """Add migrated_to column to memories table if it doesn't exist."""
        from sqlalchemy import inspect, text

        inspector = inspect(connection)
        columns = [col["name"] for col in inspector.get_columns("memories")]
        if "migrated_to" not in columns:
            connection.execute(
                text("ALTER TABLE memories ADD COLUMN migrated_to INTEGER")
            )

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

    async def get_memory_by_path(
        self, path: str, domain: str = "core"
    ) -> Optional[Dict[str, Any]]:
        """
        Get a memory by its path.

        Args:
            path: The path to look up
            domain: The domain/namespace (e.g., "core", "writer", "game")

        Returns:
            Memory dict with id, content, priority, disclosure, created_at
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
                "content": memory.content,
                "priority": path_obj.priority,  # From Path
                "disclosure": path_obj.disclosure,  # From Path
                "deprecated": memory.deprecated,
                "created_at": memory.created_at.isoformat()
                if memory.created_at
                else None,
                "domain": path_obj.domain,
                "path": path_obj.path,
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
            result = await session.execute(select(Memory).where(Memory.id == memory_id))
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
                "content": memory.content,
                # Priority/Disclosure removed as they are path-dependent
                "deprecated": memory.deprecated,
                "migrated_to": memory.migrated_to,
                "created_at": memory.created_at.isoformat()
                if memory.created_at
                else None,
                "paths": paths,
            }

    async def get_children(
        self, memory_id: Optional[int] = None, domain: str = "core"
    ) -> List[Dict[str, Any]]:
        """
        Get direct children of a memory node.

        When memory_id is given, finds ALL paths (aliases) pointing to that
        memory across all domains, then collects direct children under each.
        This models human associative recall: once you reach a memory, the
        sub-memories depend on WHAT it IS, not WHICH path you used to get here.

        When memory_id is None (virtual root), returns root-level paths
        (paths with no '/') in the given domain.

        Args:
            memory_id: The memory ID to find children for.
                       If None, returns domain root elements.
            domain: Only used when memory_id is None (root browsing).

        Returns:
            List of child memories (deduplicated by domain+path),
            sorted by priority then path.
        """
        async with self.session() as session:
            if memory_id is None:
                # Virtual root: return paths with no slashes in the given domain
                query = (
                    select(Memory, Path)
                    .join(Path, Memory.id == Path.memory_id)
                    .where(Path.domain == domain)
                    .where(Memory.deprecated == False)
                    .where(Path.path.not_like("%/%"))
                    .order_by(Path.priority.asc(), Path.path)
                )

                result = await session.execute(query)

                children = []
                for memory, path_obj in result.all():
                    children.append(
                        {
                            "domain": path_obj.domain,
                            "path": path_obj.path,
                            "name": path_obj.path.rsplit("/", 1)[-1],
                            "content_snippet": memory.content[:100] + "..."
                            if len(memory.content) > 100
                            else memory.content,
                            "priority": path_obj.priority,
                            "disclosure": path_obj.disclosure,
                        }
                    )

                return children

            # --- memory_id provided: find children across all aliases ---

            # 1. Find all paths pointing to this memory
            parent_paths_result = await session.execute(
                select(Path.domain, Path.path).where(Path.memory_id == memory_id)
            )
            parent_paths = parent_paths_result.all()

            if not parent_paths:
                return []

            # 2. Build OR conditions for children under each parent path
            child_conditions = []
            for parent_domain, parent_path in parent_paths:
                safe_parent = (
                    parent_path.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                safe_prefix = f"{safe_parent}/"

                child_conditions.append(
                    and_(
                        Path.domain == parent_domain,
                        Path.path.like(f"{safe_prefix}%", escape="\\"),
                        Path.path.not_like(f"{safe_prefix}%/%", escape="\\"),
                    )
                )

            # 3. Query all children in one shot
            query = (
                select(Memory, Path)
                .join(Path, Memory.id == Path.memory_id)
                .where(Memory.deprecated == False)
                .where(or_(*child_conditions))
                .order_by(Path.priority.asc(), Path.path)
            )

            result = await session.execute(query)

            # 4. Deduplicate by (domain, path)
            seen = set()
            children = []
            for memory, path_obj in result.all():
                key = (path_obj.domain, path_obj.path)
                if key in seen:
                    continue
                seen.add(key)

                children.append(
                    {
                        "domain": path_obj.domain,
                        "path": path_obj.path,
                        "name": path_obj.path.rsplit("/", 1)[-1],
                        "content_snippet": memory.content[:100] + "..."
                        if len(memory.content) > 100
                        else memory.content,
                        "priority": path_obj.priority,
                        "disclosure": path_obj.disclosure,
                    }
                )

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
                paths.append(
                    {
                        "domain": path_obj.domain,
                        "path": path_obj.path,
                        "uri": f"{path_obj.domain}://{path_obj.path}",
                        "name": path_obj.path.rsplit("/", 1)[
                            -1
                        ],  # Last segment of path
                        "priority": path_obj.priority,  # From Path
                        "memory_id": memory.id,
                    }
                )

            return paths

    # =========================================================================
    # Create Operations
    # =========================================================================

    async def create_memory(
        self,
        parent_path: str,
        content: str,
        priority: int,
        title: Optional[str] = None,
        disclosure: Optional[str] = None,
        domain: str = "core",
    ) -> Dict[str, Any]:
        """
        Create a new memory under a parent path.

        Args:
            parent_path: Parent path (e.g. "nocturne/salem")
            content: Memory content
            priority: Retrieval priority (lower = higher priority, min 0)
            title: Optional path segment name. If None, auto-assigns numeric ID.
                   This becomes the last segment of the path, NOT stored in memories table.
            disclosure: When to expand this memory
            domain: The domain/namespace (e.g., "core", "writer", "game")

        Returns:
            Created memory info with full path
        """
        async with self.session() as session:
            # Validate parent exists (if specified)
            if parent_path:
                parent_exists = await session.execute(
                    select(Path)
                    .where(Path.domain == domain)
                    .where(Path.path == parent_path)
                )
                if not parent_exists.scalar_one_or_none():
                    raise ValueError(
                        f"Parent '{domain}://{parent_path}' does not exist. "
                        f"Create the parent first, or use '{domain}://' as root."
                    )

            # Determine the final path
            if title:
                # Use provided title as path segment
                final_path = f"{parent_path}/{title}" if parent_path else title
            else:
                # Auto-assign numeric ID
                next_num = await self._get_next_numeric_id(session, parent_path, domain)
                final_path = (
                    f"{parent_path}/{next_num}" if parent_path else str(next_num)
                )

            # Check if path already exists in this domain
            existing = await session.execute(
                select(Path).where(Path.domain == domain).where(Path.path == final_path)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Path '{domain}://{final_path}' already exists")

            # Create memory (content only, no title stored)
            memory = Memory(content=content)
            session.add(memory)
            await session.flush()  # Get the ID

            # Create path (with metadata)
            path_obj = Path(
                domain=domain,
                path=final_path,
                memory_id=memory.id,
                priority=priority,
                disclosure=disclosure,
            )
            session.add(path_obj)

            return {
                "id": memory.id,
                "domain": domain,
                "path": final_path,
                "uri": f"{domain}://{final_path}",
                "priority": priority,
            }

    async def _get_next_numeric_id(
        self, session: AsyncSession, parent_path: str, domain: str = "core"
    ) -> int:
        """Get the next numeric ID for auto-naming under a parent path in a domain."""
        prefix = f"{parent_path}/" if parent_path else ""

        # Prepare LIKE clause with escaping if parent_path exists
        if parent_path:
            safe_parent = (
                parent_path.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            like_pattern = f"{safe_parent}/%"
            like_clause = Path.path.like(like_pattern, escape="\\")
        else:
            like_clause = Path.path.like("%")

        result = await session.execute(
            select(Path.path).where(Path.domain == domain).where(like_clause)
        )

        max_num = 0
        for (path,) in result.all():
            remainder = path[len(prefix) :] if prefix else path
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
        priority: Optional[int] = None,
        disclosure: Optional[str] = None,
        domain: str = "core",
    ) -> Dict[str, Any]:
        """
        Update a memory (creates new version, deprecates old, repoints path).

        Args:
            path: Path to update
            content: New content (None = keep old)
            priority: New priority (None = keep old)
            disclosure: New disclosure (None = keep old)
            domain: The domain/namespace (e.g., "core", "writer", "game")

        Returns:
            Updated memory info including old and new memory IDs
        """
        if content is None and priority is None and disclosure is None:
            raise ValueError(
                f"No update fields provided for '{domain}://{path}'. "
                "At least one of content, priority, or disclosure must be set."
            )

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
                raise ValueError(
                    f"Path '{domain}://{path}' not found or memory is deprecated"
                )

            old_memory, path_obj = row
            old_id = old_memory.id

            # Update Path Metadata
            if priority is not None:
                path_obj.priority = priority
            if disclosure is not None:
                path_obj.disclosure = disclosure

            new_memory_id = old_id

            if content is not None:
                # Content update requested: ALWAYS create a new version.
                #
                # Previously this checked `content != old_memory.content` and
                # silently skipped when content was identical.  This caused a
                # TOCTOU bug: the MCP layer reads content in session A, computes
                # the replacement, then passes it here (session B).  If the DB
                # content was already updated between the two reads (or if the
                # MCP transport subtly normalised whitespace), the equality
                # check would pass, no new version was created, yet "Success"
                # was returned to the caller.
                #
                # The MCP layer is responsible for validating the change; the
                # DB layer should unconditionally persist whatever it receives.
                new_memory = Memory(content=content)
                session.add(new_memory)
                await session.flush()
                new_memory_id = new_memory.id

                # Mark old as deprecated and set migration pointer to new version
                await session.execute(
                    update(Memory)
                    .where(Memory.id == old_id)
                    .values(deprecated=True, migrated_to=new_memory.id)
                )

                # Repoint ALL paths pointing to the old memory to the new memory
                # This ensures aliases stay in sync with the content update
                await session.execute(
                    update(Path)
                    .where(Path.memory_id == old_id)
                    .values(memory_id=new_memory.id)
                )

            if content is None:
                # Only metadata changed, explicitly add the path object for flush
                session.add(path_obj)

            return {
                "domain": domain,
                "path": path,
                "uri": f"{domain}://{path}",
                "old_memory_id": old_id,
                "new_memory_id": new_memory_id,
            }

    async def rollback_to_memory(
        self, path: str, target_memory_id: int, domain: str = "core"
    ) -> Dict[str, Any]:
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

            # 3. Mark current as deprecated and point to restored version
            await session.execute(
                update(Memory)
                .where(Memory.id == current_id)
                .values(deprecated=True, migrated_to=target_memory_id)
            )

            # 4. Un-deprecate target and clear its migration pointer (it's the active version now)
            await session.execute(
                update(Memory)
                .where(Memory.id == target_memory_id)
                .values(deprecated=False, migrated_to=None)
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
                "restored_memory_id": target_memory_id,
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
        priority: int = 0,
        disclosure: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create an alias path pointing to the same memory as target_path.

        Args:
            new_path: New path to create
            target_path: Existing path to alias
            new_domain: Domain for the new path
            target_domain: Domain of the target path
            priority: Priority for this new alias
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
                raise ValueError(
                    f"Target path '{target_domain}://{target_path}' not found"
                )

            # Validate parent of new_path exists
            if "/" in new_path:
                parent_path = new_path.rsplit("/", 1)[0]
                parent_exists = await session.execute(
                    select(Path)
                    .where(Path.domain == new_domain)
                    .where(Path.path == parent_path)
                )
                if not parent_exists.scalar_one_or_none():
                    raise ValueError(
                        f"Parent '{new_domain}://{parent_path}' does not exist. "
                        f"Create the parent first, or use a shallower alias path."
                    )

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
                priority=priority,
                disclosure=disclosure,
            )
            session.add(path_obj)

            return {
                "new_uri": f"{new_domain}://{new_path}",
                "target_uri": f"{target_domain}://{target_path}",
                "memory_id": target_id,
            }

    async def remove_path(self, path: str, domain: str = "core") -> Dict[str, Any]:
        """
        Remove a path (but not the memory it points to).

        Refuses to delete a path that still has children. The caller must
        delete all child paths first before removing the parent.

        Args:
            path: Path to remove
            domain: The domain/namespace (e.g., "core", "writer", "game")

        Returns:
            Removal info

        Raises:
            ValueError: If the path has children or does not exist
        """
        async with self.session() as session:
            result = await session.execute(
                select(Path).where(Path.domain == domain).where(Path.path == path)
            )
            path_obj = result.scalar_one_or_none()

            if not path_obj:
                raise ValueError(f"Path '{domain}://{path}' not found")

            # Block deletion if child paths exist
            safe_path = (
                path.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            child_prefix = f"{safe_path}/"
            child_result = await session.execute(
                select(func.count())
                .select_from(Path)
                .where(Path.domain == domain)
                .where(Path.path.like(f"{child_prefix}%", escape="\\"))
            )
            child_count = child_result.scalar()

            if child_count > 0:
                # Fetch up to 5 child URIs for a helpful error message
                sample_result = await session.execute(
                    select(Path.path)
                    .where(Path.domain == domain)
                    .where(Path.path.like(f"{child_prefix}%", escape="\\"))
                    .order_by(Path.path)
                    .limit(5)
                )
                sample_paths = [
                    f"{domain}://{row[0]}" for row in sample_result.all()
                ]
                listing = ", ".join(sample_paths)
                suffix = f" (and {child_count - 5} more)" if child_count > 5 else ""
                raise ValueError(
                    f"Cannot delete '{domain}://{path}': "
                    f"it still has {child_count} child path(s). "
                    f"Delete children first: {listing}{suffix}"
                )

            memory_id = path_obj.memory_id
            await session.delete(path_obj)

            return {"removed_uri": f"{domain}://{path}", "memory_id": memory_id}

    async def restore_path(
        self,
        path: str,
        domain: str,
        memory_id: int,
        priority: int = 0,
        disclosure: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Restore a path pointing to a specific memory ID (used for rollback).

        Args:
            path: Path to restore
            domain: Domain
            memory_id: Memory ID to point to
            priority: Path priority
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
                select(Path).where(Path.domain == domain).where(Path.path == path)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Path '{domain}://{path}' already exists")

            # Create path
            path_obj = Path(
                domain=domain,
                path=path,
                memory_id=memory_id,
                priority=priority,
                disclosure=disclosure,
            )
            session.add(path_obj)

            return {"uri": f"{domain}://{path}", "memory_id": memory_id}

    # =========================================================================
    # Search Operations
    # =========================================================================

    async def search(
        self, query: str, limit: int = 10, domain: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search memories by path and content.

        Args:
            query: Search query (substring match on path segments and content)
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
                        Path.path.like(search_pattern),
                        Memory.content.like(search_pattern),
                    )
                )
            )

            if domain is not None:
                base_query = base_query.where(Path.domain == domain)

            # Order by Path.priority
            base_query = base_query.order_by(Path.priority.asc()).limit(limit)
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

                    matches.append(
                        {
                            "domain": path_obj.domain,
                            "path": path_obj.path,
                            "uri": f"{path_obj.domain}://{path_obj.path}",
                            "name": path_obj.path.rsplit("/", 1)[
                                -1
                            ],  # Last segment of path
                            "snippet": snippet,
                            "priority": path_obj.priority,  # From Path
                        }
                    )

            return matches

    # =========================================================================
    # Recent Memories
    # =========================================================================

    async def get_recent_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get the most recently created/updated non-deprecated memories
        that have at least one path (URI) pointing to them.

        Since updates create new Memory rows (old ones are deprecated),
        created_at on non-deprecated rows effectively means "last modified".

        Args:
            limit: Maximum number of results to return

        Returns:
            List of dicts with uri, priority, disclosure, created_at,
            ordered by created_at DESC (most recent first).
        """
        async with self.session() as session:
            # Subquery: find non-deprecated memory IDs that have paths
            # Group by memory_id to avoid duplicates when a memory has multiple paths
            result = await session.execute(
                select(Memory, Path)
                .join(Path, Memory.id == Path.memory_id)
                .where(Memory.deprecated == False)
                .order_by(Memory.created_at.desc())
            )

            seen_memory_ids = set()
            memories = []

            for memory, path_obj in result.all():
                if memory.id in seen_memory_ids:
                    continue
                seen_memory_ids.add(memory.id)

                memories.append(
                    {
                        "memory_id": memory.id,
                        "uri": f"{path_obj.domain}://{path_obj.path}",
                        "priority": path_obj.priority,
                        "disclosure": path_obj.disclosure,
                        "created_at": memory.created_at.isoformat()
                        if memory.created_at
                        else None,
                    }
                )

                if len(memories) >= limit:
                    break

            return memories

    # =========================================================================
    # Deprecated Memory Operations (for human's review)
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
            result = await session.execute(select(Memory).where(Memory.id == memory_id))
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
                "content": memory.content,
                # Importance/Disclosure removed
                "created_at": memory.created_at.isoformat()
                if memory.created_at
                else None,
                "deprecated": memory.deprecated,
                "migrated_to": memory.migrated_to,
                "paths": paths,
            }

    async def get_deprecated_memories(self) -> List[Dict[str, Any]]:
        """
        Get all deprecated memories for human's review.

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
                memories.append(
                    {
                        "id": memory.id,
                        "content_snippet": memory.content[:200] + "..."
                        if len(memory.content) > 200
                        else memory.content,
                        "migrated_to": memory.migrated_to,
                        "created_at": memory.created_at.isoformat()
                        if memory.created_at
                        else None,
                    }
                )

            return memories

    async def _resolve_migration_chain(
        self, session: AsyncSession, start_id: int, max_hops: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Follow the migrated_to chain from start_id to the final target.

        The final target is the memory at the end of the chain (migrated_to=NULL).
        Returns None if the chain is broken (missing memory) or too long (cycle).
        """
        current_id = start_id
        for _ in range(max_hops):
            result = await session.execute(
                select(Memory).where(Memory.id == current_id)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                return None  # Broken chain
            if memory.migrated_to is None:
                # Final target reached
                paths_result = await session.execute(
                    select(Path).where(Path.memory_id == memory.id)
                )
                paths = [f"{p.domain}://{p.path}" for p in paths_result.scalars().all()]
                return {
                    "id": memory.id,
                    "content": memory.content,
                    "content_snippet": (
                        memory.content[:200] + "..."
                        if len(memory.content) > 200
                        else memory.content
                    ),
                    "created_at": memory.created_at.isoformat()
                    if memory.created_at
                    else None,
                    "deprecated": memory.deprecated,
                    "paths": paths,
                }
            current_id = memory.migrated_to
        return None  # Chain too long, likely a cycle

    async def get_all_orphan_memories(self) -> List[Dict[str, Any]]:
        """
        Get all orphan memories in the system.

        Two categories:
        - "deprecated": deprecated=True, created by update_memory. Has migrated_to.
        - "orphaned": deprecated=False but no paths point to it. Created by path deletion.

        For deprecated memories with migrated_to, resolves the migration chain to
        find the final target and its current paths.
        """
        async with self.session() as session:
            orphans = []

            # 1. Deprecated memories (from update_memory)
            deprecated_result = await session.execute(
                select(Memory)
                .where(Memory.deprecated == True)
                .order_by(Memory.created_at.desc())
            )

            for memory in deprecated_result.scalars().all():
                item = {
                    "id": memory.id,
                    "content_snippet": (
                        memory.content[:200] + "..."
                        if len(memory.content) > 200
                        else memory.content
                    ),
                    "created_at": memory.created_at.isoformat()
                    if memory.created_at
                    else None,
                    "deprecated": True,
                    "migrated_to": memory.migrated_to,
                    "category": "deprecated",
                    "migration_target": None,
                }

                if memory.migrated_to:
                    target = await self._resolve_migration_chain(
                        session, memory.migrated_to
                    )
                    if target:
                        item["migration_target"] = {
                            "id": target["id"],
                            "paths": target["paths"],
                            "content_snippet": target["content_snippet"],
                        }

                orphans.append(item)

            # 2. Truly orphaned memories (non-deprecated, no paths)
            orphaned_result = await session.execute(
                select(Memory)
                .outerjoin(Path, Memory.id == Path.memory_id)
                .where(Memory.deprecated == False)
                .where(Path.memory_id.is_(None))
                .order_by(Memory.created_at.desc())
            )

            for memory in orphaned_result.scalars().all():
                orphans.append(
                    {
                        "id": memory.id,
                        "content_snippet": (
                            memory.content[:200] + "..."
                            if len(memory.content) > 200
                            else memory.content
                        ),
                        "created_at": memory.created_at.isoformat()
                        if memory.created_at
                        else None,
                        "deprecated": False,
                        "migrated_to": memory.migrated_to,
                        "category": "orphaned",
                        "migration_target": None,
                    }
                )

            return orphans

    async def get_orphan_detail(self, memory_id: int) -> Optional[Dict[str, Any]]:
        """
        Get full detail of an orphan memory for content viewing and diff comparison.

        Returns full content of both the orphan and its final migration target
        (if applicable).
        """
        async with self.session() as session:
            result = await session.execute(select(Memory).where(Memory.id == memory_id))
            memory = result.scalar_one_or_none()
            if not memory:
                return None

            # Determine category
            if memory.deprecated:
                category = "deprecated"
            else:
                paths_count_result = await session.execute(
                    select(func.count())
                    .select_from(Path)
                    .where(Path.memory_id == memory_id)
                )
                category = "orphaned" if paths_count_result.scalar() == 0 else "active"

            detail = {
                "id": memory.id,
                "content": memory.content,
                "created_at": memory.created_at.isoformat()
                if memory.created_at
                else None,
                "deprecated": memory.deprecated,
                "migrated_to": memory.migrated_to,
                "category": category,
                "migration_target": None,
            }

            # Resolve migration chain for diff comparison
            if memory.migrated_to:
                target = await self._resolve_migration_chain(
                    session, memory.migrated_to
                )
                if target:
                    detail["migration_target"] = {
                        "id": target["id"],
                        "content": target["content"],
                        "paths": target["paths"],
                        "created_at": target["created_at"],
                    }

            return detail

    async def permanently_delete_memory(
        self, memory_id: int, *, require_orphan: bool = False
    ) -> Dict[str, Any]:
        """
        Permanently delete a memory (human only).

        Before deletion, repairs the version chain: if any other memory
        has migrated_to pointing to this one, it will be updated to skip
        over and point to this memory's own migrated_to target.

        Example: A(migrated_to=B) → B(migrated_to=C) → C
                 Delete B → A(migrated_to=C) → C

        Args:
            memory_id: Memory ID to delete
            require_orphan: If True, verify the memory is still an orphan
                (deprecated or path-less) within the same transaction.
                Raises PermissionError if the memory has active paths.

        Returns:
            Deletion info

        Raises:
            ValueError: Memory ID not found
            PermissionError: Memory has active paths (only when require_orphan=True)
        """
        async with self.session() as session:
            # 1. Get the memory being deleted
            target_result = await session.execute(
                select(Memory.deprecated, Memory.migrated_to).where(
                    Memory.id == memory_id
                )
            )
            target_row = target_result.first()
            if not target_row:
                raise ValueError(f"Memory ID {memory_id} not found")

            deprecated, successor_id = target_row

            # 2. If caller requires orphan safety, verify within this transaction
            if require_orphan and not deprecated:
                path_count_result = await session.execute(
                    select(func.count())
                    .select_from(Path)
                    .where(Path.memory_id == memory_id)
                )
                path_count = path_count_result.scalar()
                if path_count > 0:
                    raise PermissionError(
                        f"Memory {memory_id} is no longer an orphan "
                        f"(has {path_count} active path(s)). Deletion aborted."
                    )

            # 3. Repair the chain: any memory pointing to the deleted node
            #    should now point to the deleted node's successor
            await session.execute(
                update(Memory)
                .where(Memory.migrated_to == memory_id)
                .values(migrated_to=successor_id)
            )

            # 4. Remove any paths pointing to this memory
            await session.execute(delete(Path).where(Path.memory_id == memory_id))

            # 5. Delete the memory
            result = await session.execute(delete(Memory).where(Memory.id == memory_id))

            if result.rowcount == 0:
                raise ValueError(f"Memory ID {memory_id} not found")

            return {"deleted_memory_id": memory_id, "chain_repaired_to": successor_id}


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
            raise ValueError(
                "DATABASE_URL environment variable is not set. Please check your .env file."
            )
        _sqlite_client = SQLiteClient(database_url)
    return _sqlite_client


async def close_sqlite_client():
    """Close the global SQLiteClient connection."""
    global _sqlite_client
    if _sqlite_client:
        await _sqlite_client.close()
        _sqlite_client = None
