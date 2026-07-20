# app/routes/adsterra.py

from flask import Blueprint, request, jsonify
from datetime import datetime
from app import db_mongo, users_col

adsterra_bp = Blueprint('adsterra', __name__, url_prefix='/adsterra')


@adsterra_bp.route('/postback', methods=['GET', 'POST'])
def adsterra_postback():
    """
    Adsterra থেকে Postback রিসিভ করুন
    """
    try:
        # GET বা POST ডেটা নিন
        if request.method == 'GET':
            data = request.args
        else:
            data = request.json or request.form
        
        # প্রয়োজনীয় ডেটা এক্সট্র্যাক্ট করুন
        click_id = data.get('click_id') or data.get('subid') or data.get('subid_short')
        transaction_id = data.get('transaction_id')
        status = data.get('status', 'conversion')
        amount = data.get('amount', 0)
        
        if not click_id:
            return jsonify({"error": "Missing click_id"}), 400
        
        # ক্লিক ডেটা ডাটাবেজে খুঁজুন
        click_record = db_mongo.adsterra_clicks.find_one({
            "click_id": click_id
        })
        
        if not click_record:
            # যদি ক্লিক না পাওয়া যায়, নতুন এন্ট্রি তৈরি করুন
            click_record = {
                "click_id": click_id,
                "telegram_id": None,
                "ip": request.remote_addr,
                "user_agent": request.headers.get('User-Agent'),
                "created_at": datetime.utcnow(),
                "converted": False
            }
            db_mongo.adsterra_clicks.insert_one(click_record)
        
        # কনভার্সন সেভ করুন
        conversion_data = {
            "click_id": click_id,
            "telegram_id": click_record.get("telegram_id"),
            "transaction_id": transaction_id,
            "status": status,
            "amount": amount,
            "converted_at": datetime.utcnow()
        }
        db_mongo.adsterra_conversions.insert_one(conversion_data)
        
        # ক্লিক রেকর্ড আপডেট করুন
        db_mongo.adsterra_clicks.update_one(
            {"click_id": click_id},
            {"$set": {"converted": True, "converted_at": datetime.utcnow()}}
        )
        
        # যদি টেলিগ্রাম আইডি থাকে, তাহলে ইউজারকে রিওয়ার্ড দিন
        if click_record.get("telegram_id"):
            from app.routes.tasks import give_reward_for_adsterra
            give_reward_for_adsterra(click_record["telegram_id"], click_id)
        
        return jsonify({"status": "success", "message": "Conversion tracked"}), 200
        
    except Exception as e:
        print(f"Adsterra Postback Error: {e}")
        return jsonify({"error": str(e)}), 500


@adsterra_bp.route('/click_track', methods=['POST'])
def track_click():
    """
    Adsterra ক্লিক ট্র্যাক করুন (ফ্রন্টএন্ড থেকে কল হবে)
    """
    data = request.json
    click_id = data.get('click_id')
    telegram_id = data.get('telegram_id')
    task_id = data.get('task_id')
    
    if not click_id or not telegram_id:
        return jsonify({"success": False, "message": "Missing data"}), 400
    
    # ক্লিক ট্র্যাক করুন
    from app.utils.adsterra_utils import track_adsterra_click
    track_adsterra_click(
        click_id=click_id,
        telegram_id=telegram_id,
        task_id=task_id,
        ip=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )
    
    return jsonify({"success": True})
