from functools import wraps

from flask import g, jsonify


def login_required(f):
    @wraps(f)
    def decorated_func(*args, **kwargs):
        if g.current_user is None:
            return jsonify({
                "error": "UNAUTHORIZED",
                "message": "Authentication required"
            }), 401
        
        return f(*args, **kwargs)
    return decorated_func