import os
import random
import secrets
import threading
import time
from datetime import datetime, timedelta
from flask import Flask
from flask_cors import CORS
from flask_session import Session
from pymongo import MongoClient

# ================= CONFIG =================
API_ID = int(os.environ.get("API_ID", 36466824))
API_HASH = os.environ.get("API_HASH", "535ddcb85f2c3c74cc0ff532dd2c3406")
MONGO_URI = os.environ.get(
    "MONGO_URI", 
    "mongodb+srv://aafteleearn:Abdullah6790@cluster0.mxilc7i.mongodb.net/aaf_tele_earn_db?retryWrites=true&w=majority"
)
if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable not set")

# ================= DB CLIENT =================
client = MongoClient(MONGO_URI)
db_mongo = client["aaf_tele_earn_db"]

# ================= COLLECTIONS (Global) =================
users_col = db_mongo["users"]
settings_col = db_mongo["settings"]
admin_config_col = db_mongo["admin_config"]
deposits_col = db_mongo["deposits"]
withdraws_col = db_mongo["withdraws"]
trades_col = db_mongo["trades"]
task_claims_col = db_mongo["task_claims"]
task_orders_col = db_mongo["task_orders"]
milestones_col = db_mongo["milestones"]
user_milestone_claims_col = db_mongo["user_milestone_claims"]
deeplink_clicks_col = db_mongo["deeplink_clicks"]
candles_col = db_mongo['candles']
channel_status_col = db_mongo["channel_status"]
task_channel_status_col = db_mongo["task_channel_status"]
device_tasks_col = db_mongo["device_tasks"]
ip_tasks_col = db_mongo["ip_tasks"]
user_tasks_col = db_mongo["user_tasks"]
cache_col = db_mongo["stat_cache"]
rate_limits_col = db_mongo["rate_limits"]

# ================= 🆕 NEW COLLECTIONS (Adsterra + Timer + Post Views) =================
task_timers_col = db_mongo["task_timers"]
adsterra_clicks_col = db_mongo["adsterra_clicks"]
adsterra_conversions_col = db_mongo["adsterra_conversions"]
post_views_col = db_mongo["post_views"]

# ================= INDEXES =================
try:
    # পুরনো ইনডেক্স
    db_mongo['candles'].create_index("createdAt", expireAfterSeconds=5184000)
    db_mongo['candles_5m'].create_index("createdAt", expireAfterSeconds=5184000)
    db_mongo['candles_15m'].create_index("createdAt", expireAfterSeconds=5184000)
    db_mongo['candles_1h'].create_index("createdAt", expireAfterSeconds=5184000)
    db_mongo['candles_4h'].create_index("createdAt", expireAfterSeconds=5184000)
    db_mongo['candles_1d'].create_index("createdAt", expireAfterSeconds=5184000)
    db_mongo['candles'].create_index([("time", -1)])
    db_mongo['candles_5m'].create_index([("time", -1)])
    db_mongo['candles_15m'].create_index([("time", -1)])
    db_mongo['candles_1h'].create_index([("time", -1)])
    db_mongo['candles_4h'].create_index([("time", -1)])
    db_mongo['candles_1d'].create_index([("time", -1)])

    # 🆕 নতুন কালেকশনের জন্য ইনডেক্স
    db_mongo['task_timers'].create_index([("telegram_id", 1), ("task_id", 1)])
    db_mongo['task_timers'].create_index([("expires_at", 1)])
    db_mongo['adsterra_clicks'].create_index([("click_id", 1)], unique=True)
    db_mongo['adsterra_clicks'].create_index([("telegram_id", 1)])
    db_mongo['adsterra_clicks'].create_index([("created_at", -1)])
    db_mongo['post_views'].create_index([("telegram_id", 1), ("task_id", 1)])
    db_mongo['post_views'].create_index([("created_at", -1)])

    # ইউজার ও টাস্ক ইনডেক্স
    db_mongo['users'].create_index([("telegram_id", 1)], unique=True)
    db_mongo['tasks'].create_index([("task_id", 1)], unique=True)
    db_mongo['tasks'].create_index([("active", 1)])
    db_mongo['task_claims'].create_index([("telegram_id", 1), ("task_id", 1)])
    db_mongo['task_claims'].create_index([("status", 1)])
    db_mongo['task_claims'].create_index([("created_at", -1)])

    print("✅ সব ইনডেক্স সক্রিয় হয়েছে!")
