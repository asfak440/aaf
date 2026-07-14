import secrets
import string
import time
import random
from datetime import datetime
from app import admin_config_col, users_col, task_claims_col, candles_col

def run_async(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

def normalize_phone(phone):
    if not phone:
        return None
    phone = phone.strip().replace(" ", "")
    if phone.startswith("+880"):
        return phone
    elif phone.startswith("880"):
        return "+" + phone
    elif phone.startswith("0"):
        return "+880" + phone[1:]
    elif phone.isdigit() and len(phone) == 10:
        return "+880" + phone
    else:
        return None

def get_admin_config():
    doc = admin_config_col.find_one({"_id": "global"})
    if not doc:
        doc = {
            "_id": "global",
            "trading_fee": 0.5,
            "bonus_target": 5,
            "server_income": 0,
            "server_trading": 0,
            "total_users": users_col.count_documents({}),
            "admin_pin": "Abdullah6790",
            "wallet": {"nagad": "01---------", "bkash": ""},
            "trading_ad_text": "Welcome to Trading",
            "task_banner_ad": "",
            "task_popup_ad": "",
            "banner_image": "",
            "popup_ad": {"enabled": False, "image": "", "title": "", "desc": ""},
            "live_price": 1.0,
            "channel_url": "",
            "bot_token": "",
            "channel_id": "",
            "min_trades": 5,
            "ip_limit": "off",
            "extra_users": 0,
            "banner_ad_code": "",
            "referral_bonus": 0,
            "trade_impact_factor": 0.0001,
            "price_volatility": 0.0005,
            "task_rules": {"device_check": True, "ip_check": False, "account_check": True},
            "ip_limit_per_hour": 5,
            "default_task_expiry_hours": 168
        }
        admin_config_col.insert_one(doc)
        return doc
    updates = {}
    if "channel_id" not in doc: updates["channel_id"] = ""
    if "banner_ad_code" not in doc: updates["banner_ad_code"] = ""
    if "referral_bonus" not in doc: updates["referral_bonus"] = 0
    if "trade_impact_factor" not in doc: updates["trade_impact_factor"] = 0.0001
    if "price_volatility" not in doc: updates["price_volatility"] = 0.0005
    if "task_rules" not in doc: updates["task_rules"] = {"device_check": True, "ip_check": False, "account_check": True}
    if "ip_limit_per_hour" not in doc: updates["ip_limit_per_hour"] = 5
    if "default_task_expiry_hours" not in doc: updates["default_task_expiry_hours"] = 168
    if "task_rules" in doc and "price_volatility" in doc["task_rules"]:
        updates["price_volatility"] = doc["task_rules"].pop("price_volatility")
        admin_config_col.update_one({"_id": "global"}, {"$set": {"task_rules": doc["task_rules"]}})
    if updates:
        admin_config_col.update_one({"_id": "global"}, {"$set": updates})
        doc.update(updates)
    return doc

def update_total_users():
    total = users_col.count_documents({})
    admin_config_col.update_one({"_id": "global"}, {"$set": {"total_users": total}})

def generate_task_serial():
    date_part = datetime.utcnow().strftime("%Y%m%d")
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"TASK-{date_part}-{random_part}"

def remove_old_tasks_by_amount(telegram_id, amount):
    tasks_to_remove = int(amount / 10)
    if tasks_to_remove <= 0:
        return 0
    all_tasks = list(task_claims_col.find(
        {"telegram_id": telegram_id, "status": "approved"}
    ).sort("created_at", 1))
    if len(all_tasks) <= tasks_to_remove:
        tasks_to_remove = len(all_tasks) - 1
    deleted_count = 0
    for task in all_tasks[:tasks_to_remove]:
        task_claims_col.delete_one({"_id": task["_id"]})
        deleted_count += 1
    return deleted_count

def init_candles_collection():
    try:
        if candles_col.count_documents({}) == 0:
            base_time = int(time.time()) - (60 * 60)
            start_price = 1.0000
            initial_candles = []
            for i in range(60):
                open_p = start_price
                movement = random.uniform(-0.0015, 0.0015)
                if random.random() < 0.05:
                    movement = random.uniform(-0.003, 0.003)
                close_p = start_price + movement
                open_p = max(0.9000, open_p)
                close_p = max(0.9000, close_p)
                is_up = close_p >= open_p
                if is_up:
                    high_p = close_p + random.uniform(0.0001, 0.0008)
                    low_p = open_p - random.uniform(0.0001, 0.0006)
                else:
                    high_p = open_p + random.uniform(0.0001, 0.0006)
                    low_p = close_p - random.uniform(0.0001, 0.0008)
                low_p = max(0.9000, low_p)
                high_p = max(0.9000, high_p)
                initial_candles.append({
                    "time": int(base_time + (i * 60)),
                    "open": float(open_p),
                    "high": float(high_p),
                    "low": float(low_p),
                    "close": float(close_p)
                })
                start_price = close_p
            candles_col.insert_many(initial_candles)
            print("✅ ৬০টি ক্যান্ডেল যোগ করা হয়েছে!")
    except Exception as e:
        print(f"❌ ক্যান্ডেল ইনিশিয়ালাইজ করতে ব্যর্থ: {e}")
