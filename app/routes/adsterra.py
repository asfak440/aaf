from flask import Blueprint, request, jsonify
from datetime import datetime
from app import adsterra_clicks_col, users_col  # ← যোগ করুন

adsterra_bp = Blueprint('adsterra', __name__, url_prefix='/adsterra')


# ================= হেল্পার ফাংশন (adsterra_utils ছাড়া) =================
def track_adsterra_click(click_id, telegram_id, task_id, ip, user_agent):
    """Adsterra ক্লিক ট্র্যাক করুন (সরাসরি এখানে)"""
    try:
        # চেক করুন ইউজার আছে কিনা
        user = users_col.find_one({"telegram_id": telegram_id})
        if not user:
            return False, "User not found"
        
        # ক্লিক রেকর্ড করুন
        adsterra_clicks_col.insert_one({
            "click_id": click_id,
            "telegram_id": telegram_id,
            "task_id": task_id,
            "ip": ip,
            "user_agent": user_agent,
            "created_at": datetime.utcnow(),
            "converted": False
        })
        return True, "Click tracked"
    except Exception as e:
        return False, str(e)


@adsterra_bp.route('/postback', methods=['GET', 'POST'])
def adsterra_postback():
    """Adsterra থেকে Postback রিসিভ করুন"""
    try:
        if request.method == 'GET':
            data = request.args
        else:
            data = request.json or request.form

        click_id = data.get('click_id') or data.get('subid') or data.get('subid_short')

        if not click_id:
            return jsonify({"error": "Missing click_id"}), 400

        # ক্লিক রেকর্ড চেক করুন
        click_record = adsterra_clicks_col.find_one({"click_id": click_id})

        if not click_record:
            click_record = {
                "click_id": click_id,
                "telegram_id": None,
                "ip": request.remote_addr,
                "user_agent": request.headers.get('User-Agent'),
                "created_at": datetime.utcnow(),
                "converted": False
            }
            adsterra_clicks_col.insert_one(click_record)

        # কনভার্সন আপডেট করুন
        adsterra_clicks_col.update_one(
            {"click_id": click_id},
            {"$set": {"converted": True, "converted_at": datetime.utcnow()}}
        )

        return jsonify({"status": "success"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@adsterra_bp.route('/click_track', methods=['POST'])
def track_click():
    """Adsterra ক্লিক ট্র্যাক করুন"""
    data = request.json
    click_id = data.get('click_id')
    telegram_id = data.get('telegram_id')
    task_id = data.get('task_id')

    if not click_id or not telegram_id:
        return jsonify({"success": False, "message": "Missing data"}), 400

    success, message = track_adsterra_click(
        click_id=click_id,
        telegram_id=telegram_id,
        task_id=task_id,
        ip=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    if success:
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "message": message}), 400