# app/routes/tasks.py

from flask import Blueprint, render_template, request, jsonify, session
from datetime import datetime, timedelta
from bson import ObjectId
import hashlib

from app import users_col, db_mongo, task_claims_col, task_orders_col, admin_config_col, task_channel_status_col, device_tasks_col, ip_tasks_col, user_tasks_col, cache_col, rate_limits_col
from app.utils.decorators import login_required
from app.utils.helpers import get_admin_config, generate_task_serial, run_async
from app.services.telegram_service import verify_user_task_smart
from app.utils.adsterra_utils import verify_adsterra_click, send_conversion_to_adsterra

tasks_bp = Blueprint('tasks', __name__, url_prefix='/tasks')


@tasks_bp.route('/')
@login_required
def task():
    return render_template("tasks.html")


@tasks_bp.route('/order')
@login_required
def task_order():
    return render_template("task_order.html")


@tasks_bp.route('/api/tasks')
def get_tasks():
    auto_disable_expired_tasks()
    
    tasks = list(db_mongo["tasks"].find({
        "active": True,
        "type": {"$in": ["telegram_channel", "post_view", "smart_click"]}
    }))
    task_list = []
    for t in tasks:
        t["id"] = t.get("task_id", str(t["_id"]))
        t["_id"] = str(t["_id"])
        task_list.append(t)
    return jsonify({"tasks": task_list})


def auto_disable_expired_tasks():
    """যেসব টাস্কের সময় শেষ হয়েছে সেগুলো অটো ডিজেবল করুন"""
    now = datetime.utcnow()
    
    expired_timers = db_mongo["task_timers"].find({
        "expires_at": {"$lt": now},
        "completed": False
    })
    
    for timer in expired_timers:
        db_mongo["tasks"].update_one(
            {"task_id": timer["task_id"]},
            {"$set": {"active": False, "auto_disabled": True, "disabled_at": now}}
        )
        db_mongo["task_timers"].delete_one({"_id": timer["_id"]})


# ================= USER ME API (Tasks) =================
@tasks_bp.route('/api/user/me')
def tasks_user_me():
    uid = session.get("uid")
    if not uid:
        return jsonify({"status": "error", "message": "session_expired"})
    
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        session.clear()
        return jsonify({"status": "error", "message": "user_not_found"})
    
    admin = get_admin_config()
    
    safe_user = {
        "_id": str(user["_id"]),
        "telegram_id": user.get("telegram_id"),
        "username": user.get("username"),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "cash": float(user.get("cash", 0)),
        "aaf": float(user.get("aaf", 0)),
        "refer_count": user.get("refer_count", 0),
        "tasks_done": user.get("tasks_done", 0),
        "is_joined": user.get("is_joined", False),
        "phone": user.get("phone", "")
    }
    
    safe_admin = {
        "live_price": admin.get("live_price", 1.0),
        "trading_fee": admin.get("trading_fee", 0.5),
        "banner_ad_code": admin.get("banner_ad_code", ""),
        "trading_ad_text": admin.get("trading_ad_text", ""),
        "referral_bonus": admin.get("referral_bonus", 0),
        "wallet": admin.get("wallet", {"nagad": "", "bkash": ""})
    }
    
    return jsonify({"status": "success", "user": safe_user, "admin": safe_admin})


@tasks_bp.route('/api/user/claimed_tasks')
@login_required
def get_claimed_tasks():
    uid = session.get("uid")
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"claimed_ids": []})
    
    claims = task_claims_col.find({
        "telegram_id": user["telegram_id"], 
        "status": "approved"
    })
    claimed_ids = [claim["task_id"] for claim in claims]
    return jsonify({"claimed_ids": claimed_ids})


