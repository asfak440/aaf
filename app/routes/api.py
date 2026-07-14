from flask import Blueprint, jsonify, request
from app import db_mongo, candles_col

api_bp = Blueprint('api', __name__)

@api_bp.route('/api/test', methods=["GET"])
def test_api():
    return jsonify({"status": "ok", "message": "API is working!"})

@api_bp.route('/api/public/popup_config', methods=["GET"])
def get_public_popup_config():
    try:
        config = db_mongo["admin_config"].find_one({"_id": "global"})
        if not config:
            config = {}
        popup_ad = config.get("popup_ad", {})
        return jsonify({
            "popup_ad_enabled": popup_ad.get("enabled", False),
            "popup_ad_title": popup_ad.get("title", "📢 নতুন অফার!"),
            "popup_ad_desc": popup_ad.get("desc", ""),
            "popup_ad_image": popup_ad.get("image", "")
        })
    except Exception as e:
        return jsonify({
            "popup_ad_enabled": False,
            "popup_ad_title": "📢 নতুন অফার!",
            "popup_ad_desc": "",
            "popup_ad_image": ""
        })

@api_bp.route('/api/test_db')
def test_db():
    try:
        count = candles_col.count_documents({})
        return jsonify({
            "status": "success",
            "candles_count": count,
            "message": "MongoDB connected successfully"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@api_bp.route('/api/db-check', methods=["GET"])
def db_check():
    try:
        admin = db_mongo["admin_config"].find_one({})
        return jsonify({
            "connected": True,
            "admin_config_exists": bool(admin),
            "admin_data": admin
        })
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)}), 500
