import requests
import hashlib
from datetime import datetime
from app import users_col, API_ID, API_HASH
from app.utils.helpers import run_async, get_admin_config

# ========== CACHE ==========
memory_cache = {}
CACHE_EXPIRE = 300

def get_cache_key(telegram_id, channel_username):
    data = f"{telegram_id}:{channel_username}"
    return f"member:{hashlib.md5(data.encode()).hexdigest()}"

def get_cached_membership(telegram_id, channel_username):
    cache_key = get_cache_key(telegram_id, channel_username)
    if cache_key in memory_cache:
        data, timestamp = memory_cache[cache_key]
        if (datetime.utcnow() - timestamp).total_seconds() < CACHE_EXPIRE:
            return data
    return None

def set_cached_membership(telegram_id, channel_username, is_member):
    cache_key = get_cache_key(telegram_id, channel_username)
    memory_cache[cache_key] = (is_member, datetime.utcnow())

def clear_all_cache():
    global memory_cache
    memory_cache = {}
    return True

# ========== VERIFY FUNCTIONS ==========
def send_telegram_message(telegram_id, message):
    admin = get_admin_config()
    bot_token = admin.get("bot_token")
    if not bot_token:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {"chat_id": telegram_id, "text": message, "parse_mode": "MARKDOWN"}
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Send message error: {e}")

def verify_with_bot(telegram_id, channel_username):
    admin = get_admin_config()
    bot_token = admin.get("bot_token")
    if not bot_token:
        return None
    if not channel_username.startswith("@"):
        channel_username = "@" + channel_username
    url = f"https://api.telegram.org/bot{bot_token}/getChatMember?chat_id={channel_username}&user_id={telegram_id}"
    try:
        resp = requests.get(url, timeout=10).json()
        if resp.get("ok"):
            status = resp["result"]["status"]
            return status in ("member", "administrator", "creator")
    except Exception as e:
        print(f"Bot error: {e}")
    return None

def verify_with_session(telegram_id, channel_username):
    user = users_col.find_one({"telegram_id": telegram_id})
    if not user or not user.get("session_string"):
        return False
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        async def _check():
            client = TelegramClient(StringSession(user["session_string"]), API_ID, API_HASH)
            await client.connect()
            try:
                entity = await client.get_entity(channel_username)
                me = await client.get_me()
                permissions = await client.get_permissions(entity, me)
                return permissions.is_member
            finally:
                await client.disconnect()
        return run_async(_check())
    except Exception as e:
        print(f"Session error: {e}")
        return False

def verify_user_task_smart(telegram_id, channel_username):
    cached = get_cached_membership(telegram_id, channel_username)
    if cached is not None:
        return cached
    result = verify_with_bot(telegram_id, channel_username)
    if result is not None:
        set_cached_membership(telegram_id, channel_username, result)
        return result
    result = verify_with_session(telegram_id, channel_username)
    set_cached_membership(telegram_id, channel_username, result)
    return result
