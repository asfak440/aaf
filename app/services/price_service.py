import time
import random
import threading
from datetime import datetime
from app import db_mongo, admin_config_col

# গ্লোবাল ভেরিয়েবল (app.__init__.py থেকে ইমপোর্ট করা)
current_price = 1.0

def update_price_loop():
    global current_price
    print("🚀 মঙ্গোডিবি মাল্টি-টাইমফ্রেম অটো-ক্যান্ডেল ইঞ্জিন ও লাইভ প্রাইস লুপ চালু হয়েছে...")

    # প্রতিটি টাইমফ্রেমের জন্য আলাদা ট্র্যাকার
    last_saved_times = {
        "1m": -1,
        "5m": -1,
        "15m": -1,
        "1h": -1,
        "4h": -1,
        "1d": -1
    }

    # 🎯 আপনার মঙ্গোডিবি কালেকশন নামের সাথে মিল রেখে নিখুঁত ম্যাপিং [কালেকশন অবজেক্ট, কত সেকেন্ডের বকেট]
    tf_configs = {
        "1m": (db_mongo['candles'], 60),          # 1 Minute
        "5m": (db_mongo['candles_5m'], 300),      # 5 Minutes
        "15m": (db_mongo['candles_15m'], 900),    # 15 Minutes
        "1h": (db_mongo['candles_1h'], 3600),     # 1 Hour
        "4h": (db_mongo['candles_4h'], 14400),    # 4 Hours (৪ ঘণ্টা = ১৪৪০০ সেকেন্ড)
        "1d": (db_mongo['candles_1d'], 86400)     # 1 Day
    }

    while True:
        try:
            now_ts = int(time.time())
            current_date_utc = datetime.utcnow() # TTL ইনডেক্সের জন্য বর্তমান UTC সময়

            # ১. এডমিন কনফিগ থেকে volatility এবং লাইভ প্রাইস সিঙ্ক করা
            from app.utils.helpers import get_admin_config
            admin = get_admin_config() or {}
            volatility = admin.get("task_rules", {}).get("price_volatility", 0.0005) if isinstance(admin.get("task_rules"), dict) else admin.get("price_volatility", 0.0005)

            db_price = float(admin.get("live_price", current_price))

            # 📈📉 র্যান্ডম আপ-ডাউন মুভমেন্ট
            change = random.uniform(-volatility, volatility)
            current_price = db_price + change

            # 🛡️ ৯০ পয়সার সেফটি ফ্লোর এবং ২.৫ টাকার সিলিং লক
            current_price = max(0.9000, min(2.5000, current_price))

            # ২. 🔄 লুপ চালিয়ে আপনার ৬টি কালেকশনে আলাদা আলাদা ভাবে ক্যান্ডেল প্রসেস ও সেভ করা
            for tf_key, (col, seconds) in tf_configs.items():
                # বর্তমান টাইমফ্রেম অনুযায়ী ক্যান্ডেলের শুরুর নিখুঁত সময় (Bucket Timestamp)
                bucket_timestamp = now_ts - (now_ts % seconds)

                if bucket_timestamp != last_saved_times[tf_key]:
                    # নতুন টাইমফ্রেম ব্লক শুরু হয়েছে! একদম ফ্রেশ ক্যান্ডেল ইনসার্ট হবে
                    new_candle = {
                        "time": int(bucket_timestamp),
                        "open": float(db_price),
                        "high": float(max(db_price, current_price)),
                        "low": float(min(db_price, current_price)),
                        "close": float(current_price),
                        "createdAt": current_date_utc # 🔥 এটি আপনার ২ মাসের অটো-ডিলিট ইনডেক্সকে সচল রাখবে
                    }
                    col.insert_one(new_candle)
                    print(f"⏰ [{tf_key} ইঞ্জিন]: নতুন ক্যান্ডেল তৈরি হয়েছে! টাইম: {bucket_timestamp} | দাম: {current_price:.6f}")

                    last_saved_times[tf_key] = bucket_timestamp
                else:
                    # 🔄 একই টাইমফ্রেম ব্লকের ভেতরে রিয়েল-টাইমে হাই, লো, ক্লোজ এবং টাইমস্ট্যাম্প আপডেট হবে
                    col.update_one(
                        {"time": int(bucket_timestamp)},
                        {
                            "$max": {"high": float(current_price)},
                            "$min": {"low": float(current_price)},
                            "$set": {
                                "close": float(current_price),
                                "createdAt": current_date_utc # মেয়াদের সিল রিফ্রেশ
                            }
                        },
                        upsert=True
                    )

            # ৩. MongoDB এডমিন কনফিগে গ্লোবাল লাইভ প্রাইস রিয়েল-টাইম আপডেট
            admin_config_col.update_one(
                {"_id": "global"}, 
                {"$set": {"live_price": float(current_price), "last_updated": int(time.time())}}
            )

            time.sleep(1) # প্রতি ১ সেকেন্ডে লুপ চলবে

        except Exception as e:
            print(f"Price update error in multi-engine: {e}")
            time.sleep(5)


def start_price_thread():
    """ব্যাকগ্রাউন্ডে প্রাইস আপডেট থ্রেড শুরু করে"""
    print("🔔 [System]: Starting Background Multi-Timeframe Price Thread...")
    thread = threading.Thread(target=update_price_loop, daemon=True)
    thread.start()
    return thread
