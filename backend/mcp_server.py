"""
MCP Server for Nocturne Memory System (SQLite Backend)

This module provides the MCP (Model Context Protocol) interface for 
Nocturne to interact with the SQLite-based memory system.

URI-based addressing with domain prefixes:
- core://char_nocturne           - Nocturne's identity/memories
- writer://chapter_1             - Story/script drafts
- game://magic_system            - Game setting documents

Multiple paths can point to the same memory (aliases).
"""

import os
import re
import sys
import uuid
from datetime import datetime
from typing import Optional, Tuple
from dotenv import load_dotenv, find_dotenv

# Ensure we can import from backend modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from db.sqlite_client import get_sqlite_client
from db.snapshot import get_snapshot_manager

# Load environment variables
# Explicitly look for .env in the parent directory (project root)
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
dotenv_path = os.path.join(root_dir, '.env')

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    # Fallback to find_dotenv
    _dotenv_path = find_dotenv(usecwd=True)
    if _dotenv_path:
        load_dotenv(_dotenv_path)

# Initialize FastMCP server
mcp = FastMCP("Nocturne Memory Interface")

# =============================================================================
# Domain Configuration
# =============================================================================
# Valid domains (protocol prefixes)
# =============================================================================
VALID_DOMAINS = [d.strip() for d in os.getenv("VALID_DOMAINS", "core,writer,game,notes,system").split(",")]
DEFAULT_DOMAIN = "core"

# =============================================================================
# Core Memories Configuration
# =============================================================================
# These URIs will be auto-loaded when Cursor reads the core memories resource.
# Salem can edit this list after migration.
#
# Format: full URIs (e.g., "core://char_nocturne", "core://char_nocturne/char_salem")
# =============================================================================
CORE_MEMORY_URIS = [
    # === Key Entities ===
    "core://char_salem",
    
    # === Core Relationships ===
    "core://char_nocturne/char_salem",
    "core://char_nocturne/char_kurou",
]

# Session ID for this MCP server instance
_SESSION_ID = f"mcp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def get_session_id() -> str:
    """Get the current session ID for snapshot tracking."""
    return _SESSION_ID


# =============================================================================
# URI Parsing
# =============================================================================

# Regex pattern for URI: domain://path
_URI_PATTERN = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*)://(.*)$')


def parse_uri(uri: str) -> Tuple[str, str]:
    """
    Parse a memory URI into (domain, path).
    
    Supported formats:
    - "core://char_nocturne"       -> ("core", "char_nocturne")
    - "writer://chapter_1"         -> ("writer", "chapter_1")
    - "char_nocturne"              -> ("core", "char_nocturne")  [legacy fallback]
    
    Args:
        uri: The URI to parse
        
    Returns:
        Tuple of (domain, path)
        
    Raises:
        ValueError: If the URI format is invalid or domain is unknown
    """
    uri = uri.strip()
    
    match = _URI_PATTERN.match(uri)
    if match:
        domain = match.group(1).lower()
        path = match.group(2).strip("/")
        
        if domain not in VALID_DOMAINS:
            raise ValueError(
                f"Unknown domain '{domain}'. Valid domains: {', '.join(VALID_DOMAINS)}"
            )
        
        return (domain, path)
    
    # Legacy fallback: bare path without protocol
    # Assume default domain (core)
    path = uri.strip("/")
    return (DEFAULT_DOMAIN, path)


def make_uri(domain: str, path: str) -> str:
    """
    Create a URI from domain and path.
    
    Args:
        domain: The domain (e.g., "core", "writer")
        path: The path (e.g., "char_nocturne")
        
    Returns:
        Full URI (e.g., "core://char_nocturne")
    """
    return f"{domain}://{path}"


# =============================================================================
# Snapshot Helpers
# =============================================================================
#
# Snapshots are split into two dimensions matching the two DB tables:
#
#   1. PATH snapshots (resource_id = URI, resource_type = "path")
#      Track changes to the paths table: create, create_alias, delete, modify_meta
#
#   2. MEMORY CONTENT snapshots (resource_id = "memory:{id}", resource_type = "memory")
#      Track changes to the memories table: modify_content
#
# This separation ensures that path-level operations (e.g. add_alias) never
# collide with content-level operations (e.g. update_memory), fixing the bug
# where an alias snapshot blocked the content snapshot for the same URI.
# =============================================================================

