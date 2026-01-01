"""
Log Parser Service for extracting and storing user connection logs from XRay/Singbox.
Supports parsing access logs and extracting user-specific connection information.
"""
import re
import os
import datetime
from typing import Optional, Dict, List, Generator
from pathlib import Path

from celery import shared_task
from loguru import logger

# Default log paths
XRAY_LOG_PATH = "/opt/hiddify-manager/log/system/xray.access.log"
SINGBOX_LOG_PATH = "/opt/hiddify-manager/log/system/singbox.access.log"


class LogEntry:
    """Parsed log entry from XRay or Singbox."""
    
    def __init__(self):
        self.timestamp: Optional[datetime.datetime] = None
        self.user_uuid: Optional[str] = None
        self.source_ip: Optional[str] = None
        self.destination: Optional[str] = None
        self.protocol: Optional[str] = None
        self.event_type: str = "request"
        self.status: str = "unknown"
        self.bytes_sent: int = 0
        self.bytes_received: int = 0
        self.latency_ms: Optional[int] = None
        self.error_message: Optional[str] = None
        self.raw_log: str = ""
        self.log_level: str = "INFO"
        self.details: Dict = {}


class XrayLogParser:
    """Parser for XRay access logs."""
    
    # XRay access log format with logid=true:
    # 2024/01/01 12:00:00 [uuid] from 1.2.3.4:12345 accepted tcp:example.com:443 [inbound_tag >> outbound_tag]
    # or error format:
    # 2024/01/01 12:00:00 [uuid] from 1.2.3.4:12345 failed to connect: connection refused
    
    PATTERN_ACCESS = re.compile(
        r"(?P<date>\d{4}/\d{2}/\d{2})\s+"
        r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
        r"\[(?P<uuid>[a-f0-9\-]+)\]\s+"
        r"from\s+(?P<source>[^\s]+)\s+"
        r"(?P<action>accepted|rejected|failed[^:]*:?)\s*"
        r"(?P<protocol>\w+)?:?(?P<destination>[^\s\[]+)?\s*"
        r"(?:\[(?P<route>[^\]]+)\])?"
    )
    
    PATTERN_ERROR = re.compile(
        r"(?P<date>\d{4}/\d{2}/\d{2})\s+"
        r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
        r"\[(?P<uuid>[a-f0-9\-]+)\]\s+"
        r".*(?:error|failed|rejected|timeout|dropped).*",
        re.IGNORECASE
    )
    
    @classmethod
    def parse_line(cls, line: str) -> Optional[LogEntry]:
        """Parse a single log line and return a LogEntry."""
        line = line.strip()
        if not line:
            return None
        
        entry = LogEntry()
        entry.raw_log = line
        
        # Try access pattern first
        match = cls.PATTERN_ACCESS.match(line)
        if match:
            groups = match.groupdict()
            
            # Parse timestamp
            try:
                date_str = f"{groups['date']} {groups['time']}"
                entry.timestamp = datetime.datetime.strptime(date_str, "%Y/%m/%d %H:%M:%S")
            except ValueError:
                entry.timestamp = datetime.datetime.utcnow()
            
            entry.user_uuid = groups.get('uuid')
            entry.source_ip = groups.get('source', '').split(':')[0] if groups.get('source') else None
            entry.protocol = groups.get('protocol')
            entry.destination = groups.get('destination')
            
            action = groups.get('action', '').lower()
            if 'accepted' in action:
                entry.event_type = 'connect'
                entry.status = 'connected'
                entry.log_level = 'INFO'
            elif 'rejected' in action:
                entry.event_type = 'rejected'
                entry.status = 'rejected'
                entry.log_level = 'WARNING'
            elif 'failed' in action:
                entry.event_type = 'error'
                entry.status = 'failed'
                entry.log_level = 'ERROR'
                entry.error_message = action
            
            if groups.get('route'):
                entry.details['route'] = groups['route']
            
            return entry
        
        # Try error pattern
        match = cls.PATTERN_ERROR.match(line)
        if match:
            groups = match.groupdict()
            
            try:
                date_str = f"{groups['date']} {groups['time']}"
                entry.timestamp = datetime.datetime.strptime(date_str, "%Y/%m/%d %H:%M:%S")
            except ValueError:
                entry.timestamp = datetime.datetime.utcnow()
            
            entry.user_uuid = groups.get('uuid')
            entry.event_type = 'error'
            entry.status = 'error'
            entry.log_level = 'ERROR'
            entry.error_message = line
            
            return entry
        
        return None