except Exception as e:
    print(f"⚠️ ইনডেক্স তৈরিতে সমস্যা: {e}")

# ================= OTP STORE =================
temp_otp_data = {}
current_price = 1.0


def create_app():
    app = Flask(__name__, 
                template_folder='../templates',
                static_folder='../static')

    app.secret_key = os.environ.get("SECRET_KEY", "AAF_TELE_EARN_V18_CORE_SECRET")

    # Session Config
    app.config["SESSION_TYPE"] = "mongodb"
    app.config["SESSION_MONGODB"] = client
    app.config["SESSION_MONGODB_DB"] = "aaf_tele_earn_db"
    app.config["SESSION_MONGODB_COLLECT"] = "sessions"
    app.config["SESSION_PERMANENT"] = True
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_SAMESITE='Lax'
    )

    Session(app)
    CORS(app, supports_credentials=True)

    # ========== Register Blueprints ==========
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.tasks import tasks_bp
    from app.routes.trading import trading_bp
    from app.routes.wallet import wallet_bp
    from app.routes.account import account_bp
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp
    from app.routes.adsterra import adsterra_bp

    app.register_blueprint(auth_bp) 
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(trading_bp)
    app.register_blueprint(wallet_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(admin_bp)  # ✅ url_prefix বাদ দেওয়া হয়েছে
    app.register_blueprint(api_bp)
    app.register_blueprint(adsterra_bp, url_prefix='/adsterra')

    # ========== Start Background Threads ==========
    from app.services.price_service import start_price_thread
    start_price_thread()

    # 🆕 Auto-disable scheduler start
    start_auto_disable_scheduler()

    return app


# ================= 🆕 AUTO-DISABLE SCHEDULER =================
def start_auto_disable_scheduler():
    """
    ব্যাকগ্রাউন্ডে প্রতি ৩০ সেকেন্ড পরপর এক্সপায়ার্ড টাস্ক চেক করুন
    """
    def check_expired_tasks():
        while True:
            try:
                now = datetime.utcnow()

                # ১. timer এক্সপায়ার্ড টাস্ক ডিজেবল
                expired_timers = db_mongo["task_timers"].find({
                    "expires_at": {"$lt": now},
                    "completed": False
                })

                for timer in expired_timers:
                    db_mongo["tasks"].update_one(
                        {"task_id": timer["task_id"]},
                        {"$set": {
                            "active": False, 
                            "auto_disabled": True, 
                            "disabled_at": now,
                            "disable_reason": "timer_expired"
                        }}
                    )
                    db_mongo["task_timers"].delete_one({"_id": timer["_id"]})
                    print(f"⏰ Auto-disabled: {timer['task_id']}")

                # ২. ৫ মিনিটের বেশি পুরনো pending ক্লেইম
                old_claims = db_mongo["task_claims"].find({
                    "status": "pending",
                    "created_at": {"$lt": now - timedelta(seconds=300)}
                })

                for claim in old_claims:
                    db_mongo["tasks"].update_one(
                        {"task_id": claim["task_id"]},
                        {"$set": {"active": False, "auto_disabled": True}}
                    )
                    db_mongo["task_claims"].update_one(
                        {"_id": claim["_id"]},
                        {"$set": {"status": "expired"}}
                    )
                    print(f"⏰ Claim expired: {claim['task_id']}")

                # ৩. expiry_hours চেক (ডিফল্ট ৭ দিন)
                expired_tasks = db_mongo["tasks"].find({
                    "expiry_hours": {"$ne": 0},
                    "created_at": {"$lt": now - timedelta(hours=168)},
                    "active": True
                })

                for task in expired_tasks:
                    db_mongo["tasks"].update_one(
                        {"_id": task["_id"]},
                        {"$set": {"active": False, "expired": True}}
                    )
                    print(f"⏰ Task expired: {task['task_id']}")

            except Exception as e:
                print(f"⚠️ Scheduler error: {e}")

            # প্রতি ৩০ সেকেন্ড পর পর চেক করুন
            time.sleep(30)

    # ব্যাকগ্রাউন্ড থ্রেড শুরু করুন
    thread = threading.Thread(target=check_expired_tasks, daemon=True)
    thread.start()
    print("🚀 Auto-disable scheduler started")