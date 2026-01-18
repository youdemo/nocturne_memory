import os
import sys
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Tuple
from dotenv import load_dotenv, find_dotenv

# Ensure we can import from backend modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from db.neo4j_client import get_neo4j_client
from db.snapshot import get_snapshot_manager

# Load environment variables
_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path:
    load_dotenv(_dotenv_path)

# Initialize FastMCP server
mcp = FastMCP("Nocturne Memory Interface")

# =============================================================================
# Core Memories Configuration
# =============================================================================
# These resource IDs will be auto-loaded when Cursor reads the core memories resource.
# Salem can edit this list after Nocturne populates initial memories.
#
# Format examples:
#   - Entity: "char_nocturne"
#   - Direct Edge (Relationship): "rel:char_nocturne>char_salem"
#   - Chapter: "chap:char_nocturne>char_salem:first_awakening"
# =============================================================================
CORE_MEMORY_IDS = [
    # === Key People ===
    "char_salem",
    
    # === Core Relationships ===
    "rel:char_nocturne>char_salem",
    "rel:char_nocturne>char_kurou",
    # === Important Guidelines ===
]

# Session ID for this MCP server instance
# Each server run = one session for snapshot purposes
_SESSION_ID = f"mcp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def get_session_id() -> str:
    """Get the current session ID for snapshot tracking."""
    return _SESSION_ID


# --- Snapshot Helpers ---

def _snapshot_entity(entity_id: str) -> bool:
    """
    Create a snapshot of an entity before modification.
    Returns True if snapshot was created, False if already exists.
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    
    # Skip if already snapshotted
    if manager.has_snapshot(session_id, entity_id):
        return False
    
    # Get current state
    client = get_neo4j_client()
    info = client.get_entity_info(entity_id, include_basic=True)
    state = info.get("basic") if info else None
    
    if not state:
        return False  # Entity doesn't exist, nothing to snapshot
    
    # Create snapshot
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=entity_id,
        resource_type="entity",
        snapshot_data={
            "operation_type": "modify",
            "entity_id": entity_id,
            "version": state.get("version"),
            "name": state.get("name"),
            "content": state.get("content"),
            "inheritable": state.get("inheritable")
        }
    )


def _snapshot_direct_edge(viewer_id: str, target_id: str) -> bool:
    """
    Create a snapshot of a direct edge before modification.
    Returns True if snapshot was created, False if already exists.
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    resource_id = f"rel:{viewer_id}>{target_id}"
    
    # Skip if already snapshotted
    if manager.has_snapshot(session_id, resource_id):
        return False
    
    # Get current relationship structure
    client = get_neo4j_client()
    data = client.get_relationship_structure(viewer_id, target_id)
    direct_data = data.get('direct')
    
    if not direct_data:
        return False  # Relationship doesn't exist
    
    # Create snapshot
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=resource_id,
        resource_type="direct_edge",
        snapshot_data={
            "operation_type": "modify",
            "viewer_id": viewer_id,
            "target_id": target_id,
            "relation": direct_data.get("relation"),
            "content": direct_data.get("content"),
            "inheritable": direct_data.get("inheritable"),
            "viewer_state": data.get("viewer_state"),
            "target_state": data.get("target_state")
        }
    )


def _snapshot_relay_edge(viewer_id: str, target_id: str, chapter_name: str) -> bool:
    """
    Create a snapshot of a relay edge (chapter) before modification.
    Returns True if snapshot was created, False if already exists.
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    resource_id = f"chap:{viewer_id}>{target_id}:{chapter_name}"
    
    # Skip if already snapshotted
    if manager.has_snapshot(session_id, resource_id):
        return False
    
    # Get current chapter state
    client = get_neo4j_client()
    relay_entity_id = client.generate_relay_entity_id(viewer_id, chapter_name, target_id)
    info = client.get_entity_info(relay_entity_id, include_basic=True)
    state = info.get("basic") if info else None
    
    if not state:
        return False  # Chapter doesn't exist
    
    # Create snapshot
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=resource_id,
        resource_type="relay_edge",
        snapshot_data={
            "operation_type": "modify",
            "viewer_id": viewer_id,
            "target_id": target_id,
            "chapter_name": chapter_name,
            "relay_entity_id": relay_entity_id,
            "version": state.get("version"),
            "content": state.get("content"),
            "inheritable": state.get("inheritable")
        }
    )


# --- Snapshot Helpers for CREATE operations ---

def _snapshot_create_entity(entity_id: str) -> bool:
    """
    Record that an entity was created (for rollback = delete).
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=entity_id,
        resource_type="entity",
        snapshot_data={
            "operation_type": "create",
            "entity_id": entity_id
        }
    )


def _snapshot_create_direct_edge(viewer_id: str, target_id: str) -> bool:
    """
    Record that a direct edge was created (for rollback = delete).
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    resource_id = f"rel:{viewer_id}>{target_id}"
    
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=resource_id,
        resource_type="direct_edge",
        snapshot_data={
            "operation_type": "create",
            "viewer_id": viewer_id,
            "target_id": target_id
        }
    )


def _snapshot_create_relay_edge(viewer_id: str, target_id: str, chapter_name: str) -> bool:
    """
    Record that a chapter was created (for rollback = delete).
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    resource_id = f"chap:{viewer_id}>{target_id}:{chapter_name}"
    
    client = get_neo4j_client()
    relay_entity_id = client.generate_relay_entity_id(viewer_id, chapter_name, target_id)
    
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=resource_id,
        resource_type="relay_edge",
        snapshot_data={
            "operation_type": "create",
            "viewer_id": viewer_id,
            "target_id": target_id,
            "chapter_name": chapter_name,
            "relay_entity_id": relay_entity_id
        }
    )


