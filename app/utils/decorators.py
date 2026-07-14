from functools import wraps
from flask import session, redirect, url_for
from bson import ObjectId
from app import users_col

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        uid = session.get("uid")
        if not uid:
            return redirect(url_for("auth.login"))
        user = users_col.find_one({"_id": ObjectId(uid)})
        if not user:
            session.clear()
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("auth.admin_login_page"))
        return f(*args, **kwargs)
    return decorated_function