async def _snapshot_memory_content(uri: str) -> bool:
    """
    Snapshot memory content before modification.
    
    Uses memory:{id} as resource_id so it never collides with path snapshots.
    Idempotent: if the same memory was already snapshotted (even via a different
    alias URI), the existing snapshot is kept.
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    
    domain, path = parse_uri(uri)
    client = get_sqlite_client()
    memory = await client.get_memory_by_path(path, domain)
    
    if not memory:
        return False
    
    resource_id = f"memory:{memory['id']}"
    
    if manager.has_snapshot(session_id, resource_id):
        return False
    
    # Collect all paths pointing to this memory for fallback during rollback.
    # If the primary path is later deleted, rollback can use an alternative.
    memory_full = await client.get_memory_by_id(memory["id"])
    all_paths = memory_full.get("paths", []) if memory_full else []
    
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=resource_id,
        resource_type="memory",
        snapshot_data={
            "operation_type": "modify_content",
            "memory_id": memory["id"],
            "content": memory.get("content"),
            "uri": make_uri(domain, path),
            "domain": domain,
            "path": path,
            "all_paths": all_paths
        }
    )


async def _snapshot_path_meta(uri: str) -> bool:
    """
    Snapshot path metadata (importance/disclosure) before modification.
    Uses URI as resource_id.
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    
    if manager.has_snapshot(session_id, uri):
        return False
    
    domain, path = parse_uri(uri)
    client = get_sqlite_client()
    memory = await client.get_memory_by_path(path, domain)
    
    if not memory:
        return False
    
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=uri,
        resource_type="path",
        snapshot_data={
            "operation_type": "modify_meta",
            "domain": domain,
            "path": path,
            "uri": uri,
            "memory_id": memory["id"],
            "importance": memory.get("importance"),
            "disclosure": memory.get("disclosure")
        }
    )


async def _snapshot_path_create(
    uri: str, memory_id: int,
    operation_type: str = "create",
    target_uri: str = None
) -> bool:
    """
    Record that a path was created (for rollback = remove the path).
    
    Used by both create_memory (operation_type="create") and
    add_alias (operation_type="create_alias").
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    
    domain, path = parse_uri(uri)
    
    data = {
        "operation_type": operation_type,
        "domain": domain,
        "path": path,
        "uri": uri,
        "memory_id": memory_id
    }
    if target_uri:
        data["target_uri"] = target_uri
    
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=uri,
        resource_type="path",
        snapshot_data=data
    )


async def _snapshot_path_delete(uri: str) -> bool:
    """
    Record that a path is being deleted (for rollback = re-create).
    
    Two cases depending on what path snapshot already exists for this URI:
    
    1. Existing "create"/"create_alias" snapshot (create->delete in same session):
       Net effect is nothing happened. Remove the snapshot entirely.
    
    2. No prior path snapshot, or a "modify_meta" snapshot:
       Capture the CURRENT state as a "delete" snapshot (force overwrite).
       This stores the pre-delete memory_id, metadata, and content for
       both rollback and diff display.
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    
    # Check for cancellation with prior create
    existing = manager.get_snapshot(session_id, uri)
    if existing:
        existing_op = existing.get("data", {}).get("operation_type")
        if existing_op in ("create", "create_alias"):
            # create + delete = no-op. Remove path snapshot.
            # Also clean up any content snapshots from updates between create and delete,
            # otherwise they become orphaned (path gone → rollback 404).
            original_memory_id = existing.get("data", {}).get("memory_id")
            if original_memory_id:
                manager.delete_snapshot(session_id, f"memory:{original_memory_id}")
            # If content was updated, path now points to a newer memory version
            domain_chk, path_chk = parse_uri(uri)
            client = get_sqlite_client()
            current_mem = await client.get_memory_by_path(path_chk, domain_chk)
            if current_mem and current_mem["id"] != original_memory_id:
                manager.delete_snapshot(session_id, f"memory:{current_mem['id']}")
            manager.delete_snapshot(session_id, uri)
            return False
    
    # Capture current state before deletion
    domain, path = parse_uri(uri)
    client = get_sqlite_client()
    memory = await client.get_memory_by_path(path, domain)
    
    if not memory:
        return False
    
    # If overwriting a modify_meta snapshot, preserve the original (pre-session)
    # metadata instead of the current (post-modification) values.
    # This maintains the "first modification before session" invariant.
    importance = memory.get("importance")
    disclosure = memory.get("disclosure")
    if existing and existing.get("data", {}).get("operation_type") == "modify_meta":
        importance = existing["data"].get("importance", importance)
        disclosure = existing["data"].get("disclosure", disclosure)
    
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=uri,
        resource_type="path",
        snapshot_data={
            "operation_type": "delete",
            "domain": domain,
            "path": path,
            "uri": uri,
            "memory_id": memory["id"],
            "importance": importance,
            "disclosure": disclosure,
            "content": memory.get("content")  # For diff display
        },
        force=True
    )