@tasks_bp.route('/api/user/due_status')
@login_required
def get_due_status():
    uid = session.get("uid")
    if not uid:
        return jsonify({"due": 0, "is_member": True, "details": []})
    
    task_statuses = list(task_channel_status_col.find(
        {"user_id": uid, "is_member": False, "due_cleared": {"$ne": True}}
    ))
    
    details = []
    for status in task_statuses:
        task_id = status.get("task_id")
        task_title = "অজানা টাস্ক"
        if task_id:
            task_data = db_mongo["tasks"].find_one({"task_id": task_id})
            if task_data:
                task_title = task_data.get("title", "অজানা টাস্ক")
        details.append({
            "task_id": task_id,
            "task_title": task_title,
            "due_amount": 1,
            "last_joined": status.get("last_joined").isoformat() if status.get("last_joined") else None
        })
    
    total_due = len(task_statuses)
    if total_due == 0:
        message = "কোনো ডিউ নেই। সব টাস্কের চ্যানেল জয়েন করে রাখুন।"
    else:
        message = f"⚠️ আপনার {total_due}টি টাস্কের চ্যানেলে ডিউ আছে।"
    
    return jsonify({
        "success": True,
        "due": total_due,
        "is_member": total_due == 0,
        "message": message,
        "details": details
    })


# ================= TASK START TIMER =================
@tasks_bp.route('/api/user/tasks/start', methods=["POST"])
@login_required
def start_task_timer():
    uid = session.get("uid")
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"success": False, "message": "User not found"})

    data = request.json
    task_id = data.get("task_id")
    
    task = db_mongo["tasks"].find_one({"task_id": task_id})
    if not task:
        return jsonify({"success": False, "message": "Task not found"})
    
    if task.get("type") == "telegram_channel":
        duration = task.get("timer", 30)
    elif task.get("type") == "post_view":
        duration = task.get("view_duration", 30)
    elif task.get("type") == "smart_click":
        duration = task.get("click_verify_time", 5)
    else:
        duration = 30
    
    expires_at = datetime.utcnow() + timedelta(seconds=duration)
    
    db_mongo["task_timers"].update_one(
        {"telegram_id": user["telegram_id"], "task_id": task_id},
        {"$set": {
            "duration": duration,
            "started_at": datetime.utcnow(),
            "expires_at": expires_at,
            "completed": False
        }},
        upsert=True
    )
    
    return jsonify({
        "success": True,
        "message": f"টাইমার শুরু! {duration} সেকেন্ড সময় আছে।",
        "expires_at": expires_at.isoformat()
    })


