"""
Admin view for displaying user connection logs.
Provides a dedicated page for viewing logs per user with filtering and real-time updates.
"""
import datetime
from flask import request, jsonify, g, render_template, url_for
from flask_admin import expose, BaseView
from flask_babel import gettext as __, lazy_gettext as _
from markupsafe import Markup
from apiflask import abort

from hiddifypanel.models import User, UserConnectionLog, hconfig, ConfigEnum
from hiddifypanel.auth import login_required
from hiddifypanel.models.role import Role
from hiddifypanel.hutils.flask import hurl_for


class UserLogAdmin(BaseView):
    """Admin view for displaying user connection logs."""
    
    def is_accessible(self):
        if login_required(roles={Role.super_admin, Role.admin, Role.agent})(lambda: True)() != True:
            return False
        return True
    
    def _get_user(self, user_id: int) -> User:
        """Get user by ID with permission check."""
        user = User.query.get(user_id)
        if not user:
            abort(404, message="User not found")
        
        # Check if current admin has access to this user
        if user.added_by not in g.account.recursive_sub_admins_ids():
            abort(403, message="Access denied")
        
        return user
    
    @expose('/')
    def index(self):
        """Default redirect - requires user_id parameter."""
        user_id = request.args.get('user_id', type=int)
        if not user_id:
            return "User ID required", 400
        return self.view_logs()
    
    @expose('/view')
    def view_logs(self):
        """Display logs for a specific user."""
        user_id = request.args.get('user_id', type=int)
        if not user_id:
            abort(400, message="User ID required")
        
        user = self._get_user(user_id)
        
        # Get filter parameters
        log_level = request.args.get('log_level', '').upper()
        page = request.args.get('page', 1, type=int)
        per_page = 50
        
        # Build query
        query = UserConnectionLog.query.filter(UserConnectionLog.user_id == user_id)
        
        if log_level and log_level in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
            query = query.filter(UserConnectionLog.log_level == log_level)
        
        # Get total count
        total = query.count()
        
        # Get paginated results
        logs = query.order_by(UserConnectionLog.timestamp.desc()) \
                    .offset((page - 1) * per_page) \
                    .limit(per_page) \
                    .all()
        
        # Calculate pagination
        total_pages = (total + per_page - 1) // per_page
        
        return self.render(
            'admin/user_log.html',
            user=user,
            logs=logs,
            log_level=log_level,
            page=page,
            total_pages=total_pages,
            total=total,
            per_page=per_page,
            hurl_for=hurl_for,
            now=datetime.datetime.now(),
        )
    
    @expose('/api/logs')
    def api_logs(self):
        """API endpoint for fetching logs (for real-time updates)."""
        user_id = request.args.get('user_id', type=int)
        if not user_id:
            return jsonify({'error': 'User ID required'}), 400
        
        user = self._get_user(user_id)
        
        log_level = request.args.get('log_level', '').upper()
        limit = min(request.args.get('limit', 100, type=int), 500)
        since_id = request.args.get('since_id', 0, type=int)
        
        query = UserConnectionLog.query.filter(UserConnectionLog.user_id == user_id)
        
        if log_level and log_level in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
            query = query.filter(UserConnectionLog.log_level == log_level)
        
        if since_id:
            query = query.filter(UserConnectionLog.id > since_id)
        
        logs = query.order_by(UserConnectionLog.timestamp.desc()).limit(limit).all()
        
        return jsonify({
            'logs': [log.to_dict() for log in logs],
            'count': len(logs),
            'latest_id': logs[0].id if logs else since_id
        })
    
    @expose('/api/stats')
    def api_stats(self):
        """API endpoint for user log statistics."""
        user_id = request.args.get('user_id', type=int)
        if not user_id:
            return jsonify({'error': 'User ID required'}), 400
        
        user = self._get_user(user_id)
        
        # Get stats for last 24 hours
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        
        from sqlalchemy import func
        
        stats = UserConnectionLog.query.filter(
            UserConnectionLog.user_id == user_id,
            UserConnectionLog.timestamp >= cutoff
        ).with_entities(
            func.count(UserConnectionLog.id).label('total'),
            func.sum(UserConnectionLog.bytes_sent).label('bytes_sent'),
            func.sum(UserConnectionLog.bytes_received).label('bytes_received'),
        ).first()
        
        # Count by event type
        event_counts = UserConnectionLog.query.filter(
            UserConnectionLog.user_id == user_id,
            UserConnectionLog.timestamp >= cutoff
        ).with_entities(
            UserConnectionLog.event_type,
            func.count(UserConnectionLog.id)
        ).group_by(UserConnectionLog.event_type).all()
        
        return jsonify({
            'total_events': stats.total or 0,
            'bytes_sent': stats.bytes_sent or 0,
            'bytes_received': stats.bytes_received or 0,
            'event_counts': {e[0]: e[1] for e in event_counts},
            'user_name': user.name,
            'user_uuid': user.uuid,
            'is_online': user.last_online and (datetime.datetime.now() - user.last_online).total_seconds() < 120
        })


def get_log_button_html(user: User) -> str:
    """Generate HTML for the log button in user list."""
    log_url = hurl_for('admin.UserLogAdmin:view_logs', user_id=user.id)
    return f'''<a href="{log_url}" class="btn btn-xs btn-info" title="{__("View Logs")}">
        <i class="fa-solid fa-file-lines"></i> {__("Log")}
    </a>'''