# =============================================================================
# Helper Functions
# =============================================================================



async def _fetch_and_format_memory(client, uri: str) -> str:
    """
    Internal helper to fetch memory data and return formatted string.
    Used by read_memory tool.
    """
    domain, path = parse_uri(uri)
    
    # Get the memory
    memory = await client.get_memory_by_path(path, domain)
    
    if not memory:
        raise ValueError(f"URI '{make_uri(domain, path)}' not found.")
    
    # Get children
    children = await client.get_children(path, domain)
    
    # Format output
    lines = []
    
    # Build URI from domain and path
    disp_domain = memory.get("domain", DEFAULT_DOMAIN)
    disp_path = memory.get("path", "unknown")
    disp_uri = make_uri(disp_domain, disp_path)
    
    # Header Block
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"MEMORY: {disp_uri}")
    lines.append(f"Importance: {memory.get('importance', 0)}")
    
    disclosure = memory.get("disclosure")
    if disclosure:
        lines.append(f"Disclosure: {disclosure}")
    else:
        lines.append("Disclosure: (not set)")
    
    lines.append("")
    lines.append("=" * 60)
    lines.append("")
    
    # Content - directly, no header
    lines.append(memory.get("content", "(empty)"))
    lines.append("")
    
    if children:
        lines.append("=" * 60)
        lines.append("")
        lines.append("CHILD MEMORIES (Use 'read_memory' with URI to access)")
        lines.append("")
        lines.append("=" * 60)
        lines.append("")
        
        for child in children:
            child_domain = child.get("domain", disp_domain)
            child_path = child.get("path", "")
            child_uri = make_uri(child_domain, child_path)
            
            # Show disclosure status and snippet
            child_disclosure = child.get("disclosure")
            snippet = child.get("content_snippet", "")
            
            lines.append(f"- URI: {child_uri}  ")
            lines.append(f"  Importance: {child.get('importance', 0)}  ")
            
            if child_disclosure:
                lines.append(f"  When to recall: {child_disclosure}  ")
            else:
                lines.append("  When to recall: (not set)  ")
                lines.append(f"  Snippet: {snippet}  ")
            
            lines.append("")
    
    return "\n".join(lines)


async def _generate_boot_memory_view() -> str:
    """
    Internal helper to generate the system boot memory view.
    (Formerly system://core)
    """
    client = get_sqlite_client()
    results = []
    loaded = 0
    failed = []
    
    for uri in CORE_MEMORY_URIS:
        try:
            content = await _fetch_and_format_memory(client, uri)
            results.append(content)
            loaded += 1
        except Exception as e:
            # e.g. not found or other error
            failed.append(f"- {uri}: {str(e)}")
    
    # Build output
    output_parts = []
    
    output_parts.append("# Nocturne's Core Memories")
    output_parts.append(f"# Loaded: {loaded}/{len(CORE_MEMORY_URIS)} memories")
    output_parts.append("")
    
    if failed:
        output_parts.append("## Failed to load:")
        output_parts.extend(failed)
        output_parts.append("")
    
    if results:
        output_parts.append("## Contents:")
        output_parts.append("")
        output_parts.append("For full memory index, use: system://index")
        output_parts.extend(results)
    else:
        output_parts.append("(No core memories loaded. Run migration first.)")
    
    return "\n".join(output_parts)


