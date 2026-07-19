from flask import Blueprint, render_template, request, jsonify, session
from datetime import datetime
from bson import ObjectId
import telebot
from telebot.apihelper import ApiTelegramException

from app import users_col, admin_config_col, deposits_col, withdraws_col, trades_col, channel_status_col
from app.utils.decorators import login_required
from app.utils.helpers import get_admin_config

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template("dashboard.html")

@dashboard_bp.route('/api/user/me')
def user_me():
    uid = session.get("uid")
    if not uid:
        return jsonify({"status": "error", "message": "session_expired"})
    
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        session.clear()
        return jsonify({"status": "error", "message": "user_not_found"})
    
    admin = get_admin_config()
    wallet_data = admin.get("wallet", {"nagad": "", "bkash": ""})
    
    # স্ট্যাটিস্টিক্স
    real_users = users_col.count_documents({})
    deposits = list(deposits_col.aggregate([
        {"$match": {"status": "approved"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]))
    total_deposit = deposits[0]["total"] if deposits else 0
    
    withdraws = list(withdraws_col.aggregate([
        {"$match": {"status": "approved"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]))
    total_withdraw = withdraws[0]["total"] if withdraws else 0
    
    auto_income = total_deposit - total_withdraw
    
    trades = list(trades_col.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]))
    auto_trading = trades[0]["total"] if trades else 0
    
    manual_income = admin.get("server_income", 0)
    manual_trading = admin.get("server_trading", 0)
    manual_users = admin.get("extra_users", 0)
    
    final_income = auto_income + manual_income
    final_trading = auto_trading + manual_trading
    final_users = real_users + manual_users
    
    safe_user = {
        "_id": str(user["_id"]),
        "telegram_id": user.get("telegram_id"),
        "username": user.get("username"),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "cash": user.get("cash", 0),
        "aaf": user.get("aaf", 0),
        "refer_count": user.get("refer_count", 0),
        "tasks_done": user.get("tasks_done", 0),
        # ❌ is_joined সরিয়ে দেওয়া হয়েছে (ডাটাবেসে জমা হবে না)
        "phone": user.get("phone", "")
    }
    
    safe_admin = {
        "live_price": admin.get("live_price", 1.0),
        "trading_fee": admin.get("trading_fee", 0.5),
        "banner_ad_code": admin.get("banner_ad_code", ""),
        "trading_ad_text": admin.get("trading_ad_text", ""),
        "server_income": final_income,
        "server_trading": final_trading,
        "total_users": final_users,
        "referral_bonus": admin.get("referral_bonus", 0),
        "wallet": {
            "nagad": wallet_data.get("nagad", ""),
            "bkash": wallet_data.get("bkash", "")
        }
    }
    
    response = jsonify({"status": "success", "user": safe_user, "admin": safe_admin})
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response
    
@dashboard_bp.route('/api/user/data/<telegram_id>')
def user_data(telegram_id):
    uid = session.get("uid")
    if not uid:
        return jsonify({"status": "error", "message": "session_expired"})
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        session.clear()
        return jsonify({"status": "error", "message": "user_not_found"})
    admin = get_admin_config()
    wallet_data = admin.get("wallet", {"nagad": "", "bkash": ""})
    safe_user = {
        "_id": str(user["_id"]),
        "telegram_id": user.get("telegram_id"),
        "username": user.get("username"),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "cash": user.get("cash", 0),
        "aaf": user.get("aaf", 0)
    }
    safe_admin = {
        "banner_ad_code": admin.get("banner_ad_code", ""),
        "server_income": admin.get("server_income", 0),
        "server_trading": admin.get("server_trading", 0),
        "referral_bonus": admin.get("referral_bonus", 0),
        "wallet": {
            "nagad": wallet_data.get("nagad", ""),
            "bkash": wallet_data.get("bkash", "")
        }
    }
    return jsonify({"status": "success", "user": safe_user, "admin": safe_admin})

@dashboard_bp.route('/api/silent_join', methods=["POST"])
@login_required
def silent_join():
    admin = get_admin_config()
    channel_url = admin.get("channel_url", "")
    return jsonify({"success": False, "channel": channel_url})

@dashboard_bp.route('/api/verify_join', methods=["POST"])
@login_required
def verify_join():
    uid = session.get("uid")
    if not uid:
        return jsonify({"success": False, "message": "Not logged in"})
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"success": False, "message": "User not found"})
    admin = get_admin_config()
    bot_token = admin.get("bot_token")
    channel_url = admin.get("channel_url", "")
    if not bot_token or not channel_url:
        return jsonify({"success": False, "message": "Bot or channel not configured"})
    try:
        user_tg_id = int(user.get("telegram_id"))
    except:
        return jsonify({"success": False, "message": "Invalid Telegram ID"})
    if "t.me/" in channel_url:
        channel_username = "@" + channel_url.split("t.me/")[-1].split("/")[0]
    elif channel_url.startswith("@"):
        channel_username = channel_url
    else:
        channel_username = "@" + channel_url
    try:
        bot = telebot.TeleBot(bot_token)
        chat_member = bot.get_chat_member(channel_username, user_tg_id)
        is_member = chat_member.status in ["member", "creator", "administrator"]
        channel_status_col.update_one(
            {"user_id": uid},
            {"$set": {"is_member": is_member, "last_checked": datetime.utcnow()}},
            upsert=True
        )
        if is_member:
            users_col.update_one({"_id": ObjectId(uid)}, {"$set": {"is_joined": True}})
            return jsonify({"success": True})
        else:
            users_col.update_one({"_id": ObjectId(uid)}, {"$set": {"is_joined": False}})
            return jsonify({"success": False, "channel": channel_url})
    except ApiTelegramException as e:
        return jsonify({"success": False, "channel": channel_url, "message": "Bot not admin in channel"})
    except Exception as e:
        return jsonify({"success": False, "channel": channel_url, "message": "Server error"})