# ================= CHANNEL TASK =================
@tasks_bp.route('/api/user/tasks/verify_channel', methods=["POST"])
@login_required
def verify_channel_task():
    uid = session.get("uid")
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"success": False, "message": "User not found"})

    data = request.json
    task_id = data.get("task_id")
    device_id = data.get("device_id")
    user_ip = request.remote_addr

    task = db_mongo["tasks"].find_one({"task_id": task_id})
    if not task:
        return jsonify({"success": False, "message": "Task not found"})

    # টাইমার চেক
    timer = db_mongo["task_timers"].find_one({
        "telegram_id": user["telegram_id"],
        "task_id": task_id,
        "completed": False
    })
    
    if not timer:
        return jsonify({"success": False, "message": "⚠️ আপনি টাস্ক শুরু করেননি বা টাইমার শেষ!"})
    
    if datetime.utcnow() > timer["expires_at"]:
        db_mongo["tasks"].update_one(
            {"task_id": task_id},
            {"$set": {"active": False, "auto_disabled": True}}
        )
        return jsonify({"success": False, "message": "⏰ সময় শেষ! টাস্কটি বন্ধ করা হয়েছে。"})

    if task.get("max_users", 0) > 0:
        current = task.get("current_users", 0)
        if current >= task["max_users"]:
            return jsonify({"success": False, "message": f"⚠️ এই টাস্কে আর জায়গা নেই!"})

    admin = get_admin_config()
    global_rules = admin.get("task_rules", {})

    device_check = task.get("device_check", global_rules.get("device_check", True))
    if device_check and device_id:
        if db_mongo["device_tasks"].find_one({"task_id": task_id, "device_id": device_id}):
            return jsonify({"success": False, "message": "এই ডিভাইস ইতিমধ্যে টাস্ক ক্লেইম করেছে。"})

    ip_check = task.get("ip_check", global_rules.get("ip_check", False))
    ip_limit = admin.get("ip_limit_per_hour", 5)
    if ip_check and user_ip:
        now_ts = datetime.utcnow().timestamp()
        ip_record = db_mongo["ip_tasks"].find_one({"task_id": task_id, "ip": user_ip})
        if ip_record and ip_record.get("timestamp", 0) > now_ts - 3600:
            if ip_record.get("count", 0) >= ip_limit:
                return jsonify({"success": False, "message": f"আইপি থেকে প্রতি ঘন্টায় সর্বোচ্চ {ip_limit} বার ক্লেইম করা যাবে。"})

    account_check = task.get("account_check", global_rules.get("account_check", True))
    if account_check:
        if db_mongo["user_tasks"].find_one({"telegram_id": user["telegram_id"], "task_id": task_id}):
            return jsonify({"success": False, "message": "আপনি ইতিমধ্যে এই টাস্ক ক্লেইম করেছেন。"})

    if task_claims_col.find_one({"telegram_id": user["telegram_id"], "task_id": task_id}):
        return jsonify({"success": False, "message": "আপনি ইতিমধ্যে এই টাস্ক সম্পন্ন করেছেন。"})

    # চ্যানেল ভেরিফিকেশন
    channel = task.get("link", "").strip()
    if "t.me/" in channel:
        channel = channel.split("t.me/")[-1].split("/")[0]
        if channel.startswith("@"):
            channel = channel[1:]
    if not channel.startswith("@"):
        channel = "@" + channel

    is_member = verify_user_task_smart(user["telegram_id"], channel)
    if not is_member:
        return jsonify({"success": False, "message": "আপনি এখনো চ্যানেলে জয়েন করেননি。"})

    # টাকা দিন
    if device_check and device_id:
        db_mongo["device_tasks"].insert_one({"task_id": task_id, "device_id": device_id, "created_at": datetime.utcnow()})

    if ip_check and user_ip:
        now_ts = datetime.utcnow().timestamp()
        db_mongo["ip_tasks"].update_one(
            {"task_id": task_id, "ip": user_ip},
            {"$set": {"timestamp": now_ts}, "$inc": {"count": 1}},
            upsert=True
        )

    if account_check:
        db_mongo["user_tasks"].insert_one({"telegram_id": user["telegram_id"], "task_id": task_id, "created_at": datetime.utcnow()})

    task_channel_status_col.update_one(
        {"user_id": str(user["_id"]), "task_id": task_id},
        {"$set": {"is_member": True, "last_joined": datetime.utcnow()}},
        upsert=True
    )

    reward = task.get("reward", 0)
    currency = task.get("currency", "cash")
    
    if currency == "aaf":
        users_col.update_one({"_id": user["_id"]}, {"$inc": {"aaf": reward}})
    else:
        users_col.update_one({"_id": user["_id"]}, {"$inc": {"cash": reward}})

    users_col.update_one({"_id": user["_id"]}, {"$inc": {"tasks_done": 1}})
    db_mongo["tasks"].update_one({"task_id": task_id}, {"$inc": {"current_users": 1}})

    db_mongo["task_timers"].update_one(
        {"_id": timer["_id"]},
        {"$set": {"completed": True, "completed_at": datetime.utcnow()}}
    )

    serial_number = generate_task_serial()
    task_claims_col.insert_one({
        "telegram_id": user["telegram_id"],
        "task_id": task_id,
        "device_id": device_id,
        "ip": user_ip,
        "reward": reward,
        "currency": currency,
        "status": "approved",
        "serial_number": serial_number,
        "created_at": datetime.utcnow()
    })

    return jsonify({"success": True, "message": f"✅ টাস্ক সম্পন্ন! Received ৳{reward}"})


