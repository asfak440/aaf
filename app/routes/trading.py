from flask import Blueprint, render_template, request, jsonify, session
from datetime import datetime
from bson import ObjectId

from app import users_col, admin_config_col, trades_col, db_mongo
from app.utils.decorators import login_required
from app.utils.helpers import get_admin_config

trading_bp = Blueprint('trading', __name__, url_prefix='/trading')

# ================= PAGE ROUTES =================
@trading_bp.route('/')
@login_required
def trading():
    return render_template("trading.html")

# ================= TRADING APIs =================
@trading_bp.route('/api/market/price')
def market_price():
    try:
        admin = get_admin_config()
        live_price = float(admin.get("live_price", 1.0))
        trade_fee = float(admin.get("trading_fee", 0.5))
        price_volatility = float(admin.get("price_volatility", 0.0005))
        trade_impact_factor = float(admin.get("trade_impact_factor", 0.0001))
        if live_price < 0.90:
            live_price = 0.90
        return jsonify({
            "live_price": live_price,
            "trade_fee": trade_fee,
            "price_volatility": price_volatility,
            "trade_impact_factor": trade_impact_factor,
            "status": "success"
        })
    except Exception as e:
        return jsonify({
            "live_price": 1.0, 
            "trade_fee": 0.5,
            "price_volatility": 0.0005,
            "trade_impact_factor": 0.0001,
            "status": "error"
        })

@trading_bp.route('/api/market/live-candle')
def live_candle():
    now = int(datetime.utcnow().timestamp())
    try:
        last_candle = db_mongo["candles"].find_one({}, sort=[("time", -1)])
        if last_candle:
            return jsonify({
                "time": int(last_candle.get("time", 0)),
                "open": float(last_candle.get("open", 1.0)),
                "high": float(last_candle.get("high", 1.0)),
                "low": float(last_candle.get("low", 1.0)),
                "close": float(last_candle.get("close", 1.0))
            })
    except Exception as e:
        print(f"Live candle error: {e}")
    return jsonify({"time": now, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0})

