"""
BrightHaven — Cloud IoT Smart Home Platform
"""
import os
from flask import Flask
from dotenv import load_dotenv
from flask_compress import Compress

load_dotenv('../.env')

compress = Compress()

def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv('FLASK_SECRET_KEY', 'brighthaven_2026_mk_secure_key')
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = False # Set to True in production with HTTPS
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_REFRESH_EACH_REQUEST'] = False # Only update session if modified
    
    # Ultimate Performance Optimizations
    # 1. Enable gzip compression for all responses
    app.config['COMPRESS_MIMETYPES'] = ['text/html', 'text/css', 'application/json', 'application/javascript']
    app.config['COMPRESS_LEVEL'] = 6
    app.config['COMPRESS_MIN_SIZE'] = 500
    compress.init_app(app)

    # 2. Aggressive static file caching (1 year)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000

    # Core dependencies
    from app.core.firebase import db
    from app.core.mqtt import mqtt_bridge
    from app.core.hardware import cache, gpio_ctrl
    from app.core.timer_engine import timer_engine
    from app.core.dynamic_data import load_dynamic_data

    # Blueprints
    from app.routes.public import home_bp
    from app.routes.user import user_bp
    from app.routes.admin import admin_bp
    from app.routes.super_admin import super_bp
    from app.routes.api import api_bp

    # Load initial data
    print("[System] Initializing database...")
    load_dynamic_data()
    
    # Initialize hardware
    gpio_ctrl.init_pins()
    
    # Start background threads
    print("[MQTT] Connecting to broker... (started by import)")
    
    print("[Blynk] Fetching initial device states...")
    cache.start_background_refresh()
    
    timer_engine.start()

    # Register Blueprints
    app.register_blueprint(home_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(super_bp)
    app.register_blueprint(api_bp)

    from flask import g, session, request, abort

    @app.before_request
    def enforce_tenant_isolation():
        # Exclude static routes or public routes if necessary, but basically 
        # ensure g.tenant_id is available for any logged-in user.
        if 'user' in session:
            g.tenant_id = session['user'].get('tenant_id', 'tenant_default_001')
            g.user_id = session['user'].get('id')
            g.role = session['user'].get('role')
        else:
            g.tenant_id = None

    from flask import render_template
    
    @app.errorhandler(400)
    def bad_request(e):
        return render_template('error.html', code=400, title="Bad Request", msg="The server could not understand your request."), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return render_template('error.html', code=401, title="Unauthorized", msg="You must be logged in to view this page."), 401

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('error.html', code=403, title="Forbidden", msg="You don't have permission to access this resource."), 403

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('error.html', code=404, title="Not Found", msg="The requested URL was not found on our server."), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_template('error.html', code=405, title="Method Not Allowed", msg="The method is not allowed for the requested URL."), 405

    @app.errorhandler(500)
    def internal_error(e):
        return render_template('error.html', code=500, title="Server Error", msg="Something went wrong on our end. Please try again later."), 500

    print("[Server] BrightHaven Cloud IoT Platform Ready ✅\n")
    return app