# ================= POST VIEW TASK =================
@tasks_bp.route('/api/user/tasks/verify_post_view', methods=["POST"])
@login_required
def verify_post_view():
    uid = session.get("uid")
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"success": False, "message": "User not found"})

    data = request.json
    task_id = data.get("task_id")
    view_duration = data.get("view_duration", 0)
    device_id = data.get("device_id")
    user_ip = request.remote_addr

    task = db_mongo["tasks"].find_one({"task_id": task_id})
    if not task:
        return jsonify({"success": False, "message": "Task not found"})

    if task.get("type") != "post_view":
        return jsonify({"success": False, "message": "Invalid task type"})

    timer = db_mongo["task_timers"].find_one({
        "telegram_id": user["telegram_id"],
        "task_id": task_id,
        "completed": False
    })
    
    if not timer:
        return jsonify({"success": False, "message": "⚠️ আপনি টাস্ক শুরু করেননি বা টাইমার শেষ!"})
    
    if datetime.utcnow() > timer["expires_at"]:
        db_mongo["tasks"].update_one(
            {"task_id": task_id},
            {"$set": {"active": False, "auto_disabled": True}}
        )
        return jsonify({"success": False, "message": "⏰ সময় শেষ! টাস্কটি বন্ধ করা হয়েছে。"})

    required_duration = task.get("view_duration", 30)
    if view_duration < required_duration:
        return jsonify({
            "success": False, 
            "message": f"আপনি {required_duration} সেকেন্ড পুরো দেখেননি। দেখেছেন {view_duration} সেকেন্ড।"
        })

    if task.get("max_users", 0) > 0:
        current = task.get("current_users", 0)
        if current >= task["max_users"]:
            return jsonify({"success": False, "message": f"⚠️ এই টাস্কে আর জায়গা নেই!"})

    admin = get_admin_config()
    global_rules = admin.get("task_rules", {})

    device_check = task.get("device_check", global_rules.get("device_check", True))
    if device_check and device_id:
        if db_mongo["device_tasks"].find_one({"task_id": task_id, "device_id": device_id}):
            return jsonify({"success": False, "message": "এই ডিভাইস ইতিমধ্যে টাস্ক ক্লেইম করেছে。"})

    ip_check = task.get("ip_check", global_rules.get("ip_check", False))
    ip_limit = admin.get("ip_limit_per_hour", 5)
    if ip_check and user_ip:
        now_ts = datetime.utcnow().timestamp()
        ip_record = db_mongo["ip_tasks"].find_one({"task_id": task_id, "ip": user_ip})
        if ip_record and ip_record.get("timestamp", 0) > now_ts - 3600:
            if ip_record.get("count", 0) >= ip_limit:
                return jsonify({"success": False, "message": f"আইপি থেকে প্রতি ঘন্টায় সর্বোচ্চ {ip_limit} বার ক্লেইম করা যাবে。"})

    account_check = task.get("account_check", global_rules.get("account_check", True))
    if account_check:
        if db_mongo["user_tasks"].find_one({"telegram_id": user["telegram_id"], "task_id": task_id}):
            return jsonify({"success": False, "message": "আপনি ইতিমধ্যে এই টাস্ক ক্লেইম করেছেন。"})

    if task_claims_col.find_one({"telegram_id": user["telegram_id"], "task_id": task_id}):
        return jsonify({"success": False, "message": "আপনি ইতিমধ্যে এই টাস্ক সম্পন্ন করেছেন。"})

    # টাকা দিন
    if device_check and device_id:
        db_mongo["device_tasks"].insert_one({"task_id": task_id, "device_id": device_id, "created_at": datetime.utcnow()})

    if ip_check and user_ip:
        now_ts = datetime.utcnow().timestamp()
        db_mongo["ip_tasks"].update_one(
            {"task_id": task_id, "ip": user_ip},
            {"$set": {"timestamp": now_ts}, "$inc": {"count": 1}},
            upsert=True
        )

    if account_check:
        db_mongo["user_tasks"].insert_one({"telegram_id": user["telegram_id"], "task_id": task_id, "created_at": datetime.utcnow()})

    db_mongo["post_views"].insert_one({
        "telegram_id": user["telegram_id"],
        "task_id": task_id,
        "view_duration": view_duration,
        "ip": user_ip,
        "device_id": device_id,
        "created_at": datetime.utcnow()
    })

    reward = task.get("reward", 0)
    currency = task.get("currency", "cash")
    
    if currency == "aaf":
        users_col.update_one({"_id": user["_id"]}, {"$inc": {"aaf": reward}})
    else:
        users_col.update_one({"_id": user["_id"]}, {"$inc": {"cash": reward}})

    users_col.update_one({"_id": user["_id"]}, {"$inc": {"tasks_done": 1}})
    db_mongo["tasks"].update_one({"task_id": task_id}, {"$inc": {"current_users": 1}})

    db_mongo["task_timers"].update_one(
        {"_id": timer["_id"]},
        {"$set": {"completed": True, "completed_at": datetime.utcnow()}}
    )

    serial_number = generate_task_serial()
    task_claims_col.insert_one({
        "telegram_id": user["telegram_id"],
        "task_id": task_id,
        "view_duration": view_duration,
        "reward": reward,
        "currency": currency,
        "status": "approved",
        "serial_number": serial_number,
        "created_at": datetime.utcnow()
    })

    return jsonify({"success": True, "message": f"✅ টাস্ক সম্পন্ন! Received ৳{reward}"})