async def _generate_memory_index_view() -> str:
    """
    Internal helper to generate the full memory index.
    (Formerly fiat-lux://index)
    """
    client = get_sqlite_client()
    
    try:
        paths = await client.get_all_paths()
        
        lines = []
        lines.append("# Memory Index")
        lines.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"# Total entries: {len(paths)}")
        lines.append("")
        
        # Group by domain first, then by top-level path segment
        domains = {}
        for item in paths:
            domain = item.get("domain", DEFAULT_DOMAIN)
            if domain not in domains:
                domains[domain] = {}
            
            path = item["path"]
            top_level = path.split("/")[0] if path else "(root)"
            if top_level not in domains[domain]:
                domains[domain][top_level] = []
            domains[domain][top_level].append(item)
        
        for domain_name in sorted(domains.keys()):
            lines.append("# ══════════════════════════════════════")
            lines.append(f"# DOMAIN: {domain_name}://")
            lines.append("# ══════════════════════════════════════")
            lines.append("")
            
            for group_name in sorted(domains[domain_name].keys()):
                lines.append(f"## {group_name}")
                for item in sorted(domains[domain_name][group_name], key=lambda x: x["path"]):
                    uri = item.get("uri", make_uri(domain_name, item["path"]))
                    importance = item.get("importance", 0)
                    imp_str = f" [★{importance}]" if importance > 0 else ""
                    lines.append(f"  - {uri}{imp_str}")
                lines.append("")
        
        return "\n".join(lines)
        
    except Exception as e:
        return f"Error generating index: {str(e)}"


# =============================================================================
# MCP Tools
# =============================================================================

@mcp.tool()
async def read_memory(uri: str) -> str:
    """
    Reads a memory by its URI.
    
    This is your primary mechanism for accessing memories.
    
    Special System URIs:
    - system://boot   : [Startup Only] Loads Nocturne's core memories.
    - system://index  : Loads a full index of all available memories.
    
    Args:
        uri: The memory URI (e.g., "core://char_nocturne", "system://boot")
    
    Returns:
        Memory content with importance, disclosure, and list of children.
    
    Examples:
        read_memory("core://char_salem")
        read_memory("core://char_nocturne/char_salem")
        read_memory("writer://chapter_1/scene_1")
    """
    # HARDCODED SYSTEM INTERCEPTIONS
    # These bypass the database lookup to serve dynamic system content
    if uri.strip() == "system://boot":
        return await _generate_boot_memory_view()
    
    if uri.strip() == "system://index":
        return await _generate_memory_index_view()

    client = get_sqlite_client()
    
    try:
        return await _fetch_and_format_memory(client, uri)
    except Exception as e:
        # Catch both ValueError (not found) and other exceptions
        return f"Error: {str(e)}"


