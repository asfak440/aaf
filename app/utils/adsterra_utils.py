import requests
import hashlib
from datetime import datetime, timedelta
from app import adsterra_clicks_col  # ← ঠিক করা


def verify_adsterra_click(click_id, telegram_id):
    """Adsterra ক্লিক ভেরিফাই করুন"""
    click_record = adsterra_clicks_col.find_one({  # ← ঠিক করা
        "click_id": click_id,
        "telegram_id": telegram_id
    })

    if not click_record:
        return False, "ক্লিক রেকর্ড পাওয়া যায়নি"

    if datetime.utcnow() - click_record["created_at"] > timedelta(minutes=5):
        return False, "ক্লিকের মেয়াদ শেষ হয়েছে"

    if click_record.get("used", False):
        return False, "এই ক্লিক ইতিমধ্যে ব্যবহার করা হয়েছে"

    adsterra_clicks_col.update_one(  # ← ঠিক করা
        {"click_id": click_id},
        {"$set": {"used": True, "verified_at": datetime.utcnow()}}
    )

    return True, "ক্লিক ভেরিফাইড"


def send_conversion_to_adsterra(click_id, amount=0, username="your_username"):
    """Adsterra-তে কনভার্সন রিপোর্ট করুন"""
    try:
        # ✅ আপনার username দিন অথবা প্যারামিটার হিসেবে দিন
        postback_url = f"https://www.pbterra.com/name/{username}/at?subid_short={click_id}"
        if amount > 0:
            postback_url += f"&amount={amount}"

        response = requests.get(postback_url, timeout=5)
        return response.status_code == 200
    except:
        return False


def track_adsterra_click(click_id, telegram_id, task_id, ip, user_agent):
    """Adsterra ক্লিক ট্র্যাক করুন"""
    adsterra_clicks_col.insert_one({  # ← ঠিক করা
        "click_id": click_id,
        "telegram_id": telegram_id,
        "task_id": task_id,
        "ip": ip,
        "user_agent": user_agent,
        "created_at": datetime.utcnow(),
        "used": False,
        "converted": False  # ← যোগ করুন (দুটোই রাখতে পারেন)
    })
    return True


def generate_click_id(telegram_id, task_id):
    """ইউনিক ক্লিক আইডি তৈরি করুন"""
    raw = f"{telegram_id}_{task_id}_{datetime.utcnow().timestamp()}"
    return hashlib.md5(raw.encode()).hexdigest()