# ================= SMART CLICK TASK =================
@tasks_bp.route('/api/user/tasks/verify_smart_click', methods=["POST"])
@login_required
def verify_smart_click():
    uid = session.get("uid")
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"success": False, "message": "User not found"})

    data = request.json
    task_id = data.get("task_id")
    click_id = data.get("click_id")
    device_id = data.get("device_id")
    user_ip = request.remote_addr

    task = db_mongo["tasks"].find_one({"task_id": task_id})
    if not task:
        return jsonify({"success": False, "message": "Task not found"})

    if task.get("type") != "smart_click":
        return jsonify({"success": False, "message": "Invalid task type"})

    timer = db_mongo["task_timers"].find_one({
        "telegram_id": user["telegram_id"],
        "task_id": task_id,
        "completed": False
    })
    
    if not timer:
        return jsonify({"success": False, "message": "⚠️ আপনি টাস্ক শুরু করেননি বা টাইমার শেষ!"})
    
    if datetime.utcnow() > timer["expires_at"]:
        db_mongo["tasks"].update_one(
            {"task_id": task_id},
            {"$set": {"active": False, "auto_disabled": True}}
        )
        return jsonify({"success": False, "message": "⏰ সময় শেষ! টাস্কটি বন্ধ করা হয়েছে。"})

    # Adsterra ক্লিক ভেরিফিকেশন
    is_valid, message = verify_adsterra_click(click_id, user["telegram_id"])
    if not is_valid:
        return jsonify({"success": False, "message": f"❌ {message}"})

    if task.get("max_users", 0) > 0:
        current = task.get("current_users", 0)
        if current >= task["max_users"]:
            return jsonify({"success": False, "message": f"⚠️ এই টাস্কে আর জায়গা নেই!"})

    admin = get_admin_config()
    global_rules = admin.get("task_rules", {})

    device_check = task.get("device_check", global_rules.get("device_check", True))
    if device_check and device_id:
        if db_mongo["device_tasks"].find_one({"task_id": task_id, "device_id": device_id}):
            return jsonify({"success": False, "message": "এই ডিভাইস ইতিমধ্যে টাস্ক ক্লেইম করেছে。"})

    ip_check = task.get("ip_check", global_rules.get("ip_check", False))
    ip_limit = admin.get("ip_limit_per_hour", 5)
    if ip_check and user_ip:
        now_ts = datetime.utcnow().timestamp()
        ip_record = db_mongo["ip_tasks"].find_one({"task_id": task_id, "ip": user_ip})
        if ip_record and ip_record.get("timestamp", 0) > now_ts - 3600:
            if ip_record.get("count", 0) >= ip_limit:
                return jsonify({"success": False, "message": f"আইপি থেকে প্রতি ঘন্টায় সর্বোচ্চ {ip_limit} বার ক্লেইম করা যাবে。"})

    account_check = task.get("account_check", global_rules.get("account_check", True))
    if account_check:
        if db_mongo["user_tasks"].find_one({"telegram_id": user["telegram_id"], "task_id": task_id}):
            return jsonify({"success": False, "message": "আপনি ইতিমধ্যে এই টাস্ক ক্লেইম করেছেন。"})

    if task_claims_col.find_one({"telegram_id": user["telegram_id"], "task_id": task_id}):
        return jsonify({"success": False, "message": "আপনি ইতিমধ্যে এই টাস্ক সম্পন্ন করেছেন。"})

    # টাকা দিন
    if device_check and device_id:
        db_mongo["device_tasks"].insert_one({"task_id": task_id, "device_id": device_id, "created_at": datetime.utcnow()})

    if ip_check and user_ip:
        now_ts = datetime.utcnow().timestamp()
        db_mongo["ip_tasks"].update_one(
            {"task_id": task_id, "ip": user_ip},
            {"$set": {"timestamp": now_ts}, "$inc": {"count": 1}},
            upsert=True
        )

    if account_check:
        db_mongo["user_tasks"].insert_one({"telegram_id": user["telegram_id"], "task_id": task_id, "created_at": datetime.utcnow()})

    reward = task.get("reward", 0)
    currency = task.get("currency", "cash")
    
    if currency == "aaf":
        users_col.update_one({"_id": user["_id"]}, {"$inc": {"aaf": reward}})
    else:
        users_col.update_one({"_id": user["_id"]}, {"$inc": {"cash": reward}})

    users_col.update_one({"_id": user["_id"]}, {"$inc": {"tasks_done": 1}})
    db_mongo["tasks"].update_one({"task_id": task_id}, {"$inc": {"current_users": 1}})

    db_mongo["task_timers"].update_one(
        {"_id": timer["_id"]},
        {"$set": {"completed": True, "completed_at": datetime.utcnow()}}
    )

    # Adsterra কনভার্সন রিপোর্ট
    send_conversion_to_adsterra(click_id, reward)

    serial_number = generate_task_serial()
    task_claims_col.insert_one({
        "telegram_id": user["telegram_id"],
        "task_id": task_id,
        "click_id": click_id,
        "reward": reward,
        "currency": currency,
        "status": "approved",
        "serial_number": serial_number,
        "created_at": datetime.utcnow()
    })

    return jsonify({"success": True, "message": f"✅ স্মার্ট ক্লিক সম্পন্ন! Received ৳{reward}"})