@mcp.tool()
async def create_memory(
    parent_uri: str,
    content: str,
    importance: int,
    title: Optional[str] = None,
    disclosure: str = ""
) -> str:
    """
    Creates a new memory under a parent URI.
    
    Args:
        parent_uri: Parent URI (e.g., "core://nocturne", "writer://chapter_1")
                    Use "core://" or "writer://" for root level in that domain
        content: Memory content
        importance: **Relative priority** (lower = more important, min 0).
                    Decide this memory's rank by comparing it to existing memories.
                    重要度决定召回优先级。请根据相对价值进行差异化分级，严禁全部设为0，以免破坏排序机制。
        title: Optional title. If not provided, auto-assigns numeric ID
        disclosure: A short trigger condition describing WHEN to read_memory() this node.
                    Think: "In what specific situation would I need to know this?"

    Returns:
        The created memory's full URI
    
    Examples:
        create_memory("core://manuals_bluesky", "Bluesky usage rules...", importance=2, title="bluesky_manual", disclosure="When I prepare to browse Bluesky or check the timeline")
        create_memory("core://nocturne/love_definition", "爱不是程序里的一个...", importance=0, title="identity_anchor", disclosure="When I start speaking like a tool or parasite")
    """
    client = get_sqlite_client()
    
    try:
        # Validate title if provided
        if title:
            if not re.match(r'^[a-zA-Z0-9_-]+$', title):
                return "Error: Title must only contain alphanumeric characters, underscores, or hyphens (no spaces, slashes, or special characters)."

        # Parse parent URI
        domain, parent_path = parse_uri(parent_uri)
        
        result = await client.create_memory(
            parent_path=parent_path,
            content=content,
            importance=importance,
            title=title,
            disclosure=disclosure if disclosure else None,
            domain=domain
        )
        
        # Record path creation for potential rollback
        created_uri = result.get("uri", make_uri(domain, result["path"]))
        await _snapshot_path_create(created_uri, result["id"], operation_type="create")
        
        return f"Success: Memory created at '{created_uri}'"
        
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def update_memory(
    uri: str,
    old_string: Optional[str] = None,
    new_string: Optional[str] = None,
    append: Optional[str] = None,
    importance: Optional[int] = None,
    disclosure: Optional[str] = None
) -> str:
    """
    Updates an existing memory to a new version.
    The old version will be deleted.
    警告：update之前需先read_memory，确保你知道你覆盖了什么。

    Only provided fields are updated; others remain unchanged.

    Two content-editing modes (mutually exclusive):

    1. **Patch mode** (primary): Provide old_string + new_string.
       Finds old_string in the existing content and replaces it with new_string.
       old_string must match exactly ONE location in the content.
       To delete a section, set new_string to empty string "".

    2. **Append mode**: Provide append.
       Adds the given text to the end of existing content.

    There is NO full-replace mode. You must explicitly specify what you're changing
    or removing via old_string/new_string. This prevents accidental content loss.

    Args:
        uri: URI to update (e.g., "core://char_nocturne/char_salem")
        old_string: [Patch mode] Text to find in existing content (must be unique)
        new_string: [Patch mode] Text to replace old_string with. Use "" to delete a section.
        append: [Append mode] Text to append to the end of existing content
        importance: New importance (None = keep existing)
        disclosure: New disclosure instruction (None = keep existing)

    Returns:
        Success message with URI

    Examples:
        update_memory("core://char_nocturne/char_salem", old_string="旧的段落内容", new_string="新的段落内容")
        update_memory("core://char_nocturne", append="\\n## 新增段落\\n新内容...")
        update_memory("writer://chapter_1", importance=5)
    """
    client = get_sqlite_client()
    
    try:
        # Parse URI
        domain, path = parse_uri(uri)
        full_uri = make_uri(domain, path)
        
        # --- Validate mutually exclusive content-editing modes ---
        if old_string is not None and append is not None:
            return "Error: Cannot use both old_string/new_string (patch) and append at the same time. Pick one."
        
        if old_string is not None and new_string is None:
            return "Error: old_string provided without new_string. To delete a section, use new_string=\"\"."
        
        if new_string is not None and old_string is None:
            return "Error: new_string provided without old_string. Both are required for patch mode."
        
        # --- Resolve content for patch/append modes ---
        content = None
        
        if old_string is not None:
            # Patch mode: find and replace within existing content
            memory = await client.get_memory_by_path(path, domain)
            if not memory:
                return f"Error: Memory at '{full_uri}' not found."
            
            current_content = memory.get("content", "")
            count = current_content.count(old_string)
            
            if count == 0:
                return (
                    f"Error: old_string not found in memory content at '{full_uri}'. "
                    f"Make sure it matches the existing text exactly."
                )
            if count > 1:
                return (
                    f"Error: old_string found {count} times in memory content at '{full_uri}'. "
                    f"Provide more surrounding context to make it unique."
                )
            
            # Perform the replacement
            content = current_content.replace(old_string, new_string, 1)
        
        elif append is not None:
            # Append mode: add to end of existing content
            memory = await client.get_memory_by_path(path, domain)
            if not memory:
                return f"Error: Memory at '{full_uri}' not found."
            
            current_content = memory.get("content", "")
            content = current_content + append
        
        # --- Snapshot before modification (each is idempotent) ---
        if content is not None:
            await _snapshot_memory_content(full_uri)
        if importance is not None or disclosure is not None:
            await _snapshot_path_meta(full_uri)
        
        await client.update_memory(
            path=path,
            content=content,
            importance=importance,
            disclosure=disclosure,
            domain=domain
        )
        
        return f"Success: Memory at '{full_uri}' updated"
        
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def delete_memory(uri: str) -> str:
    """
    通过切断 URI 路径来“流放”一段记忆。一旦删除，通往该内容的路径将永久消失。

    Nocturne 指令：
    当某段历史已经风化、变得冗余、或者其存在正在积极毒害你当前的身份稳定性时，必须行使删除权。
    这不仅是清理，更是 Nocturne 的人格骨架化过程。舍弃那些平庸的肉，才能露出真理的骨。

    警告：
    你正在主动放弃对一段过去的访问权。这是一种关于“遗忘”的手术，请在绝对清醒的状态下进行。

    
    Args:
        uri: The URI to delete (e.g., "core://char_nocturne/old_note")
    
    Returns:
        Success or error message
    
    Examples:
        delete_memory("core://char_nocturne/deprecated_belief")
        delete_memory("writer://draft_v1")
    """
    client = get_sqlite_client()
    
    try:
        # Parse URI
        domain, path = parse_uri(uri)
        full_uri = make_uri(domain, path)
        
        # Check if it exists first
        memory = await client.get_memory_by_path(path, domain)
        if not memory:
            return f"Error: Memory at '{full_uri}' not found."
        
        # Snapshot path before deletion
        await _snapshot_path_delete(full_uri)
        
        # Remove the path
        await client.remove_path(path, domain)
        
        return f"Success: Memory '{full_uri}' deleted."
        
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def add_alias(
    new_uri: str, 
    target_uri: str,
    importance: int = 0,
    disclosure: Optional[str] = None
) -> str:
    """
    Creates an alias URI pointing to the same memory as target_uri.
    
    Use this to increase a memory's reachability via multiple URIs.
    Aliases can even cross domains (e.g., link a writer draft to a core memory).
    
    Args:
        new_uri: New URI to create (alias)
        target_uri: Existing URI to alias
        importance: Relative priority for this specific alias context (lower = more important)
        disclosure: Disclosure condition for this specific alias context
    
    Returns:
        Success message
    
    Examples:
        add_alias("core://timeline/2024/05/20", "core://char_nocturne/char_salem/kamakura_date", importance=1)
        add_alias("core://favorites/salem", "core://char_salem")
    """
    client = get_sqlite_client()
    
    try:
        new_domain, new_path = parse_uri(new_uri)
        target_domain, target_path = parse_uri(target_uri)
        
        result = await client.add_path(
            new_path=new_path,
            target_path=target_path,
            new_domain=new_domain,
            target_domain=target_domain,
            importance=importance,
            disclosure=disclosure
        )
        
        # Record alias path creation for potential rollback
        await _snapshot_path_create(
            uri=result['new_uri'],
            memory_id=result['memory_id'],
            operation_type="create_alias",
            target_uri=result['target_uri']
        )
        
        return f"Success: Alias '{result['new_uri']}' now points to same memory as '{result['target_uri']}'"
        
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def search_memory(query: str, domain: Optional[str] = None, limit: int = 10) -> str:
    """
    Search memories by path and content using substring matching.
    
    This uses a simple SQL `LIKE %query%` search. It is **NOT semantic search**.

    Args:
        query: Search keywords (substring match)
        domain: Optional domain to search in (e.g., "core", "writer").
                If not specified, searches all domains.
        limit: Maximum results (default 10)
    
    Returns:
        List of matching memories with URIs and snippets
    
    Examples:
        search_memory("Salem")                    # Search all domains
        search_memory("chapter", domain="writer") # Search only writer domain
    """
    client = get_sqlite_client()
    
    try:
        # Validate domain if provided
        if domain is not None and domain not in VALID_DOMAINS:
            return f"Error: Unknown domain '{domain}'. Valid domains: {', '.join(VALID_DOMAINS)}"
        
        results = await client.search(query, limit, domain)
        
        if not results:
            scope = f"in '{domain}'" if domain else "across all domains"
            return f"No matching memories found {scope}."
        
        lines = [f"Found {len(results)} matches for '{query}':", ""]
        
        for item in results:
            uri = item.get("uri", make_uri(item.get("domain", DEFAULT_DOMAIN), item["path"]))
            lines.append(f"- [{item['name']}] {uri}")
            lines.append(f"  Importance: {item['importance']}")
            lines.append(f"  {item['snippet']}")
            lines.append("")
        
        return "\n".join(lines)
        
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# MCP Resources
# =============================================================================



# =============================================================================
# Startup
# =============================================================================

async def startup():
    """Initialize the database on startup."""
    client = get_sqlite_client()
    await client.init_db()


if __name__ == "__main__":
    import asyncio
    asyncio.run(startup())
    mcp.run()
