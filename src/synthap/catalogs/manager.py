# src/synthap/catalogs/manager.py
from __future__ import annotations
import os
import shutil
import time
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
import uuid
import hashlib
from datetime import datetime

from ..config.settings import settings


def create_backup_dir(base_dir: str = None) -> Path:
    """Create a backup directory for catalogs."""
    base_dir = base_dir or settings.data_dir
    backup_dir = Path(base_dir) / "catalogs_backup"
    backup_dir.mkdir(exist_ok=True)
    return backup_dir


def backup_catalogs(base_dir: str = None, reason: str = None) -> str:
    """
    Backup catalog files with a descriptive naming scheme.
    
    Format: backup_YYYYMMDD_HHMMSS_[reason]_[hash]
    - YYYYMMDD_HHMMSS: Timestamp for chronological sorting
    - reason: Optional descriptor (e.g., 'before_mining_data', 'manual', 'auto')
    - hash: Content hash (first 8 chars) to ensure uniqueness
    
    Returns the path to the created backup directory.
    """
    base_dir = base_dir or settings.data_dir
    catalogs_dir = Path(base_dir) / "catalogs"
    backup_dir = create_backup_dir(base_dir)
    
    # Generate timestamp component
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Clean up reason text for filename use
    clean_reason = ""
    if reason:
        # Replace spaces and special chars with underscores, limit length
        clean_reason = "".join(c if c.isalnum() else "_" for c in reason.lower())
        clean_reason = clean_reason[:30]  # Limit length
        clean_reason = f"_{clean_reason}"
    
    # Generate content hash for uniqueness
    content_hash = ""
    hash_obj = hashlib.md5()
    for yaml_file in sorted(catalogs_dir.glob("*.yaml")):
        if yaml_file.exists():
            hash_obj.update(yaml_file.read_bytes())
    content_hash = hash_obj.hexdigest()[:8]  # First 8 chars of hash
    
    # Create backup folder name
    backup_name = f"backup_{timestamp}{clean_reason}_{content_hash}"
    backup_path = backup_dir / backup_name
    backup_path.mkdir(exist_ok=True)
    
    # Copy all YAML files
    for yaml_file in catalogs_dir.glob("*.yaml"):
        shutil.copy2(yaml_file, backup_path / yaml_file.name)
    
    return str(backup_path)


def restore_catalogs(backup_path: str, base_dir: str = None) -> bool:
    """Restore catalog files from a backup directory."""
    base_dir = base_dir or settings.data_dir
    catalogs_dir = Path(base_dir) / "catalogs"
    source_path = Path(backup_path)
    
    if not source_path.exists() or not source_path.is_dir():
        return False
    
    # Copy all YAML files from backup to catalogs directory
    for yaml_file in source_path.glob("*.yaml"):
        shutil.copy2(yaml_file, catalogs_dir / yaml_file.name)
    
    return True


def list_backups(base_dir: str = None) -> list[dict]:
    """List all available catalog backups with readable information."""
    base_dir = base_dir or settings.data_dir
    backup_dir = create_backup_dir(base_dir)
    
    backups = []
    for backup_path in sorted(backup_dir.iterdir(), reverse=True):
        if backup_path.is_dir():
            try:
                name = backup_path.name
                
                # Skip default backup - handle it separately
                if name == "default":
                    continue
                
                # Parse the backup name components
                display_name = name
                human_date = ""
                reason = "Manual backup"
                
                # Extract parts from backup_YYYYMMDD_HHMMSS_[reason]_[hash]
                if name.startswith("backup_"):
                    parts = name.split("_")
                    if len(parts) >= 3:
                        # Extract date and time
                        try:
                            date_str = parts[1]
                            time_str = parts[2]
                            dt = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                            human_date = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            human_date = "Unknown date"
                        
                        # Extract reason if present
                        if len(parts) > 4:
                            reason_parts = parts[3:-1]  # All parts between time and hash
                            reason = " ".join(reason_parts).replace("_", " ").title()
                        
                        display_name = f"{human_date} - {reason}"
                
                backups.append({
                    "name": name,
                    "path": str(backup_path),
                    "display_name": display_name,
                    "date": human_date,
                    "reason": reason
                })
            except Exception:
                # If parsing fails, use the raw directory name
                backups.append({
                    "name": backup_path.name,
                    "path": str(backup_path),
                    "display_name": backup_path.name
                })
    
    # Add default backup at the top if it exists
    default_path = backup_dir / "default"
    if default_path.exists() and default_path.is_dir():
        backups.insert(0, {
            "name": "default",
            "path": str(default_path),
            "display_name": "Default Catalogs (Factory Settings)",
            "date": "",
            "reason": "Default"
        })
    
    return backups

def create_default_backup(base_dir: str = None) -> str:
    """Create a 'default' backup of current catalogs if it doesn't exist."""
    base_dir = base_dir or settings.data_dir
    backup_dir = create_backup_dir(base_dir)
    default_path = backup_dir / "default"
    
    # Only create default backup if it doesn't exist
    if not default_path.exists():
        default_path.mkdir(exist_ok=True)
        catalogs_dir = Path(base_dir) / "catalogs"
        
        for yaml_file in catalogs_dir.glob("*.yaml"):
            shutil.copy2(yaml_file, default_path / yaml_file.name)
    
    return str(default_path)


def restore_default_catalogs(base_dir: str = None) -> bool:
    """Restore catalogs from the default backup."""
    base_dir = base_dir or settings.data_dir
    backup_dir = create_backup_dir(base_dir)
    default_path = backup_dir / "default"
    
    if not default_path.exists():
        # Create default backup first if it doesn't exist
        create_default_backup(base_dir)
    
    return restore_catalogs(str(default_path), base_dir)

def fix_items_yaml(base_dir: str = None) -> bool:
    """
    Fix the items.yaml file by ensuring all account_code values are strings.
    Returns True if any changes were made, False otherwise.
    """
    base_dir = base_dir or settings.data_dir
    items_path = Path(base_dir) / "catalogs" / "items.yaml"
    
    if not items_path.exists():
        return False
    
    # Load the YAML file
    with open(items_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    if not data or "items" not in data:
        return False
    
    # Track if any changes were made
    changes_made = False
    
    # Ensure all account_code values are strings
    for item in data["items"]:
        if "account_code" in item and not isinstance(item["account_code"], str):
            item["account_code"] = str(item["account_code"])
            changes_made = True
    
    # If changes were made, save the file
    if changes_made:
        with open(items_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
    
    return changes_made