# ================= TASK ORDER =================
@tasks_bp.route('/api/task_order/active')
@login_required
def get_active_orders():
    uid = session.get("uid")
    if not uid:
        return jsonify({"orders": []})
    orders = list(task_orders_col.find(
        {"user_id": uid, "status": {"$ne": "completed"}}
    ).sort("created_at", -1))
    for o in orders:
        if "_id" in o:
            o["_id"] = str(o["_id"])
    return jsonify({"orders": orders})


@tasks_bp.route('/api/task_order/submit', methods=["POST"])
@login_required
def submit_task_order():
    uid = session.get("uid")
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"success": False, "message": "User not found"})
    data = request.json
    total_charge = float(data.get("total_charge", 0))
    if user.get("cash", 0) < total_charge:
        return jsonify({"success": False, "message": "Insufficient balance"})
    users_col.update_one({"_id": ObjectId(uid)}, {"$inc": {"cash": -total_charge}})
    order = {
        "user_id": uid,
        "telegram_id": user.get("telegram_id"),
        "link": data.get("link"),
        "service": data.get("service"),
        "quantity": data.get("quantity"),
        "total_charge": total_charge,
        "progress": 0,
        "status": "pending",
        "created_at": datetime.utcnow()
    }
    task_orders_col.insert_one(order)
    return jsonify({"success": True, "message": "Order submitted"})