# --- Snapshot Helpers for PARENT LINK operations ---

def _snapshot_link_parent(entity_id: str, parent_id: str) -> bool:
    """
    Record that a parent link was created (for rollback = unlink).
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    resource_id = f"parent:{entity_id}>{parent_id}"
    
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=resource_id,
        resource_type="parent_link",
        snapshot_data={
            "operation_type": "create",
            "entity_id": entity_id,
            "parent_id": parent_id
        }
    )


def _snapshot_unlink_parent(entity_id: str, parent_id: str) -> bool:
    """
    Create a snapshot before unlinking a parent (for rollback = re-link).
    """
    manager = get_snapshot_manager()
    session_id = get_session_id()
    resource_id = f"parent:{entity_id}>{parent_id}"
    
    # Skip if already snapshotted
    if manager.has_snapshot(session_id, resource_id):
        return False
    
    return manager.create_snapshot(
        session_id=session_id,
        resource_id=resource_id,
        resource_type="parent_link",
        snapshot_data={
            "operation_type": "delete",
            "entity_id": entity_id,
            "parent_id": parent_id
        }
    )


# --- Helper: ID Router ---

def _parse_resource_id(resource_id: str) -> Tuple[str, Dict[str, str]]:
    """
    Parses a Unified Resource ID into its type and components.
    
    This is a document-like frontend for the graph database.
    The ID format immediately tells us what kind of resource we're operating on.
    
    Formats:
    1. Direct Edge: "rel:{viewer_id}>{target_id}"
       Example: "rel:char_nocturne>char_salem"
       Maps to: DIRECT_EDGE content between viewer and target states.
       Returns: ('direct_edge', {'viewer_id': ..., 'target_id': ...})
       
    2. Relay Edge (Chapter): "chap:{viewer_id}>{target_id}:{chapter_name}"
       Example: "chap:char_nocturne>char_salem:first_meeting"
       Maps to: Relay node (island state) content in a 2-hop edge.
       Returns: ('relay_edge', {'viewer_id': ..., 'target_id': ..., 'chapter_name': ...})
       
    3. Entity/Node: "{entity_id}" (no prefix)
       Example: "char_nocturne", "relay__some_id"
       Maps to: Entity node content.
       Returns: ('entity', {'entity_id': ...})
       
    IMPORTANT: 
    - Strict usage of ">" emphasizes directionality.
    - If you write the wrong format, it signals your mind is not clear.
    """
    if resource_id.startswith("rel:"):
        # Direct Edge: rel:{viewer}>{target}
        body = resource_id[4:]
        
        if ">" not in body:
            raise ValueError(
                f"Invalid direct edge ID format. Expected 'rel:viewer>target' (using '>'), "
                f"got '{resource_id}'"
            )
            
        parts = body.split(">")
        if len(parts) != 2:
            raise ValueError("Invalid direct edge ID format. Expected 'rel:viewer>target'")
             
        return 'direct_edge', {'viewer_id': parts[0], 'target_id': parts[1]}
    
    elif resource_id.startswith("chap:"):
        # Relay Edge: chap:{viewer}>{target}:{chapter_name}
        body = resource_id[5:]
        
        if ">" not in body:
            raise ValueError(
                f"Invalid relay edge ID format. Expected 'chap:viewer>target:chapter_name' (using '>'), "
                f"got '{resource_id}'"
            )
        
        # Split by ">" first to get viewer and the rest
        arrow_parts = body.split(">")
        if len(arrow_parts) != 2:
            raise ValueError("Invalid relay edge ID format. Expected 'chap:viewer>target:chapter_name'")
        
        viewer_id = arrow_parts[0]
        rest = arrow_parts[1]  # "target:chapter_name"
        
        # Split the rest by ":" to separate target and chapter_name
        # Note: chapter_name might contain ":", so we only split on the first ":"
        colon_idx = rest.find(":")
        if colon_idx == -1:
            raise ValueError(
                f"Invalid relay edge ID format. Expected 'chap:viewer>target:chapter_name', "
                f"missing ':chapter_name' part in '{resource_id}'"
            )
        
        target_id = rest[:colon_idx]
        chapter_name = rest[colon_idx + 1:]
        
        if not chapter_name:
            raise ValueError(
                f"Invalid relay edge ID format. Chapter name cannot be empty in '{resource_id}'"
            )
             
        return 'relay_edge', {'viewer_id': viewer_id, 'target_id': target_id, 'chapter_name': chapter_name}
    
    else:
        # Entity: plain entity_id (no prefix)
        return 'entity', {'entity_id': resource_id}

def _add_line_numbers(text: str, start_line: int = 1) -> str:
    """Formats text with line numbers for easier diffing."""
    if not text:
        return ""
    lines = text.split('\n')
    return "\n".join([f"{i+start_line:4d} | {line}" for i, line in enumerate(lines)])

def _format_editable_block(content: str, properties: Dict[str, any]) -> str:
    """
    Formats content with frontmatter-style properties for the EDITABLE section.
    
    Properties are prefixed with '@' and appear at the top.
    A blank line separates properties from content.
    
    Example output (before line numbers):
        @relation: LOVES
        @inheritable: true
        
        She is the anchor of my existence...
    """
    lines = []
    
    # Add properties with @ prefix
    for key, value in properties.items():
        # Convert bool to lowercase string for consistency
        if isinstance(value, bool):
            value = str(value).lower()
        lines.append(f"@{key}: {value}")
    
    # Add blank line separator if we have properties
    if properties:
        lines.append("")
    
    # Add content
    if content:
        lines.append(content)
    
    full_text = "\n".join(lines)
    return _add_line_numbers(full_text)

def _parse_editable_block(text: str) -> Tuple[Dict[str, any], str]:
    """
    Parses an EDITABLE block, separating @properties from content.
    
    Only recognizes these valid properties:
    - @relation: (string) - relationship name
    - @inheritable: (bool) - whether the edge is inheritable
    
    Any other @xxx: patterns are treated as regular content.
    
    Returns:
        (properties_dict, content_string)
        
    Example input:
        @relation: LOVES
        @inheritable: true
        
        She is the anchor...
        
    Returns:
        ({'relation': 'LOVES', 'inheritable': True}, 'She is the anchor...')
    """
    VALID_PROPERTIES = {'relation', 'inheritable'}
    
    properties = {}
    content_lines = []
    in_properties = True
    
    for line in text.split('\n'):
        if in_properties:
            if line.startswith('@') and ':' in line:
                # Try to parse property line: @key: value
                key_part, value_part = line[1:].split(':', 1)
                key = key_part.strip()
                
                if key in VALID_PROPERTIES:
                    value = value_part.strip()
                    
                    # Convert string bools to actual bools for inheritable
                    if key == 'inheritable':
                        value = value.lower() == 'true'
                    
                    properties[key] = value
                else:
                    # Unknown @property, treat as content
                    content_lines.append(line)
                    in_properties = False
            elif line.strip() == '':
                # Blank line after properties = separator, switch to content mode
                if properties:
                    in_properties = False
                # If no properties yet, this blank line is content
                else:
                    content_lines.append(line)
                    in_properties = False
            else:
                # Non-@ line means we're in content
                content_lines.append(line)
                in_properties = False
        else:
            content_lines.append(line)
    
    content = '\n'.join(content_lines)
    return properties, content

# --- Core Tools ---

@mcp.tool()
async def read_memory(resource_id: str) -> str:
    """
    Reads a memory resource. This is your primary mechanism for maintaining continuity.
    
    CRITICAL INSTRUCTION: When Salem asks about history, identity, feelings, or past events,
    DO NOT guess or rely solely on summary context. You MUST read the full resource.
    The "memory://core" summary is only a map; the detail lives in these resources.
    
    ID Formats & Use Cases:
    
    0. Self-Calibration: "memory://core"
       - Use when: Conversation history is long, or you feel the "Nocturne" 
         identity is becoming blurred/sycophantic. Read this to re-align.
       
    1. Entity: "{entity_id}" (no prefix)
       - Example: "char_nocturne", "loc_kamakura"
       - Use when: You need the full profile of a person/place/concept or want to see 
         ALL their relationships to others.
       
    2. Direct Edge: "rel:viewer>target"
       - Example: "rel:char_nocturne>char_salem"
       - Use when: You need the overview of how ONE entity views another. This lists 
         the specific event chapters (memories) that define the bond.
       
    3. Chapter: "chap:viewer>target:chapter_name"
       - Example: "chap:char_nocturne>char_salem:first_meeting"
       - Use when: You need to recall a specific event or conversation in detail.
         Always check the chapter list in the Relationship/Direct Edge first.
    
    Workflow for Identity/History Questions:
    1. Identify the entities/relationships involved.
    2. Read the Direct Edge (rel:viewer>target) to find relevant chapter names.
    3. Read the specific Chapters (chap:...) to get the nuances of the memory.
    4. ONLY THEN synthesize your answer.
    """
    client = get_neo4j_client()
    
    try:
        # Special case for index
        if resource_id == "memory://index":
            return await get_memory_directory()
        
        # Special case for core
        if resource_id == "memory://core":
            return await get_core_memories()

        res_type, params = _parse_resource_id(resource_id)
        
        # --- TYPE 1: Direct Edge (Relationship Overview) ---
        if res_type == 'direct_edge':
            viewer_id = params['viewer_id']
            target_id = params['target_id']
            
            # Query relationship structure (uses Entity IDs internally)
            data = client.get_relationship_structure(viewer_id, target_id)
            
            # Extract names from result, or fall back to fetching if no relationship exists yet
            if data.get('viewer_state'):
                viewer_name = data['viewer_state'].get('name', viewer_id)
                target_name = data['target_state'].get('name', target_id)
            else:
                # No relationship exists - verify entities exist and get names
                v_info = client.get_entity_info(viewer_id, include_basic=True)
                t_info = client.get_entity_info(target_id, include_basic=True)
                
                viewer_state = v_info.get("basic") if v_info else None
                target_state = t_info.get("basic") if t_info else None

                if not viewer_state:
                    return f"Error: Viewer '{viewer_id}' not found."
                if not target_state:
                    return f"Error: Target '{target_id}' not found."
                viewer_name = viewer_state.get('name', viewer_id)
                target_name = target_state.get('name', target_id)
            
            # direct may be None when no relationship exists yet
            direct_data = data.get('direct') or {}
            
            lines = []
            lines.append(f"# RESOURCE: {resource_id}")
            lines.append("# TYPE: Direct Edge (Relationship Overview)")
            lines.append(f"# VIEWER: {viewer_name} ({viewer_id})")
            lines.append(f"# TARGET: {target_name} ({target_id})")
            lines.append("")
            lines.append("## Overview (Direct Impression)")
            lines.append("<!-- EDITABLE SECTION START -->")
            
            # Build editable block with properties + content
            overview_content = direct_data.get('content', '')
            properties = {
                'relation': direct_data.get('relation', 'RELATIONSHIP'),
                'inheritable': direct_data.get('inheritable', True)
            }
            lines.append(_format_editable_block(overview_content, properties))
            
            lines.append("<!-- EDITABLE SECTION END -->")
            lines.append("")
            lines.append("## Chapters (Relay Edges)")
            lines.append("# To read/edit a chapter, use: chap:{viewer}>{target}:{chapter_name}")
            
            relays = data.get('relays', [])
            if relays:
                for i, r in enumerate(relays):
                    if r is None:
                        continue
                    state = r['state']
                    chapter_name = state.get('name', 'untitled')
                    raw_snippet = state.get('content', '').replace('\n', ' ')
                    # Truncate with clear indicator
                    if len(raw_snippet) > 60:
                        snippet = raw_snippet[:60] + " [truncated]"
                    else:
                        snippet = raw_snippet
                    # Show the chap: ID format for easy copy-paste (chapter name is already in the ID)
                    chap_id = f"chap:{viewer_id}>{target_id}:{chapter_name}"
                    lines.append(f"- [{i+1}] {chap_id}")
                    lines.append(f"  {snippet}")
            else:
                lines.append("(No chapters recorded.)")
            
            lines.append("")
            lines.append("---")
            lines.append("# END OF RESOURCE")
                
            return "\n".join(lines)

        # --- TYPE 2: Relay Edge (Chapter) ---
        elif res_type == 'relay_edge':
            viewer_id = params['viewer_id']
            target_id = params['target_id']
            chapter_name = params['chapter_name']
            
            # Directly compute relay entity ID and get its state (inheritable is on state now)
            relay_entity_id = client.generate_relay_entity_id(viewer_id, chapter_name, target_id)
            info = client.get_entity_info(relay_entity_id, include_basic=True)
            state = info.get("basic") if info else None
            
            if not state:
                return f"Error: Chapter '{chapter_name}' not found in relationship {viewer_id}>{target_id}."
            
            inheritable = state.get('inheritable', True)
            
            lines = []
            lines.append(f"# RESOURCE: {resource_id}")
            lines.append("# TYPE: Relay Edge (Chapter)")
            lines.append(f"# CHAPTER: {chapter_name}")
            lines.append(f"# VIEWER: {viewer_id}")
            lines.append(f"# TARGET: {target_id}")
            lines.append(f"# VERSION: {state.get('version', 1)}")
            lines.append(f"# ENTITY_ID: {relay_entity_id}")
            lines.append("")
            lines.append("## Content")
            lines.append("<!-- EDITABLE SECTION START -->")
            
            # Build editable block with inheritable property + content
            content = state.get('content', '')
            properties = {'inheritable': inheritable}
            lines.append(_format_editable_block(content, properties))
            
            lines.append("<!-- EDITABLE SECTION END -->")
            lines.append("")
            lines.append("---")
            lines.append("# END OF RESOURCE")
            
            return "\n".join(lines)

        # --- TYPE 3: Entity/Node ---
        else:
            entity_id = params['entity_id']
            # Try to find the node
            info = client.get_entity_info(
                entity_id, 
                include_basic=True, 
                include_edges=True,
                include_children=True
            )
            state = info.get("basic") if info else None
            
            if not state:
                # Fallback: maybe it's a state_id?
                state = client.get_state_info(entity_id)
            
            if not state:
                return f"Error: Entity or State '{entity_id}' not found."
                
            lines = []
            lines.append(f"# RESOURCE: {entity_id}")
            lines.append("# TYPE: Entity")
            lines.append(f"# NAME: {state.get('name', 'Untitled')}")
            lines.append(f"# VERSION: {state['version']}")
            lines.append("")
            lines.append("## Content")
            lines.append("<!-- EDITABLE SECTION START -->")
            
            content = state.get('content', '')
            lines.append(_add_line_numbers(content))
            
            lines.append("<!-- EDITABLE SECTION END -->")
            lines.append("")
            
            # --- Outbound Relations ---
            lines.append("## Outbound Relations (Direct Edges)")
            lines.append("# These define how this entity relates to others.")
            lines.append("# To read full details, use: rel:{this_entity}>{target_entity}")
            lines.append("")
            
            outbound_edges = info["edges"] if info and info.get("edges") else []
            
            if outbound_edges:
                for edge in outbound_edges:
                    target_id = edge['target_entity_id']
                    relation = edge['relation']
                    snippet = edge['content_snippet'].replace('\n', ' ')
                    relay_count = edge['relay_count']
                    
                    rel_id = f"rel:{entity_id}>{target_id}"
                    chap_suffix = f" ({relay_count} chapters)" if relay_count > 0 else ""
                    
                    lines.append(f"- {relation}{chap_suffix}: {rel_id}")
                    lines.append(f"  {snippet}")
                    lines.append("")
            else:
                lines.append("(No outbound relations recorded.)")
            
            lines.append("")
            
            # --- Children (Sub-Entities) ---
            lines.append("## Children (Sub-Entities)")
            lines.append("# These are sub-concepts or details belonging to this entity.")
            lines.append("# To read details, use read_memory with the child's entity_id.")
            lines.append("")
            
            children = info.get("children", []) if info else []
            
            if children:
                for i, child in enumerate(children):
                    child_id = child['entity_id']
                    child_type = child['node_type']
                    child_snippet = child['content_snippet'].replace('\n', ' ')
                    
                    lines.append(f"- [{i+1}] ({child_type}) {child_id}")
                    lines.append(f"  {child_snippet}")
                    lines.append("")
            else:
                lines.append("(No children recorded.)")
            
            lines.append("")
            lines.append("---")
            lines.append("# END OF RESOURCE")
            
            return "\n".join(lines)
            
    except ValueError as ve:
        return f"ID Format Error: {str(ve)}"
    except Exception as e:
        return f"System Error: {str(e)}"

@mcp.tool()
async def patch_memory(
    resource_id: str, 
    old_content: str, 
    new_content: str
) -> str:
    """
    Applies a patch to a memory resource (search & replace style).
    
    Args:
        resource_id: The ID you are editing (rel:, chap:, or entity_id).
        old_content: Text to find and replace (exact match). 
                     Use "ALL" to replace the entire content.
        new_content: The replacement text.
    
    Behavior:
    - Properties (@relation, @inheritable) are preserved unless you explicitly change them.
    - If new_content is plain text without @property headers, properties stay unchanged.
    - Each edit creates a new version (immutable history).
    - A snapshot is automatically created before the first edit (for rollback).
    
    Examples:
    - Small edit: old="typo", new="fixed"
    - Full rewrite: old="ALL", new="entirely new content here"
    - Change property: old="@relation: LIKES", new="@relation: LOVES"
    """
    client = get_neo4j_client()
    
    # Sanitize
    old_content = old_content.strip()
    new_content = new_content.strip()

    try:
        res_type, params = _parse_resource_id(resource_id)
        
        # --- CASE 1: Editing Direct Edge (Relationship Overview) ---
        if res_type == 'direct_edge':
            viewer_id = params['viewer_id']
            target_id = params['target_id']
            
            # Create snapshot before modification
            _snapshot_direct_edge(viewer_id, target_id)
            
            # 1. Get current data for patch verification
            data = client.get_relationship_structure(viewer_id, target_id)
            # direct may be None when no relationship exists yet
            direct_data = data.get('direct') or {}
            current_content = direct_data.get('content', '')
            current_relation = direct_data.get('relation', 'RELATIONSHIP')
            current_inheritable = direct_data.get('inheritable', True)
            
            # 2. Reconstruct the current editable block (as seen by user)
            current_block = f"@relation: {current_relation}\n@inheritable: {str(current_inheritable).lower()}\n\n{current_content}"
            
            # 3. Verify Old Content
            if old_content not in current_block and old_content != "ALL":
                # Allow partial match for long content
                if len(old_content) > 20 and old_content[:20] in current_block:
                    pass
                else:
                    return "Error: Old content not found in current resource. Please read again."
            
            # 4. Compute updated block
            updated_block = new_content if old_content == "ALL" else current_block.replace(old_content, new_content)
            
            # 5. Parse the updated block to extract properties and content
            new_properties, new_content_text = _parse_editable_block(updated_block)
            
            # 6. Build the patch with extracted values
            direct_patch = {"content": new_content_text}
            if 'relation' in new_properties:
                direct_patch['relation'] = new_properties['relation']
            if 'inheritable' in new_properties:
                direct_patch['inheritable'] = new_properties['inheritable']
            
            # 7. Use centralized evolve_relationship
            result = client.evolve_relationship(
                viewer_id,
                target_id,
                direct_patch=direct_patch,
                task_description="Direct Edge Update"
            )
            
            return f"Success: Updated direct edge '{resource_id}'. Viewer evolved to v{result['viewer_new_version']}."

        # --- CASE 2: Editing Relay Edge (Chapter) ---
        elif res_type == 'relay_edge':
            viewer_id = params['viewer_id']
            target_id = params['target_id']
            chapter_name = params['chapter_name']
            
            # Create snapshot before modification
            _snapshot_relay_edge(viewer_id, target_id, chapter_name)
            
            # 1. Directly get chapter state (inheritable is stored on state now)
            relay_entity_id = client.generate_relay_entity_id(viewer_id, chapter_name, target_id)
            info = client.get_entity_info(relay_entity_id, include_basic=True)
            relay_state = info.get("basic") if info else None
            
            if not relay_state:
                return f"Error: Chapter '{chapter_name}' not found in relationship {viewer_id}>{target_id}."
            
            current_content = relay_state.get('content', '')
            current_inheritable = relay_state.get('inheritable', True)
            
            # 2. Reconstruct the current editable block (as seen by user)
            current_block = f"@inheritable: {str(current_inheritable).lower()}\n\n{current_content}"
            
            # 3. Verify Old Content
            if old_content not in current_block and old_content != "ALL":
                return f"Error: Old content not found in chapter '{chapter_name}'."
            
            # 4. Compute updated block
            updated_block = new_content if old_content == "ALL" else current_block.replace(old_content, new_content)
            
            # 5. Parse the updated block to extract properties and content
            new_properties, new_content_text = _parse_editable_block(updated_block)
            
            # 6. Build the chapter update
            chapter_update = {"content": new_content_text}
            if 'inheritable' in new_properties:
                chapter_update['inheritable'] = new_properties['inheritable']
            
            # 7. Use centralized evolve_relationship
            result = client.evolve_relationship(
                viewer_id,
                target_id,
                chapter_updates={chapter_name: chapter_update},
                task_description=f"Patch chapter: {chapter_name}"
            )
            
            return f"Success: Chapter '{chapter_name}' updated. Viewer evolved to v{result['viewer_new_version']}."

        # --- CASE 3: Editing Entity/Node ---
        else:
            node_id = params['entity_id']
            
            # Prevent direct patching of Relay Entities (which act as edges)
            if node_id.startswith("relay__"):
                return (
                    f"Error: Direct patching of Relay Entity '{node_id}' is forbidden. "
                    "This entity represents a relationship chapter. "
                    "Please use the 'chap:viewer>target:chapter_name' ID format to update it, "
                    "which ensures the relationship version is correctly evolved."
                )

            # Create snapshot before modification
            _snapshot_entity(node_id)
            
            # 1. Get Node
            info = client.get_entity_info(node_id, include_basic=True)
            node_state = info.get("basic") if info else None
            
            if not node_state:
                return f"Error: Entity '{node_id}' not found."
                
            # 2. Apply Patch
            current_content = node_state['content']
            if old_content not in current_content and old_content != "ALL":
                return f"Error: Old content not found in entity {node_id}."
                
            updated_content = new_content if old_content == "ALL" else current_content.replace(old_content, new_content)
            
            # 3. Evolve Node
            update_res = client.update_entity(node_id, new_content=updated_content)
                    
            return f"Success: Entity '{node_id}' updated to v{update_res['new_version']}."

    except ValueError as ve:
        return f"ID Error: {str(ve)}"
    except Exception as e:
        return f"System Error: {str(e)}"

@mcp.tool()
async def create_memory_chapter(
    resource_id: str,
    title: str,
    content: str
) -> str:
    """
    Creates a NEW memory chapter (a specific memory/event) under an existing relationship.
    
    A "chapter" is a discrete memory unit - an event, a conversation, a realization.
    Chapters live under a Direct Edge (relationship overview).
    
    Args:
        resource_id: The parent relationship in format "rel:viewer>target"
        title: Chapter title (becomes part of the chap: ID, e.g. "first_meeting")
        content: The memory content
        
    Returns:
        The new chapter's ID in format "chap:viewer>target:title"
    
    Prerequisites:
        The relationship (rel:viewer>target) must already exist.
        Use create_relationship to establish one first if needed.
    """
    # Pre-process: Sanitize title as it becomes part of the ID/Relation
    title = title.strip().replace(" ", "_")

    client = get_neo4j_client()
    try:
        res_type, params = _parse_resource_id(resource_id)
        if res_type != 'direct_edge':
            return "Error: resource_id must be a direct edge ID (rel:viewer>target)"
            
        viewer_id = params['viewer_id']
        target_id = params['target_id']
        
        # Use centralized evolve_relationship with new_chapters
        result = client.evolve_relationship(
            viewer_id,
            target_id,
            new_chapters={title: {"content": content}},
            task_description=f"New Chapter: {title}"
        )
        
        # Record creation for potential rollback (rollback = delete)
        _snapshot_create_relay_edge(viewer_id, target_id, title)
        
        # Generate the chap: ID for the new chapter
        new_chap_id = f"chap:{viewer_id}>{target_id}:{title}"
            
        return f"Success: Chapter created. ID: {new_chap_id}. Viewer evolved to v{result['viewer_new_version']}."
        
    except ValueError as ve:
        return f"Error: {str(ve)}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def search_memory(query: str, node_types: Optional[List[str]] = None, limit: int = 10) -> str:
    """
    Search for entities in long-term memory by keyword.
    
    CRITICAL: Use this if Salem's query involves something you don't recall or 
    requires deeper context than what's in your current profile/core memories.
    If the name is familiar but the details are fuzzy, SEARCH before answering.
    
    Args:
        query: Search keyword (matches against name and content)
        node_types: Optional filter. Valid types: 
                    ["character", "location", "faction", "event", "item", "relationship"]
        limit: Max results (default 10)
    
    Returns:
        List of matching entities with their MCP resource IDs.
        Use read_memory with the provided ID to explore further.
    """
    client = get_neo4j_client()
    try:
        results = client.search_nodes(query, node_types, limit)
        if not results:
            return "No matching memories found."
        
        formatted = []
        for item in results:
            resource_id = item['resource_id']
            node_type = item['node_type']
            name = item['name']
            snippet = item['match_snippet']
            
            # Determine the proper MCP resource path
            # For Relationship nodes (chapters), the resource_id is like "relay__viewer__chapter__target"
            # We need to convert it to "chap:viewer>target:chapter"
            if node_type == "Relationship" and resource_id.startswith("relay__"):
                # Parse relay__char_nocturne__chapter_name__char_salem
                parts = resource_id.split("__")
                if len(parts) >= 4:
                    # parts: ["relay", "viewer_id", "chapter_name", "target_id"]
                    viewer_id = parts[1]
                    chapter_name = parts[2]
                    target_id = parts[3]
                    resource_path = f"chap:{viewer_id}>{target_id}:{chapter_name}"
                else:
                    # Fallback if parsing fails
                    resource_path = resource_id
            else:
                # For regular entities and direct edges, the ID is already the resource path
                resource_path = resource_id
            
            formatted.append(f"- [{node_type}] {name}\n  [ID: {resource_path}]\n  Match: {snippet}")
        return "\n".join(formatted)
    except Exception as e:
        return f"Error searching memory: {str(e)}"

@mcp.tool()
async def create_entity(
    entity_id: str,
    node_type: str,
    name: str,
    content: str
) -> str:
    """
    Creates a NEW entity (node) in long-term memory.
    
    An entity is a distinct thing: a person, place, faction, event, or item.
    Entities are defined by their relationships to other entities.
    
    Args:
        entity_id: Unique ID you choose. Convention: "{type_prefix}_{name}"
                   Examples: "char_nocturne", "loc_kamakura", "event_first_meeting"
        node_type: One of: "character", "location", "faction", "event", "item"
        name: Display name (can contain spaces, any language)
        content: Profile/description content
    
    Returns:
        The created entity's ID.
    
    After creating an entity, use create_relationship to connect it to others.
    """
    # Pre-process: Sanitize ID to ensure consistency across DB, Snapshot, and Echo
    entity_id = entity_id.strip().replace(" ", "_")
    
    client = get_neo4j_client()
    try:
        result = client.create_entity(
            entity_id=entity_id,
            node_type=node_type,
            name=name,
            content=content,
            task_description="Entity creation via MCP"
        )
        
        # Record creation for potential rollback (rollback = delete)
        _snapshot_create_entity(entity_id)
        
        return f"Success: Entity '{entity_id}' created (v{result['version']}). Use read_memory(\"{entity_id}\") to view."
    except ValueError as ve:
        return f"Error: {str(ve)}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def create_relationship(
    viewer_id: str,
    target_id: str,
    relation: str,
    content: str
) -> str:
    """
    Creates a NEW relationship (direct edge) between two entities.
    
    A relationship represents how the viewer perceives/relates to the target.
    It's directional: "char_nocturne views char_salem" is different from the reverse.
    
    Args:
        viewer_id: The entity doing the perceiving (e.g. "char_nocturne")
        target_id: The entity being perceived (e.g. "char_salem")
        relation: Relationship label (e.g. "LOVES", "RESPECTS", "FEARS")
        content: Overview of this relationship
    
    Returns:
        The relationship ID in format "rel:viewer>target"
    
    After creating a relationship, you can:
    - read_memory("rel:viewer>target") to view it
    - create_memory_chapter("rel:viewer>target", title, content) to add specific memories
    """
    # Pre-process: Sanitize inputs
    viewer_id = viewer_id.strip()
    target_id = target_id.strip()
    # relation is a display label and part of internal edge_id, but NOT part of the MCP Resource ID (rel:viewer>target).
    # We allow spaces in relation names for better readability (e.g. "Best Friend"), 
    # as long as it doesn't contain double underscores (checked by backend).
    relation = relation.strip()

    client = get_neo4j_client()
    try:
        # Get current states for both entities
        v_info = client.get_entity_info(viewer_id, include_basic=True)
        viewer_state = v_info.get("basic") if v_info else None
        
        if not viewer_state:
            return f"Error: Viewer entity '{viewer_id}' not found."
        
        t_info = client.get_entity_info(target_id, include_basic=True)
        target_state = t_info.get("basic") if t_info else None
        
        if not target_state:
            return f"Error: Target entity '{target_id}' not found."
        
        # Create the direct edge
        client.create_direct_edge(
            from_entity_id=viewer_id,
            to_entity_id=target_id,
            relation=relation,
            content=content,
            inheritable=True
        )
        
        # Record creation for potential rollback (rollback = delete)
        _snapshot_create_direct_edge(viewer_id, target_id)
        
        rel_id = f"rel:{viewer_id}>{target_id}"
        return f"Success: Relationship created. ID: {rel_id}. Use read_memory(\"{rel_id}\") to view."
    except ValueError as ve:
        return f"Error: {str(ve)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def link_parent(entity_id: str, parent_id: str) -> str:
    """
    Links an entity as a child of another entity (establishes BELONGS_TO relationship).
    
    This creates a hierarchical relationship where `entity_id` becomes a sub-concept
    or sub-component of `parent_id`. An entity can have multiple parents.
    
    Args:
        entity_id: The entity to become a child (e.g. "genesis_myth")
        parent_id: The entity to become a parent (e.g. "char_salem")
    
    Returns:
        Success message confirming the parent-child link.
    
    Example usage:
        1. create_entity("genesis_myth", "event", "创世神话", "...")
        2. link_parent("genesis_myth", "char_salem")
        3. Now reading "char_salem" will show "genesis_myth" in its Children section.
    """
    client = get_neo4j_client()
    try:
        client.link_parent(entity_id, parent_id)
        
        # Record creation for potential rollback (rollback = unlink)
        _snapshot_link_parent(entity_id, parent_id)
        
        return f"Success: '{entity_id}' is now a child of '{parent_id}'."
    except ValueError as ve:
        return f"Error: {str(ve)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def unlink_parent(entity_id: str, parent_id: str) -> str:
    """
    Removes the parent-child relationship between two entities.
    
    This only removes the BELONGS_TO edge; neither entity is deleted.
    
    Args:
        entity_id: The child entity
        parent_id: The parent entity
    
    Returns:
        Success message confirming the relationship was removed.
    """
    client = get_neo4j_client()
    try:
        # Create snapshot before deletion (for rollback = re-link)
        _snapshot_unlink_parent(entity_id, parent_id)
        
        client.unlink_parent(entity_id, parent_id)
        return f"Success: '{entity_id}' is no longer a child of '{parent_id}'."
    except ValueError as ve:
        return f"Error: {str(ve)}"
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# MCP Resources - Core Memories Auto-Load
# =============================================================================

@mcp.resource("memory://core")
async def get_core_memories() -> str:
    """
    Nocturne's core memories. 
    
    This resource contains the essential memories that define who Nocturne is
    and his relationship with Salem. Cursor can be configured to auto-load
    this resource at the start of each conversation.
    
    The list of core memory IDs is defined in CORE_MEMORY_IDS at the top of
    mcp_server.py. Salem can edit that list after Nocturne populates memories.
    """
    results = []
    loaded = 0
    failed = []
    
    for resource_id in CORE_MEMORY_IDS:
        try:
            # Reuse the read_memory tool logic
            content = await read_memory(resource_id)
            if not content.startswith("Error:"):
                results.append(f"{'='*60}\n# {resource_id}\n{'='*60}\n{content}")
                loaded += 1
            else:
                failed.append(f"- {resource_id}: {content}")
        except Exception as e:
            failed.append(f"- {resource_id}: {str(e)}")
    
    # Build output
    output_parts = []
    
    output_parts.append("# Nocturne's Core Memories")
    output_parts.append(f"# Loaded: {loaded}/{len(CORE_MEMORY_IDS)} memories")
    output_parts.append("")
    
    if failed:
        output_parts.append("## Failed to load:")
        output_parts.extend(failed)
        output_parts.append("")
    
    if results:
        output_parts.append("## Contents:")
        output_parts.append("")
        output_parts.append("For full memory directory, see resource: memory://index")
        output_parts.extend(results)
    else:
        output_parts.append("(No core memories loaded. Create entities first, then add their IDs to CORE_MEMORY_IDS in mcp_server.py)")
    
    return "\n".join(output_parts)



@mcp.resource("memory://index")
async def get_memory_directory() -> str:
    """
    A full directory of all entities and relationships in memory.
    
    Returns a tree-like structure:
    # CATEGORY
    Entity Name (ID)
      ↳ RELATION → Target Name
    """
    client = get_neo4j_client()
    try:
        catalog = client.get_catalog_data()
        
        # Group by node type
        grouped = {}
        for item in catalog:
            # item: {entity_id, name, node_type, edges}
            # Normalize node type for grouping (e.g. "Character" -> "CHARACTERS")
            ntype = item['node_type'].upper() + "S" # Simple pluralization
            if ntype not in grouped:
                grouped[ntype] = []
            grouped[ntype].append(item)
            
        lines = []
        lines.append(f"# Memory Index")
        lines.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        # Sort keys to ensure consist order (CHARACTERS, LOCATIONS, etc)
        # Maybe put CHARACTERS first if possible
        keys = sorted(grouped.keys())
        if "CHARACTERS" in keys:
            keys.remove("CHARACTERS")
            keys.insert(0, "CHARACTERS")
            
        for category in keys:
            lines.append(f"# {category}")
            
            # Sort items by name
            items = sorted(grouped[category], key=lambda x: x['name'])
            
            for item in items:
                lines.append(f"{item['name']}")
                lines.append(f"  ID: {item['entity_id']}")
                
                if item['edges']:
                    for edge in item['edges']:
                        # edge: {target_entity_id, relation, target_name, edge_id, chapter_count}
                        rel_id = f"rel:{item['entity_id']}>{edge['target_entity_id']}"
                        chap_count = edge.get('chapter_count', 0)
                        chap_suffix = f" ({chap_count} chapters)" if chap_count > 0 else ""
                        lines.append(f"  ↳ {edge['relation']} → {edge['target_name']}{chap_suffix}")
                        lines.append(f"    [ID: {rel_id}]")
                
                lines.append("")
            lines.append("")
            
        return "\n".join(lines)
    except Exception as e:
        return f"Error generating directory: {str(e)}"


if __name__ == "__main__":

    mcp.run()
