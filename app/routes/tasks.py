from flask import Blueprint, render_template, request, jsonify, session
from datetime import datetime, timedelta
from bson import ObjectId
import secrets
import hashlib

from app import users_col, db_mongo, task_claims_col, task_orders_col, deeplink_clicks_col, admin_config_col, task_channel_status_col, device_tasks_col, ip_tasks_col, user_tasks_col, cache_col, rate_limits_col
from app.utils.decorators import login_required
from app.utils.helpers import get_admin_config, generate_task_serial, run_async
from app.services.telegram_service import verify_user_task_smart, send_telegram_message

tasks_bp = Blueprint('tasks', __name__, url_prefix='/tasks')

# ================= PAGE ROUTES =================
@tasks_bp.route('/')
@login_required
def task():
    return render_template("task.html")

@tasks_bp.route('/order')
@login_required
def task_order():
    return render_template("task_order.html")

# ================= TASK APIs =================
@tasks_bp.route('/api/tasks')
def get_tasks():
    tasks = list(db_mongo["tasks"].find({"active": True}))
    task_list = []
    for t in tasks:
        t["id"] = t.get("task_id", str(t["_id"]))
        t["_id"] = str(t["_id"])
        task_list.append(t)
    return jsonify({"tasks": task_list})

@tasks_bp.route('/api/user/claimed_tasks')
@login_required
def get_claimed_tasks():
    uid = session.get("uid")
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"claimed_ids": []})
    claims = task_claims_col.find({"telegram_id": user["telegram_id"], "status": "approved"})
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
        message = f"⚠️ আপনার {total_due}টি টাস্কের চ্যানেলে ডিউ আছে। প্রতিটি টাস্ক কমপ্লিট করলে ১ টাকা করে কাটা হবে। চ্যানেলে পুনরায় জয়েন করুন এবং VERIFY চাপুন।"
    return jsonify({
        "success": True,
        "due": total_due,
        "is_member": total_due == 0,
        "message": message,
        "details": details
    })

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

    # MAX_USERS চেক
    if task.get("max_users", 0) > 0:
        current = task.get("current_users", 0)
        if current >= task["max_users"]:
            return jsonify({
                "success": False, 
                "message": f"⚠️ এই টাস্কে আর জায়গা নেই! (সর্বোচ্চ {task['max_users']} জন)"
            })

    admin = get_admin_config()
    global_rules = admin.get("task_rules", {})

    # ডিভাইস চেক
    device_check = task.get("device_check", global_rules.get("device_check", True))
    if device_check and device_id:
        if db_mongo["device_tasks"].find_one({"task_id": task_id, "device_id": device_id}):
            return jsonify({"success": False, "message": "এই ডিভাইস ইতিমধ্যে টাস্ক ক্লেইম করেছে।"})

    # আইপি চেক
    ip_check = task.get("ip_check", global_rules.get("ip_check", False))
    ip_limit = admin.get("ip_limit_per_hour", 5)
    if ip_check and user_ip:
        now_ts = datetime.utcnow().timestamp()
        ip_record = db_mongo["ip_tasks"].find_one({"task_id": task_id, "ip": user_ip})
        if ip_record and ip_record.get("timestamp", 0) > now_ts - 3600:
            if ip_record.get("count", 0) >= ip_limit:
                return jsonify({"success": False, "message": f"আইপি থেকে প্রতি ঘন্টায় সর্বোচ্চ {ip_limit} বার ক্লেইম করা যাবে।"})

    # অ্যাকাউন্ট চেক
    account_check = task.get("account_check", global_rules.get("account_check", True))
    if account_check:
        if db_mongo["user_tasks"].find_one({"telegram_id": user["telegram_id"], "task_id": task_id}):
            return jsonify({"success": False, "message": "আপনি ইতিমধ্যে এই টাস্ক ক্লেইম করেছেন।"})

    if task_claims_col.find_one({"telegram_id": user["telegram_id"], "task_id": task_id}):
        return jsonify({"success": False, "message": "আপনি ইতিমধ্যে এই টাস্ক সম্পন্ন করেছেন।"})

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
        return jsonify({"success": False, "message": "আপনি এখনো চ্যানেলে জয়েন করেননি।"})

    # সব চেক পাস — সেভ ও টাকা দিন
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

    task_channel_status = task_channel_status_col.find_one({"user_id": str(user["_id"]), "task_id": task_id})

    reward = task.get("reward", 0)
    currency = task.get("currency", "cash")
    final_reward = reward

    if task_channel_status and task_channel_status.get("is_member") == False:
        due_amount = admin.get("task_channel_leave_penalty", 50)
        final_reward = max(0, reward - due_amount)
        task_channel_status_col.update_one(
            {"user_id": str(user["_id"]), "task_id": task_id},
            {"$set": {"due_cleared": True}}
        )

    if currency == "aaf":
        users_col.update_one({"_id": user["_id"]}, {"$inc": {"aaf": final_reward}})
    else:
        users_col.update_one({"_id": user["_id"]}, {"$inc": {"cash": final_reward}})

    if final_reward != reward:
        msg = f"✅ টাস্ক সম্পন্ন! ডিউ কাটা হয়েছে: -৳{reward - final_reward}"
    else:
        msg = f"✅ টাস্ক সম্পন্ন! Received ৳{final_reward}"

    users_col.update_one({"_id": user["_id"]}, {"$inc": {"tasks_done": 1}})
    db_mongo["tasks"].update_one(
        {"task_id": task_id},
        {"$inc": {"current_users": 1}}
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

    return jsonify({"success": True, "message": msg})

@tasks_bp.route('/api/user/tasks/verify_deeplink', methods=["POST"])
@login_required
def verify_deeplink_task():
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

    admin = get_admin_config()
    global_rules = admin.get("task_rules", {})

    device_check = task.get("device_check", global_rules.get("device_check", True))
    if device_check and device_id:
        if db_mongo["device_tasks"].find_one({"task_id": task_id, "device_id": device_id}):
            return jsonify({"success": False, "message": "এই ডিভাইস ইতিমধ্যে টাস্ক ক্লেইম করেছে।"})

    ip_check = task.get("ip_check", global_rules.get("ip_check", False))
    ip_limit = admin.get("ip_limit_per_hour", 5)
    if ip_check and user_ip:
        now_ts = datetime.utcnow().timestamp()
        ip_record = db_mongo["ip_tasks"].find_one({"task_id": task_id, "ip": user_ip})
        if ip_record and ip_record.get("timestamp", 0) > now_ts - 3600:
            if ip_record.get("count", 0) >= ip_limit:
                return jsonify({"success": False, "message": f"আইপি থেকে প্রতি ঘন্টায় সর্বোচ্চ {ip_limit} বার ক্লেইম করা যাবে।"})

    account_check = task.get("account_check", global_rules.get("account_check", True))
    if account_check:
        if db_mongo["user_tasks"].find_one({"telegram_id": user["telegram_id"], "task_id": task_id}):
            return jsonify({"success": False, "message": "আপনি ইতিমধ্যে এই টাস্ক ক্লেইম করেছেন।"})

    if task_claims_col.find_one({"telegram_id": user["telegram_id"], "task_id": task_id}):
        return jsonify({"success": False, "message": "আপনি ইতিমধ্যে এই টাস্ক সম্পন্ন করেছেন।"})

    record = deeplink_clicks_col.find_one({"telegram_id": user["telegram_id"], "task_id": f"task_{task_id}"})
    if not record:
        return jsonify({"success": False, "message": "আপনি এখনো নির্দিষ্ট লিংকে ক্লিক করেননি। লিংকে ক্লিক করে আবার VERIFY চাপুন।"})

    # সব চেক পাস — সেভ
    if device_check and device_id:
        db_mongo["device_tasks"].insert_one({"task_id": task_id, "device_id": device_id, "created_at": datetime.utcnow()})

    if ip_check and user_ip:
        db_mongo["ip_tasks"].update_one(
            {"task_id": task_id, "ip": user_ip},
            {"$set": {"timestamp": datetime.utcnow().timestamp()}, "$inc": {"count": 1}},
            upsert=True
        )

    if account_check:
        db_mongo["user_tasks"].insert_one({"telegram_id": user["telegram_id"], "task_id": task_id, "created_at": datetime.utcnow()})

    task_channel_status = task_channel_status_col.find_one({"user_id": str(user["_id"]), "task_id": task_id})

    reward = task.get("reward", 0)
    currency = task.get("currency", "cash")
    final_reward = reward

    if task_channel_status and task_channel_status.get("is_member") == False:
        due_amount = admin.get("task_channel_leave_penalty", 50)
        final_reward = max(0, reward - due_amount)
        task_channel_status_col.update_one(
            {"user_id": str(user["_id"]), "task_id": task_id},
            {"$set": {"due_cleared": True}}
        )

    if currency == "aaf":
        users_col.update_one({"_id": user["_id"]}, {"$inc": {"aaf": final_reward}})
    else:
        users_col.update_one({"_id": user["_id"]}, {"$inc": {"cash": final_reward}})

    users_col.update_one({"_id": user["_id"]}, {"$inc": {"tasks_done": 1}})

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

    msg = f"✅ টাস্ক সম্পন্ন! সিরিয়াল: {serial_number} | Received ৳{final_reward}"
    return jsonify({"success": True, "message": msg})

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

@tasks_bp.route('/api/user/check_stat')
@login_required
def user_check_stat():
    uid = session.get("uid")
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"success": False, "message": "User not found"})

    link = request.args.get("link", "").strip()
    session_owner = request.args.get("session_owner", "").strip()

    if not link:
        return jsonify({"success": False, "message": "Link is required"})

    if "t.me/" not in link:
        if link.startswith("@"):
            link = f"https://t.me/{link[1:]}"
        elif not link.startswith("https://"):
            link = f"https://t.me/{link}"

    now = datetime.utcnow()
    cache_key_data = f"{uid}_{link}_{session_owner}"
    cache_key = hashlib.md5(cache_key_data.encode()).hexdigest()
    cached = cache_col.find_one({"cache_key": cache_key})
    if cached and (now - cached["created_at"]).total_seconds() < 300:
        return jsonify(cached["data"])

    one_minute_ago = now - timedelta(minutes=1)
    recent = rate_limits_col.count_documents({
        "user_id": uid,
        "created_at": {"$gte": one_minute_ago}
    })
    if recent >= 3:
        return jsonify({
            "success": False,
            "message": "⏳ প্রতি মিনিটে ৩ বার পর্যন্ত। কিছুক্ষণ পর ট্রাই করুন।"
        })

    total_recent = rate_limits_col.count_documents({
        "created_at": {"$gte": one_minute_ago}
    })
    if total_recent >= 20:
        return jsonify({
            "success": False,
            "message": "⏳ সার্ভার ব্যস্ত! কিছুক্ষণ পর ট্রাই করুন।"
        })

    rate_limits_col.insert_one({
        "user_id": uid,
        "endpoint": "check_stat",
        "created_at": now
    })

    session_string = None
    checked_by = None

    if session_owner:
        target_user = users_col.find_one({"telegram_id": session_owner})
        if target_user and target_user.get("session_string"):
            session_string = target_user["session_string"]
            checked_by = target_user.get("first_name", session_owner)
        else:
            return jsonify({"success": False, "message": "Selected user session not found"})
    else:
        session_string = user.get("session_string")
        checked_by = user.get("first_name")

    if not session_string:
        return jsonify({"success": False, "message": "No session found. Please login first."})

        async def check():
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from app import API_ID, API_HASH

        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                return {"success": False, "message": "Session expired. Please login again."}

            clean_link = link.replace("https://t.me/", "").replace("t.me/", "")
            parts = clean_link.split("/")
            channel_username = parts[0]
            post_id = int(parts[1]) if len(parts) > 1 else None

            try:
                entity = await client.get_entity(channel_username)
            except Exception as e:
                error_msg = str(e).lower()
                if "username not found" in error_msg or "not found" in error_msg:
                    return {"success": False, "message": "❌ চ্যানেল বা ইউজারনেম পাওয়া যায়নি"}
                elif "private" in error_msg:
                    return {"success": False, "message": "🔒 প্রাইভেট চ্যানেল - অ্যাক্সেস নেই"}
                elif "flood" in error_msg:
                    return {"success": False, "message": "⚠️ অতিরিক্ত রিকোয়েস্ট! কিছুক্ষণ পর চেষ্টা করুন"}
                else:
                    return {"success": False, "message": f"❌ চ্যানেল অ্যাক্সেস এরর: {str(e)}"}

            try:
                me = await client.get_me()
                try:
                    await client.get_permissions(entity, me)
                    user_is_member = True
                except:
                    user_is_member = False
            except:
                user_is_member = False

            if post_id:
                try:
                    message = await client.get_messages(entity, ids=post_id)
                    if not message:
                        return {"success": False, "message": f"❌ পোস্ট {post_id} পাওয়া যায়নি"}
                except Exception as e:
                    return {"success": False, "message": f"❌ পোস্ট ফেচ করতে ব্যর্থ: {str(e)}"}

                if message.photo:
                    media_type = "📷 ফটো"
                elif message.video:
                    media_type = "🎥 ভিডিও"
                elif message.document:
                    media_type = "📄 ডকুমেন্ট"
                elif message.audio:
                    media_type = "🎵 অডিও"
                elif message.gif:
                    media_type = "🎬 GIF"
                else:
                    media_type = "📝 টেক্সট"

                result = {
                    "success": True,
                    "type": "post",
                    "channel_title": entity.title,
                    "channel_username": channel_username,
                    "post_id": post_id,
                    "views": getattr(message, 'views', 0),
                    "forwards": getattr(message, 'forwards', 0),
                    "date": str(message.date),
                    "text": message.text[:500] if message.text else "[মিডিয়া মেসেজ]",
                    "media_type": media_type,
                    "user_is_member": user_is_member,
                    "member_status": "✅ জয়েন করেছেন" if user_is_member else "❌ জয়েন করেননি",
                    "post_link": f"https://t.me/{channel_username}/{post_id}"
                }
                if checked_by:
                    result["checked_by"] = checked_by
                try:
                    if hasattr(message, 'reactions') and message.reactions:
                        reactions = {}
                        for r in message.reactions.results:
                            emoticon = getattr(r.reaction, 'emoticon', '👍')
                            reactions[emoticon] = r.count
                        result["reactions"] = reactions
                except:
                    pass
                try:
                    if hasattr(message, 'replies') and message.replies:
                        result["replies_count"] = message.replies.replies
                except:
                    pass
                if not hasattr(entity, 'broadcast'):
                    try:
                        participants = await client.get_participants(entity, limit=50)
                        result["recent_members"] = [
                            {"id": p.id, "name": p.first_name or "", "username": p.username or ""}
                            for p in participants[:20] if p
                        ]
                        result["total_members"] = len(participants) if participants else "N/A"
                    except Exception:
                        result["recent_members"] = []
                        result["total_members"] = "N/A"
                return result

            else:
                result = {
                    "success": True,
                    "type": "channel" if hasattr(entity, 'broadcast') else "group",
                    "title": entity.title,
                    "username": channel_username,
                    "is_public": bool(entity.username),
                    "description": "",
                    "members": "লোড হচ্ছে...",
                    "user_is_member": user_is_member,
                    "member_status": "✅ জয়েন করেছেন" if user_is_member else "❌ জয়েন করেননি"
                }
                if checked_by:
                    result["checked_by"] = checked_by
                try:
                    if hasattr(entity, 'broadcast'):
                        full = await client.get_full_channel(entity)
                        result["description"] = full.full_chat.about or ''
                        if hasattr(full, 'participants_count') and full.participants_count:
                            result["members"] = full.participants_count
                        elif hasattr(full.full_chat, 'participants_count'):
                            result["members"] = full.full_chat.participants_count
                    else:
                        full = await client.get_full_chat(entity)
                        result["description"] = full.about or ''
                        if hasattr(full, 'participants_count'):
                            result["members"] = full.participants_count
                        try:
                            participants = await client.get_participants(entity, limit=20)
                            result["recent_members"] = [
                                {"id": p.id, "name": p.first_name or "", "username": p.username or ""}
                                for p in participants[:20] if p
                            ]
                        except:
                            pass
                except Exception as e:
                    result["members"] = "N/A (সীমাবদ্ধ)"
                return result

        except Exception as e:
            return {"success": False, "message": f"Unexpected error: {str(e)}"}
        finally:
            await client.disconnect()

    try:
        data = run_async(check())
        if data.get("success"):
            cache_col.update_one(
                {"cache_key": cache_key},
                {"$set": {"data": data, "created_at": now}},
                upsert=True
            )
        return jsonify(data)
    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"})