@dashboard_bp.route('/api/check_membership', methods=["GET"])
@login_required
def check_membership():
    uid = session.get("uid")
    if not uid:
        return jsonify({"is_member": False})
    
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"is_member": False})
    
    admin = get_admin_config()
    
    # ✅ ড্যাশবোর্ড বটের টোকেন ব্যবহার করুন
    bot_token = admin.get("dashboard_bot_token") or admin.get("bot_token")
    channel_url = admin.get("official_channel") or admin.get("channel_url", "")
    
    if not bot_token or not channel_url:
        return jsonify({"is_member": False, "error": "Bot not configured"})
    
    try:
        user_tg_id = int(user.get("telegram_id"))
        
        if "t.me/" in channel_url:
            channel_username = "@" + channel_url.split("t.me/")[-1].split("/")[0]
        elif channel_url.startswith("@"):
            channel_username = channel_url
        else:
            channel_username = "@" + channel_url
        
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/getChatMember?chat_id={channel_username}&user_id={user_tg_id}"
        resp = requests.get(url, headers={"Cache-Control": "no-cache"}, timeout=10)
        data = resp.json()
        
        if data.get("ok"):
            status = data["result"]["status"]
            is_member = status in ("member", "administrator", "creator")
        else:
            is_member = False
        
        response = jsonify({
            "is_member": is_member,
            "status": status if data.get("ok") else "unknown"
        })
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response
        
    except Exception as e:
        print(f"Check membership error: {e}")
        return jsonify({"is_member": False, "error": str(e)})
        
@dashboard_bp.route('/api/dashboard/stats')
@login_required
def dashboard_stats():
    admin = get_admin_config()
    real_users = users_col.count_documents({})
    deposits = list(deposits_col.aggregate([
        {"$match": {"status": "approved"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]))
    total_deposit = deposits[0]["total"] if deposits else 0
    withdraws = list(withdraws_col.aggregate([
        {"$match": {"status": "approved"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]))
    total_withdraw = withdraws[0]["total"] if withdraws else 0
    auto_income = total_deposit - total_withdraw
    trades = list(trades_col.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]))
    auto_trading = trades[0]["total"] if trades else 0
    manual_income = admin.get("server_income", 0)
    manual_trading = admin.get("server_trading", 0)
    manual_users = admin.get("extra_users", 0)
    final_income = auto_income + manual_income
    final_trading = auto_trading + manual_trading
    final_users = real_users + manual_users
    return jsonify({
        "success": True,
        "server_income": final_income,
        "trading_volume": final_trading,
        "total_users": final_users,
        "auto_income": auto_income,
        "auto_trading": auto_trading,
        "auto_users": real_users,
        "manual_income": manual_income,
        "manual_trading": manual_trading,
        "manual_users": manual_users
    })
