"""
UserConnectionLog model for storing per-user connection logs.
Logs are automatically cleaned up after 24 hours.
"""
import datetime
from enum import auto
from strenum import StrEnum

from hiddifypanel.database import db


class ConnectionEventType(StrEnum):
    """Types of connection events that can be logged."""
    connect = auto()
    disconnect = auto()
    request = auto()
    response = auto()
    error = auto()
    timeout = auto()
    rejected = auto()


class UserConnectionLog(db.Model):
    """
    Model for storing user connection logs.
    Each log entry represents a connection event for a specific user.
    Logs older than 24 hours are automatically cleaned up by a Celery task.
    """
    __tablename__ = 'user_connection_log'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
    
    # Event details
    event_type = db.Column(db.String(32), default=ConnectionEventType.connect, nullable=False)
    log_level = db.Column(db.String(16), default='INFO', nullable=False, index=True)
    
    # Connection info
    source_ip = db.Column(db.String(64), nullable=True)
    destination = db.Column(db.String(256), nullable=True)
    protocol = db.Column(db.String(32), nullable=True)
    
    # Traffic metrics
    bytes_sent = db.Column(db.BigInteger, default=0)
    bytes_received = db.Column(db.BigInteger, default=0)
    
    # Performance metrics
    latency_ms = db.Column(db.Integer, nullable=True)  # Ping in milliseconds
    connection_speed = db.Column(db.BigInteger, nullable=True)  # Bytes per second
    
    # Status and details
    status = db.Column(db.String(32), nullable=True)  # connected, dropped, rejected, etc.
    error_message = db.Column(db.String(512), nullable=True)
    raw_log = db.Column(db.Text, nullable=True)  # Original log line
    details = db.Column(db.JSON, nullable=True)  # Additional JSON details
    
    # Relationships
    user = db.relationship('User', backref=db.backref('connection_logs', lazy='dynamic', cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<UserConnectionLog {self.id} user={self.user_id} type={self.event_type}>'
    
    def to_dict(self):
        """Convert log entry to dictionary for API responses."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'event_type': self.event_type,
            'log_level': self.log_level,
            'source_ip': self.source_ip,
            'destination': self.destination,
            'protocol': self.protocol,
            'bytes_sent': self.bytes_sent,
            'bytes_received': self.bytes_received,
            'latency_ms': self.latency_ms,
            'connection_speed': self.connection_speed,
            'status': self.status,
            'error_message': self.error_message,
            'details': self.details,
        }
    
    @classmethod
    def get_user_logs(cls, user_id: int, log_level: str = None, limit: int = 100, offset: int = 0):
        """Get logs for a specific user with optional filtering."""
        query = cls.query.filter(cls.user_id == user_id)
        
        if log_level:
            query = query.filter(cls.log_level == log_level.upper())
        
        return query.order_by(cls.timestamp.desc()).offset(offset).limit(limit).all()
    
    @classmethod
    def cleanup_old_logs(cls, hours: int = 24):
        """Delete logs older than specified hours. Returns count of deleted logs."""
        cutoff_time = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        deleted = cls.query.filter(cls.timestamp < cutoff_time).delete()
        db.session.commit()
        return deleted
    
    @classmethod
    def add_log(cls, user_id: int, event_type: str, **kwargs):
        """Add a new log entry for a user."""
        log = cls(
            user_id=user_id,
            event_type=event_type,
            **kwargs
        )
        db.session.add(log)
        db.session.commit()
        return log
