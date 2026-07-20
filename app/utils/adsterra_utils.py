# app/utils/adsterra_utils.py

import requests
import hashlib
from datetime import datetime, timedelta
from app import db_mongo

def verify_adsterra_click(click_id, telegram_id):
    """Adsterra ক্লিক ভেরিফাই করুন"""
    click_record = db_mongo.adsterra_clicks.find_one({
        "click_id": click_id,
        "telegram_id": telegram_id
    })
    
    if not click_record:
        return False, "ক্লিক রেকর্ড পাওয়া যায়নি"
    
    if datetime.utcnow() - click_record["created_at"] > timedelta(minutes=5):
        return False, "ক্লিকের মেয়াদ শেষ হয়েছে"
    
    if click_record.get("used", False):
        return False, "এই ক্লিক ইতিমধ্যে ব্যবহার করা হয়েছে"
    
    db_mongo.adsterra_clicks.update_one(
        {"click_id": click_id},
        {"$set": {"used": True, "verified_at": datetime.utcnow()}}
    )
    
    return True, "ক্লিক ভেরিফাইড"


def send_conversion_to_adsterra(click_id, amount=0):
    """Adsterra-তে কনভার্সন রিপোর্ট করুন"""
    try:
        postback_url = f"https://www.pbterra.com/name/your_username/at?subid_short={click_id}"
        if amount > 0:
            postback_url += f"&amount={amount}"
        
        response = requests.get(postback_url, timeout=5)
        return response.status_code == 200
    except:
        return False


def track_adsterra_click(click_id, telegram_id, task_id, ip, user_agent):
    """Adsterra ক্লিক ট্র্যাক করুন"""
    db_mongo.adsterra_clicks.insert_one({
        "click_id": click_id,
        "telegram_id": telegram_id,
        "task_id": task_id,
        "ip": ip,
        "user_agent": user_agent,
        "created_at": datetime.utcnow(),
        "used": False
    })
    return True


def generate_click_id(telegram_id, task_id):
    """ইউনিক ক্লিক আইডি তৈরি করুন"""
    raw = f"{telegram_id}_{task_id}_{datetime.utcnow().timestamp()}"
    return hashlib.md5(raw.encode()).hexdigest()
