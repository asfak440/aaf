from flask import Blueprint, render_template, request, jsonify, session
from datetime import datetime
from bson import ObjectId

from app import users_col, task_claims_col, milestones_col, user_milestone_claims_col
from app.utils.decorators import login_required

account_bp = Blueprint('account', __name__, url_prefix='/account')

# ================= PAGE ROUTES =================
@account_bp.route('/')
@login_required
def account():
    return render_template("account.html")

@account_bp.route('/refer_list')
@login_required
def refer_list():
    return render_template("refer_list.html")

# ================= ACCOUNT APIs =================
@account_bp.route('/api/user/referrals/<telegram_id>')
@login_required
def get_referrals(telegram_id):
    uid = session.get("uid")
    user = users_col.find_one({"telegram_id": telegram_id})
    if not user or str(user["_id"]) != uid:
        return jsonify({"status": "error", "message": "unauthorized"})
    referrals = users_col.find({"refer_by": telegram_id}, {"username": 1, "telegram_id": 1, "created_at": 1})
    ref_list = []
    for r in referrals:
        ref_list.append({
            "username": r.get("username", "USER"),
            "telegram_id": r.get("telegram_id"),
            "joined_at": r.get("created_at").isoformat() if r.get("created_at") else ""
        })
    return jsonify({"referrals": ref_list})

@account_bp.route('/api/user/milestones', methods=['GET'])
@login_required
def user_milestones():
    uid = session.get('uid')
    if not uid:
        return jsonify({"milestones": []})
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"milestones": []})

    task_count = task_claims_col.count_documents({"telegram_id": user["telegram_id"], "status": "approved"})
    referral_count = user.get("refer_count", 0)
    deposit_total = user.get("total_deposit", 0)

    milestones = list(milestones_col.find({"active": True}))
    result = []
    for m in milestones:
        if m['type'] == 'task':
            progress = task_count
        elif m['type'] == 'referral':
            progress = referral_count
        else:
            progress = deposit_total

        achieved = progress >= m['target']
        already_claimed = user_milestone_claims_col.find_one({"user_id": uid, "milestone_id": str(m['_id'])}) is not None

        result.append({
            "id": str(m['_id']),
            "type": m['type'],
            "target": m['target'],
            "reward_amount": m['reward_amount'],
            "reward_type": m['reward_type'],
            "days": m.get('days'),
            "progress": progress,
            "achieved": achieved,
            "already_claimed": already_claimed
        })
    return jsonify({"milestones": result})

@account_bp.route('/api/user/claim_milestone', methods=['POST'])
@login_required
def claim_milestone():
    uid = session.get('uid')
    if not uid:
        return jsonify({"success": False, "error": "Login required"})
    data = request.json
    milestone_id = data.get('milestone_id')
    if not milestone_id:
        return jsonify({"success": False, "error": "Missing milestone_id"})

    milestone = milestones_col.find_one({"_id": ObjectId(milestone_id), "active": True})
    if not milestone:
        return jsonify({"success": False, "error": "Milestone not found"})

    if user_milestone_claims_col.find_one({"user_id": uid, "milestone_id": milestone_id}):
        return jsonify({"success": False, "error": "Already claimed"})

    user = users_col.find_one({"_id": ObjectId(uid)})
    task_count = task_claims_col.count_documents({"telegram_id": user["telegram_id"], "status": "approved"})
    referral_count = user.get("refer_count", 0)
    deposit_total = user.get("total_deposit", 0)

    if milestone['type'] == 'task':
        progress = task_count
    elif milestone['type'] == 'referral':
        progress = referral_count
    else:
        progress = deposit_total

    if progress < milestone['target']:
        return jsonify({"success": False, "error": "Target not reached"})

    if milestone['reward_type'] == 'bdt':
        users_col.update_one({"_id": ObjectId(uid)}, {"$inc": {"cash": milestone['reward_amount']}})
    else:
        users_col.update_one({"_id": ObjectId(uid)}, {"$inc": {"aaf": milestone['reward_amount']}})

    user_milestone_claims_col.insert_one({
        "user_id": uid,
        "milestone_id": milestone_id,
        "claimed_at": datetime.utcnow()
    })
    return jsonify({"success": True})
