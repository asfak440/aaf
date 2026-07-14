from flask import Blueprint, render_template, request, jsonify, session
from datetime import datetime
from bson import ObjectId

from app import users_col, deposits_col, withdraws_col
from app.utils.decorators import login_required
from app.utils.helpers import get_admin_config, remove_old_tasks_by_amount
from app.services.telegram_service import send_telegram_message

wallet_bp = Blueprint('wallet', __name__, url_prefix='/wallet')

# ================= PAGE ROUTES =================
@wallet_bp.route('/')
@login_required
def wallet():
    return render_template("wallet.html")

@wallet_bp.route('/history')
@login_required
def payment_history():
    return render_template("payment_history.html")

# ================= WALLET APIs =================
@wallet_bp.route('/api/wallet/deposit', methods=["POST"])
@login_required
def deposit_request():
    uid = session.get("uid")
    if not uid:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.json
    method = data.get("method")
    amount = float(data.get("amount", 0))
    reference = data.get("reference") or data.get("trx")

    if not method or amount <= 0 or not reference:
        return jsonify({"status": "error", "message": "Method, amount and transaction ID required"}), 400

    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    existing = deposits_col.find_one({"reference": reference})
    if existing:
        return jsonify({"status": "error", "message": "This transaction ID already submitted"}), 400

    deposits_col.insert_one({
        "telegram_id": user.get("telegram_id"),
        "method": method,
        "amount": amount,
        "reference": reference,
        "status": "pending",
        "created_at": datetime.utcnow()
    })

    return jsonify({"status": "success", "message": f"Deposit request of ৳{amount} submitted. Wait for admin approval."})

@wallet_bp.route('/api/wallet/withdraw', methods=["POST"])
@login_required
def withdraw_request():
    uid = session.get("uid")
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    data = request.json
    amount = float(data.get("amount", 0))
    account_number = data.get("account_number", "").strip()

    # চেক: টাকা তোলার আগে টাস্ক চেক
    # (check_all_user_tasks ফাংশনটি যদি থাকে, তাহলে এখানে যোগ করুন)
    # বর্তমানে সরাসরি চেক করছি না

    if user.get("cash", 0) < amount:
        return jsonify({"status": "error", "message": "Insufficient balance"}), 400

    if amount < 100:
        return jsonify({"status": "error", "message": "Minimum withdrawal is ৳100"}), 400

    withdraws_col.insert_one({
        "telegram_id": user["telegram_id"],
        "account_number": account_number,
        "amount": amount,
        "status": "pending",
        "created_at": datetime.utcnow()
    })

    deleted_count = remove_old_tasks_by_amount(user["telegram_id"], amount)
    if deleted_count > 0:
        send_telegram_message(
            user["telegram_id"],
            f"🧹 **{amount} টাকা তোলার পর {deleted_count} টি পুরনো টাস্ক রিমুভ করা হয়েছে!**"
        )

    return jsonify({
        "status": "success",
        "message": f"Withdraw of ৳{amount} submitted. {deleted_count} old tasks removed."
    })

@wallet_bp.route('/api/wallet/transfer', methods=["POST"])
@login_required
def transfer_funds():
    uid = session.get("uid")
    if not uid:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.json
    transfer_type = data.get("type")
    receiver_tg_id = str(data.get("receiver_id") or data.get("to") or "").strip()
    amount = float(data.get("amount", 0))

    if not receiver_tg_id or amount <= 0:
        return jsonify({"status": "error", "message": "Receiver ID and valid amount required"}), 400

    if transfer_type not in ["cash", "coin", "aaf"]:
        return jsonify({"status": "error", "message": "Invalid transfer type. Use 'cash' or 'coin'"}), 400

    sender = users_col.find_one({"_id": ObjectId(uid)})
    if not sender:
        return jsonify({"status": "error", "message": "Sender not found"}), 404

    if sender.get("telegram_id") == receiver_tg_id:
        return jsonify({"status": "error", "message": "Cannot transfer to yourself"}), 400

    receiver = users_col.find_one({"telegram_id": receiver_tg_id})
    if not receiver:
        return jsonify({"status": "error", "message": f"User {receiver_tg_id} not found"}), 404

    if transfer_type == "cash":
        if sender.get("cash", 0) < amount:
            return jsonify({"status": "error", "message": f"Insufficient cash. Available: ৳{sender.get('cash', 0)}"}), 400
        users_col.update_one({"_id": sender["_id"]}, {"$inc": {"cash": -amount}})
        users_col.update_one({"_id": receiver["_id"]}, {"$inc": {"cash": amount}})
        message = f"Successfully transferred ৳{amount} to {receiver.get('username', receiver_tg_id)}"
    else:
        coin_balance = sender.get("aaf", 0)
        if coin_balance < amount:
            return jsonify({"status": "error", "message": f"Insufficient AAF coins. Available: {coin_balance}"}), 400
        users_col.update_one({"_id": sender["_id"]}, {"$inc": {"aaf": -amount}})
        users_col.update_one({"_id": receiver["_id"]}, {"$inc": {"aaf": amount}})
        message = f"Successfully transferred {amount} AAF coins to {receiver.get('username', receiver_tg_id)}"

    return jsonify({"status": "success", "message": message})

@wallet_bp.route('/api/user/payments/<telegram_id>')
@login_required
def get_payments(telegram_id):
    uid = session.get("uid")
    user = users_col.find_one({"telegram_id": telegram_id})
    if not user or str(user["_id"]) != uid:
        return jsonify({"status": "error", "message": "unauthorized"})
    deposits = list(deposits_col.find({"telegram_id": telegram_id}, {"_id": 0, "amount": 1, "status": 1, "created_at": 1}))
    withdraws = list(withdraws_col.find({"telegram_id": telegram_id}, {"_id": 0, "amount": 1, "number": 1, "status": 1, "created_at": 1}))
    for d in deposits:
        d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else ""
    for w in withdraws:
        w["created_at"] = w["created_at"].isoformat() if w.get("created_at") else ""
    return jsonify({"deposits": deposits, "withdraws": withdraws})
