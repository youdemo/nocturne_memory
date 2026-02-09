#!/usr/bin/env python3
"""
Migration Script: Neo4j -> SQLite

This script migrates memory data from Neo4j to SQLite.

Mapping:
- Entity `nocturne` -> path `nocturne`
- Relationship `rel:A>B` -> path `A/B`
- Chapter `chap:A>B:name` -> path `A/B/name`

Usage:
    python -m scripts.migrate_neo4j_to_sqlite
    
    Or from backend directory:
    python scripts/migrate_neo4j_to_sqlite.py
"""

import os
import sys
import asyncio
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv, find_dotenv

# Load environment variables
_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path:
    load_dotenv(_dotenv_path)

from db.neo4j_client import get_neo4j_client
from db.sqlite_client import get_sqlite_client, SQLiteClient


class MigrationLogger:
    """Logs migration progress and results."""
    
    def __init__(self, log_file: str = "migration_log.json"):
        self.log_file = log_file
        self.entries = []
        self.errors = []
        self.stats = {
            "entities": 0,
            "relationships": 0,
            "chapters": 0,
            "total_memories": 0,
            "total_paths": 0
        }
    
    def log(self, entry_type: str, source_id: str, target_path: str, memory_id: int):
        """Log a successful migration."""
        self.entries.append({
            "type": entry_type,
            "source": source_id,
            "target_path": target_path,
            "memory_id": memory_id,
            "timestamp": datetime.now().isoformat()
        })
        self.stats[f"{entry_type}s" if entry_type != "entity" else "entities"] += 1
        self.stats["total_memories"] += 1
        self.stats["total_paths"] += 1
    
    def error(self, entry_type: str, source_id: str, error: str):
        """Log an error."""
        self.errors.append({
            "type": entry_type,
            "source": source_id,
            "error": error,
            "timestamp": datetime.now().isoformat()
        })
    
    def save(self):
        """Save log to file."""
        data = {
            "stats": self.stats,
            "entries": self.entries,
            "errors": self.errors,
            "completed_at": datetime.now().isoformat()
        }
        with open(self.log_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\nMigration log saved to: {self.log_file}")
    
    def print_summary(self):
        """Print migration summary."""
        print("\n" + "="*60)
        print("MIGRATION SUMMARY")
        print("="*60)
        print(f"Entities migrated:     {self.stats['entities']}")
        print(f"Relationships migrated: {self.stats['relationships']}")
        print(f"Chapters migrated:     {self.stats['chapters']}")
        print(f"Total memories created: {self.stats['total_memories']}")
        print(f"Total paths created:    {self.stats['total_paths']}")
        print(f"Errors:                {len(self.errors)}")
        if self.errors:
            print("\nErrors:")
            for err in self.errors[:10]:  # Show first 10 errors
                print(f"  - [{err['type']}] {err['source']}: {err['error']}")
            if len(self.errors) > 10:
                print(f"  ... and {len(self.errors) - 10} more errors")
        print("="*60)


async def migrate_entity(
    neo4j_client,
    sqlite_client: SQLiteClient,
    entity_id: str,
    logger: MigrationLogger
) -> Optional[int]:
    """
    Migrate a single entity.
    
    Returns:
        memory_id if successful, None if failed
    """
    try:
        # Get entity info from Neo4j
        info = neo4j_client.get_entity_info(
            entity_id,
            include_basic=True,
            include_edges=False,
            include_children=False
        )
        
        if not info or not info.get("basic"):
            logger.error("entity", entity_id, "Entity not found or has no basic info")
            return None
        
        basic = info["basic"]
        content = basic.get("content", "")
        name = basic.get("name", entity_id)
        
        # Create in SQLite
        # Path = entity_id (flat structure)
        result = await sqlite_client.create_memory(
            parent_path="",  # Root level
            content=content,
            title=entity_id,  # Use entity_id as title
            importance=0,
            disclosure=None
        )
        
        logger.log("entity", entity_id, result["path"], result["id"])
        print(f"  [OK] Entity: {entity_id} -> {result['path']}")
        return result["id"]
        
    except Exception as e:
        logger.error("entity", entity_id, str(e))
        print(f"  [ERR] Entity: {entity_id} - {e}")
        return None


async def migrate_relationship(
    neo4j_client,
    sqlite_client: SQLiteClient,
    viewer_id: str,
    target_id: str,
    logger: MigrationLogger
) -> Optional[int]:
    """
    Migrate a relationship (direct edge).
    
    Returns:
        memory_id if successful, None if failed
    """
    try:
        # Get relationship structure from Neo4j
        data = neo4j_client.get_relationship_structure(viewer_id, target_id)
        
        if not data.get("direct"):
            logger.error("relationship", f"rel:{viewer_id}>{target_id}", "Relationship not found")
            return None
        
        direct = data["direct"]
        content = direct.get("content", "")
        relation = direct.get("relation", "RELATIONSHIP")
        
        # Build content with relation metadata
        full_content = f"@relation: {relation}\n\n{content}"
        
        # Path = viewer_id/target_id
        target_path = f"{viewer_id}/{target_id}"
        
        result = await sqlite_client.create_memory(
            parent_path=viewer_id,
            content=full_content,
            title=target_id,
            importance=0,
            disclosure=None
        )
        
        logger.log("relationship", f"rel:{viewer_id}>{target_id}", result["path"], result["id"])
        print(f"  [OK] Relationship: rel:{viewer_id}>{target_id} -> {result['path']}")
        return result["id"]
        
    except Exception as e:
        logger.error("relationship", f"rel:{viewer_id}>{target_id}", str(e))
        print(f"  [ERR] Relationship: rel:{viewer_id}>{target_id} - {e}")
        return None


async def migrate_chapter(
    neo4j_client,
    sqlite_client: SQLiteClient,
    viewer_id: str,
    target_id: str,
    chapter_name: str,
    logger: MigrationLogger
) -> Optional[int]:
    """
    Migrate a chapter (relay edge).
    
    Returns:
        memory_id if successful, None if failed
    """
    try:
        # Get chapter content from Neo4j
        relay_entity_id = neo4j_client.generate_relay_entity_id(viewer_id, chapter_name, target_id)
        info = neo4j_client.get_entity_info(relay_entity_id, include_basic=True)
        
        if not info or not info.get("basic"):
            logger.error("chapter", f"chap:{viewer_id}>{target_id}:{chapter_name}", "Chapter not found")
            return None
        
        basic = info["basic"]
        content = basic.get("content", "")
        
        # Path = viewer_id/target_id/chapter_name
        parent_path = f"{viewer_id}/{target_id}"
        
        result = await sqlite_client.create_memory(
            parent_path=parent_path,
            content=content,
            title=chapter_name,
            importance=0,
            disclosure=None
        )
        
        logger.log("chapter", f"chap:{viewer_id}>{target_id}:{chapter_name}", result["path"], result["id"])
        print(f"  [OK] Chapter: chap:{viewer_id}>{target_id}:{chapter_name} -> {result['path']}")
        return result["id"]
        
    except Exception as e:
        logger.error("chapter", f"chap:{viewer_id}>{target_id}:{chapter_name}", str(e))
        print(f"  [ERR] Chapter: chap:{viewer_id}>{target_id}:{chapter_name} - {e}")
        return None


async def run_migration():
    """Main migration function."""
    print("="*60)
    print("NEO4J -> SQLITE MIGRATION")
    print("="*60)
    
    # Initialize clients
    print("\n[1/5] Initializing clients...")
    neo4j_client = get_neo4j_client()
    sqlite_client = get_sqlite_client()
    
    # Initialize SQLite tables
    print("[2/5] Creating SQLite tables...")
    await sqlite_client.init_db()
    
    logger = MigrationLogger()
    
    # Get catalog from Neo4j
    print("[3/5] Reading Neo4j catalog...")
    catalog = neo4j_client.get_catalog_data()
    print(f"  Found {len(catalog)} entities in catalog")
    
    # Phase 1: Migrate all entities first (to ensure parent paths exist)
    print("\n[4/5] Migrating entities...")
    entity_ids = set()
    for item in catalog:
        entity_id = item["entity_id"]
        entity_ids.add(entity_id)
        await migrate_entity(neo4j_client, sqlite_client, entity_id, logger)
    
    # Phase 2: Migrate relationships and chapters
    print("\n[5/5] Migrating relationships and chapters...")
    for item in catalog:
        entity_id = item["entity_id"]
        edges = item.get("edges", [])
        
        for edge in edges:
            target_id = edge["target_entity_id"]
            
            # Migrate the relationship
            await migrate_relationship(neo4j_client, sqlite_client, entity_id, target_id, logger)
            
            # Get and migrate chapters
            rel_data = neo4j_client.get_relationship_structure(entity_id, target_id)
            relays = rel_data.get("relays", [])
            
            for relay in relays:
                if relay is None:
                    continue
                state = relay.get("state", {})
                chapter_name = state.get("name", "")
                if chapter_name:
                    await migrate_chapter(
                        neo4j_client, sqlite_client,
                        entity_id, target_id, chapter_name,
                        logger
                    )
    
    # Print summary and save log
    logger.print_summary()
    logger.save()
    
    # Cleanup
    await sqlite_client.close()
    neo4j_client.close()
    
    print("\nMigration complete!")


if __name__ == "__main__":
    asyncio.run(run_migration())
