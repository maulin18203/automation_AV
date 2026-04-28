from functools import wraps
from flask import session, redirect, url_for, flash

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('home.login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    """Requires admin or super_admin role"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session or session['user']['role'] not in ('admin', 'super_admin'):
            flash('Admin access required.', 'danger')
            return redirect(url_for('home.login'))
        return f(*args, **kwargs)
    return decorated

def super_admin_required(f):
    """Requires super_admin role only"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session or session['user']['role'] != 'super_admin':
            flash('Super Admin access required.', 'danger')
            return redirect(url_for('home.login'))
        return f(*args, **kwargs)
    return decorated