class SingboxLogParser:
    """Parser for Singbox access logs."""
    
    # Singbox log format varies, but typically:
    # INFO [inbound/protocol] connection from 1.2.3.4:12345 to example.com:443 user: uuid
    
    PATTERN = re.compile(
        r"(?P<level>INFO|WARN|ERROR|DEBUG)\s+"
        r"\[(?P<inbound>[^\]]+)\]\s+"
        r"(?P<action>connection|accepted|rejected|closed|error)\s+"
        r"(?:from\s+)?(?P<source>[^\s]+)?\s*"
        r"(?:to\s+(?P<destination>[^\s]+))?\s*"
        r"(?:user:\s*(?P<uuid>[a-f0-9\-]+))?",
        re.IGNORECASE
    )
    
    @classmethod
    def parse_line(cls, line: str) -> Optional[LogEntry]:
        """Parse a single log line and return a LogEntry."""
        line = line.strip()
        if not line:
            return None
        
        entry = LogEntry()
        entry.raw_log = line
        
        match = cls.PATTERN.search(line)
        if match:
            groups = match.groupdict()
            
            entry.timestamp = datetime.datetime.utcnow()  # Singbox may not have timestamp
            entry.user_uuid = groups.get('uuid')
            entry.source_ip = groups.get('source', '').split(':')[0] if groups.get('source') else None
            entry.destination = groups.get('destination')
            
            level = groups.get('level', 'INFO').upper()
            entry.log_level = level
            
            action = groups.get('action', '').lower()
            if action in ('connection', 'accepted'):
                entry.event_type = 'connect'
                entry.status = 'connected'
            elif action == 'closed':
                entry.event_type = 'disconnect'
                entry.status = 'disconnected'
            elif action in ('rejected', 'error'):
                entry.event_type = 'error'
                entry.status = action
                entry.error_message = line
            
            if groups.get('inbound'):
                entry.details['inbound'] = groups['inbound']
            
            return entry
        
        return None


class LogCollector:
    """Collects and stores logs from XRay and Singbox."""
    
    def __init__(self, xray_log_path: str = XRAY_LOG_PATH, singbox_log_path: str = SINGBOX_LOG_PATH):
        self.xray_log_path = xray_log_path
        self.singbox_log_path = singbox_log_path
        self._last_positions: Dict[str, int] = {}
    
    def _read_new_lines(self, file_path: str) -> Generator[str, None, None]:
        """Read new lines from a log file since last position."""
        if not os.path.exists(file_path):
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Get or set initial position
                last_pos = self._last_positions.get(file_path, 0)
                
                # Check if file was truncated (log rotation)
                f.seek(0, 2)  # Go to end
                current_size = f.tell()
                if current_size < last_pos:
                    last_pos = 0  # File was rotated
                
                f.seek(last_pos)
                
                for line in f:
                    yield line
                
                self._last_positions[file_path] = f.tell()
        except Exception as e:
            logger.warning(f"Error reading log file {file_path}: {e}")
    
    def collect_xray_logs(self) -> List[LogEntry]:
        """Collect new logs from XRay access log."""
        entries = []
        for line in self._read_new_lines(self.xray_log_path):
            entry = XrayLogParser.parse_line(line)
            if entry and entry.user_uuid:
                entries.append(entry)
        return entries
    
    def collect_singbox_logs(self) -> List[LogEntry]:
        """Collect new logs from Singbox access log."""
        entries = []
        for line in self._read_new_lines(self.singbox_log_path):
            entry = SingboxLogParser.parse_line(line)
            if entry and entry.user_uuid:
                entries.append(entry)
        return entries
    
    def collect_all_logs(self) -> List[LogEntry]:
        """Collect logs from all sources."""
        entries = []
        entries.extend(self.collect_xray_logs())
        entries.extend(self.collect_singbox_logs())
        return entries


def get_user_id_by_uuid(uuid: str) -> Optional[int]:
    """Get user ID from UUID."""
    from hiddifypanel.models import User
    user = User.query.filter(User.uuid == uuid).first()
    return user.id if user else None


def store_log_entries(entries: List[LogEntry]) -> int:
    """Store log entries in the database. Returns count of stored logs."""
    from hiddifypanel.models import UserConnectionLog
    from hiddifypanel.database import db
    
    stored = 0
    for entry in entries:
        if not entry.user_uuid:
            continue
        
        user_id = get_user_id_by_uuid(entry.user_uuid)
        if not user_id:
            continue
        
        try:
            log = UserConnectionLog(
                user_id=user_id,
                timestamp=entry.timestamp or datetime.datetime.utcnow(),
                event_type=entry.event_type,
                log_level=entry.log_level,
                source_ip=entry.source_ip,
                destination=entry.destination,
                protocol=entry.protocol,
                bytes_sent=entry.bytes_sent,
                bytes_received=entry.bytes_received,
                latency_ms=entry.latency_ms,
                status=entry.status,
                error_message=entry.error_message,
                raw_log=entry.raw_log[:2000] if entry.raw_log else None,  # Limit size
                details=entry.details if entry.details else None
            )
            db.session.add(log)
            stored += 1
        except Exception as e:
            logger.error(f"Error storing log entry: {e}")
    
    try:
        db.session.commit()
    except Exception as e:
        logger.error(f"Error committing log entries: {e}")
        db.session.rollback()
        return 0
    
    return stored


# Global collector instance
_collector: Optional[LogCollector] = None


def get_collector() -> LogCollector:
    """Get or create the global log collector instance."""
    global _collector
    if _collector is None:
        _collector = LogCollector()
    return _collector


@shared_task
def collect_logs():
    """Celery task to collect and store logs from XRay/Singbox."""
    try:
        collector = get_collector()
        entries = collector.collect_all_logs()
        
        if entries:
            stored = store_log_entries(entries)
            logger.debug(f"Collected and stored {stored} log entries")
        
        return len(entries)
    except Exception as e:
        logger.error(f"Error in collect_logs task: {e}")
        return 0


@shared_task
def cleanup_old_logs(hours: int = 24):
    """Celery task to clean up logs older than specified hours."""
    try:
        from hiddifypanel.models import UserConnectionLog
        deleted = UserConnectionLog.cleanup_old_logs(hours=hours)
        logger.info(f"Cleaned up {deleted} old log entries")
        return deleted
    except Exception as e:
        logger.error(f"Error in cleanup_old_logs task: {e}")
        return 0
