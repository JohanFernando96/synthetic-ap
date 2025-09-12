"""Logging utilities for the application."""

from __future__ import annotations
import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import traceback
from typing import Dict, List, Optional

import pandas as pd

from .config.settings import settings


def logs_dir() -> Path:
    """Get the logs directory path."""
    base_dir = settings.runs_dir if settings.runs_dir else "runs"
    log_dir = Path(base_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


class LogManager:
    """Manager for application logs."""
    _instance = None
    
    @classmethod
    def get_instance(cls) -> LogManager:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = LogManager()
        return cls._instance
    
    def __init__(self):
        """Initialize loggers."""
        self.loggers = {}
        self._setup_loggers()
    
    def _setup_loggers(self):
        """Set up the different loggers."""
        log_dir = logs_dir()
        
        # Configure root logger to capture all module-level logging
        root_logger = logging.getLogger()
        if not root_logger.handlers:  # Only add handler if none exists
            root_handler = RotatingFileHandler(
                log_dir / "system.log",
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
            root_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
            root_handler.setFormatter(root_formatter)
            root_logger.addHandler(root_handler)
            root_logger.setLevel(logging.INFO)
        
        # System logger for application-specific logging
        system_logger = logging.getLogger("system")
        system_logger.propagate = False  # Don't propagate to root logger
        system_logger.setLevel(logging.INFO)
        system_handler = RotatingFileHandler(
            log_dir / "system.log", 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        system_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        system_handler.setFormatter(system_formatter)
        system_logger.addHandler(system_handler)
        self.loggers["system"] = system_logger
        
        # Xero logger
        xero_logger = logging.getLogger("xero")
        xero_logger.propagate = False  # Don't propagate to root logger
        xero_logger.setLevel(logging.INFO)
        xero_handler = RotatingFileHandler(
            log_dir / "xero.log", 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        xero_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        xero_handler.setFormatter(xero_formatter)
        xero_logger.addHandler(xero_handler)
        self.loggers["xero"] = xero_logger
        
        # Error logger
        error_logger = logging.getLogger("error")
        error_logger.propagate = False  # Don't propagate to root logger
        error_logger.setLevel(logging.ERROR)
        error_handler = RotatingFileHandler(
            log_dir / "error.log", 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        error_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s\n%(pathname)s:%(lineno)d')
        error_handler.setFormatter(error_formatter)
        error_logger.addHandler(error_handler)
        self.loggers["error"] = error_logger
    
    def log_system(self, message: str, level: str = "INFO"):
        """Log a system message."""
        if level == "INFO":
            self.loggers["system"].info(message)
        elif level == "WARNING":
            self.loggers["system"].warning(message)
        elif level == "ERROR":
            self.loggers["system"].error(message)
            # Also log to error logger
            self.loggers["error"].error(f"SYSTEM: {message}")
        elif level == "DEBUG":
            self.loggers["system"].debug(message)
    
    def log_xero(self, message: str, level: str = "INFO"):
        """Log a Xero API related message."""
        if level == "INFO":
            self.loggers["xero"].info(message)
        elif level == "WARNING":
            self.loggers["xero"].warning(message)
        elif level == "ERROR":
            self.loggers["xero"].error(message)
            # Also log to error logger
            self.loggers["error"].error(f"XERO: {message}")
        elif level == "DEBUG":
            self.loggers["xero"].debug(message)
    
    def log_error(self, message: str, exception=None):
        """Log an error with optional exception details."""
        if exception:
            tb = traceback.format_exc()
            self.loggers["error"].error(f"{message}\n{tb}")
        else:
            self.loggers["error"].error(message)
    
    def read_logs(self, log_type: str, max_lines: int = 1000, search_text: str = None, level_filter: str = None) -> List[Dict]:
        """Read logs from the specified log file with optional filtering."""
        log_dir = logs_dir()
        log_file = log_dir / f"{log_type}.log"
        
        if not log_file.exists():
            return []
        
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # Get the last N lines (most recent logs first)
            lines = lines[-max_lines:]
            
            # Process lines into structured format for display
            processed_logs = []
            for line in lines:
                try:
                    # Parse the log line 
                    # Expected format: '2025-09-10 12:34:56,789 - INFO - message'
                    # or '2025-09-10 12:34:56,789 - INFO - module_name - message' for root logger
                    parts = line.split(" - ", 3)
                    if len(parts) >= 3:
                        timestamp = parts[0]
                        level = parts[1]
                        message = parts[-1]  # Last part is always the message
                        
                        # Apply filters
                        if search_text and search_text.lower() not in line.lower():
                            continue
                            
                        if level_filter and level.strip() != level_filter:
                            continue
                            
                        processed_logs.append({
                            "timestamp": timestamp.strip(),
                            "level": level.strip(),
                            "message": message.strip()
                        })
                    else:
                        # If it's a continuation line, append to the last message
                        if processed_logs:
                            processed_logs[-1]["message"] += "\n" + line.strip()
                except Exception:
                    # If parsing fails, just add the raw line
                    processed_logs.append({
                        "timestamp": "",
                        "level": "PARSE_ERROR",
                        "message": line.strip()
                    })
            
            # Reverse to show newest at the top
            return list(reversed(processed_logs))
        except Exception as e:
            # Return an error entry if something goes wrong
            return [{
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "level": "ERROR",
                "message": f"Failed to read log file: {str(e)}"
            }]


# Initialize the log manager
_log_manager = LogManager()


def get_log_manager() -> LogManager:
    """Get the log manager instance."""
    return _log_manager


# Helper functions for easy logging
def log_system(message: str, level: str = "INFO"):
    """Log a system message."""
    get_log_manager().log_system(message, level)


def log_xero(message: str, level: str = "INFO"):
    """Log a Xero API related message."""
    get_log_manager().log_xero(message, level)


def log_error(message: str, exception=None):
    """Log an error with optional exception details."""
    get_log_manager().log_error(message, exception)


def read_logs(log_type: str, max_lines: int = 1000, search_text: str = None, level_filter: str = None) -> List[Dict]:
    """Read logs from the specified log file with optional filtering."""
    return get_log_manager().read_logs(log_type, max_lines, search_text, level_filter)