@trading_bp.route('/api/market/update_candle', methods=["POST"])
@login_required
def update_candle():
    try:
        data = request.get_json()
        admin_doc = admin_config_col.find_one({"_id": "global"})
        if admin_doc and admin_doc.get("live_price"):
            price = float(admin_doc.get("live_price"))
        else:
            price = float(data.get('price', 0))
        if not price:
            return jsonify({"status": "error", "message": "Invalid price"}), 400

        now = int(datetime.utcnow().timestamp())
        current_date_utc = datetime.utcnow()

        timeframes = {
            "1": db_mongo['candles'],
            "5": db_mongo['candles_5m'],
            "15": db_mongo['candles_15m'],
            "60": db_mongo['candles_1h'],
            "240": db_mongo['candles_4h'],
            "1440": db_mongo['candles_1d']
        }

        for tf_str, collection in timeframes.items():
            tf_minutes = int(tf_str)
            tf_seconds = tf_minutes * 60
            bucket_time = now - (now % tf_seconds)
            existing = collection.find_one({"time": bucket_time})
            if existing:
                old_high = float(existing.get("high", price))
                old_low = float(existing.get("low", price))
                new_high = max(old_high, price)
                new_low = min(old_low, price)
                collection.update_one(
                    {"time": bucket_time},
                    {
                        "$set": {
                            "high": new_high,
                            "low": new_low,
                            "close": price,
                            "createdAt": current_date_utc
                        }
                    }
                )
            else:
                collection.insert_one({
                    "time": bucket_time,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "createdAt": current_date_utc
                })
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@trading_bp.route('/api/trade/execute', methods=["POST"])
@login_required
def execute_trade():
    data = request.get_json(silent=True) or {}
    uid = session.get("uid")
    if not uid:
        return jsonify({"status": "error", "message": "session_expired"}), 401

    trade_type = str(data.get("action") or data.get("type", "")).lower().strip()
    taka = float(data.get("amount") or data.get("taka", 0) or 0)
    coin = float(data.get("coin", 0) or 0)
    price = float(data.get("current_price") or data.get("price", 0) or 0)

    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    admin = get_admin_config() or {}
    fee_percent = float(admin.get("trading_fee", 0.5) or 0.5)
    impact_factor = float(admin.get("trade_impact_factor", 0.0001))

    if price <= 0:
        return jsonify({"status": "error", "message": "Invalid price"}), 400

    if trade_type == "buy":
        if taka <= 0:
            return jsonify({"status": "error", "message": "Invalid amount"}), 400
        if coin <= 0:
            coin = taka / price
        total_cost = taka + (taka * fee_percent / 100)
        if float(user.get("cash", 0)) < total_cost:
            return jsonify({"status": "error", "message": "Insufficient cash"}), 400
        new_cash = float(user.get("cash", 0)) - total_cost
        new_aaf = float(user.get("aaf", 0)) + coin
        fee_amount = taka * fee_percent / 100
        users_col.update_one(
            {"_id": user["_id"]},
            {"$set": {"cash": new_cash, "aaf": new_aaf}}
        )
        admin_config_col.update_one(
            {"_id": "global"},
            {"$inc": {"server_income": fee_amount}}
        )
        trades_col.insert_one({
            "telegram_id": user.get("telegram_id"),
            "type": "buy",
            "taka": taka,
            "coin": coin,
            "price": price,
            "fee": fee_amount,
            "timestamp": datetime.utcnow()
        })
        current_live_price = float(admin.get("live_price", 1.0))
        price_change = taka * impact_factor
        new_price = current_live_price + price_change
        new_price = max(0.1, new_price)
        admin_config_col.update_one(
            {"_id": "global"},
            {"$set": {"live_price": new_price}}
        )
        return jsonify({"status": "success", "message": f"Bought {coin:.4f} AAF successfully"})

    elif trade_type == "sell":
        if coin <= 0:
            if taka > 0:
                coin = taka / price
            else:
                return jsonify({"status": "error", "message": "Invalid coin amount"}), 400
        if taka <= 0:
            taka = coin * price
        if float(user.get("aaf", 0)) < coin:
            return jsonify({"status": "error", "message": "Insufficient AAF"}), 400
        fee_amount = taka * fee_percent / 100
        total_receive = taka - fee_amount
        new_cash = float(user.get("cash", 0)) + total_receive
        new_aaf = float(user.get("aaf", 0)) - coin
        users_col.update_one(
            {"_id": user["_id"]},
            {"$set": {"cash": new_cash, "aaf": new_aaf}}
        )
        admin_config_col.update_one(
            {"_id": "global"},
            {"$inc": {"server_income": fee_amount}}
        )
        trades_col.insert_one({
            "telegram_id": user.get("telegram_id"),
            "type": "sell",
            "taka": taka,
            "coin": coin,
            "price": price,
            "fee": fee_amount,
            "timestamp": datetime.utcnow()
        })
        current_live_price = float(admin.get("live_price", 1.0))
        price_change = taka * impact_factor
        new_price = current_live_price - price_change
        new_price = max(0.1, new_price)
        admin_config_col.update_one(
            {"_id": "global"},
            {"$set": {"live_price": new_price}}
        )
        return jsonify({"status": "success", "message": f"Sold {coin:.4f} AAF successfully"})

    return jsonify({"status": "error", "message": "Invalid type. Use 'buy' or 'sell'"}), 400

@trading_bp.route('/api/candles', methods=['GET'])
def get_candles():
    try:
        tf = request.args.get('timeframe') or request.args.get('tf') or '1'
        limit = request.args.get('limit', 500, type=int)

        if tf == '5':
            collection_name = 'candles_5m'
        elif tf == '15':
            collection_name = 'candles_15m'
        elif tf == '60':
            collection_name = 'candles_1h'
        elif tf == '240':
            collection_name = 'candles_4h'
        elif tf == '1440':
            collection_name = 'candles_1d'
        else:
            collection_name = 'candles'

        current_col = db_mongo[collection_name]
        candles_cursor = current_col.find({}, {'_id': 0}).sort("time", -1).limit(limit)
        candles = list(candles_cursor)
        candles.reverse()

        for c in candles:
            if c.get("time") and c["time"] > 9999999999:
                c["time"] = int(c["time"] / 1000)

        if not candles:
            base = int(datetime.utcnow().timestamp()) - (int(tf) * 60 * 100)
            for i in range(100):
                price = 1.0 + (i * 0.001)
                candles.append({
                    "time": base + (i * int(tf) * 60),
                    "open": price,
                    "high": price * 1.002,
                    "low": price * 0.998,
                    "close": price * 1.001
                })

        return jsonify({"status": "success", "candles": candles})
    except Exception as e:
        return jsonify({"status": "error", "candles": [], "message": str(e)}), 500
