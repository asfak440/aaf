# config.py

import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    MONGO_URI = os.environ.get('MONGO_URI') or 'mongodb://localhost:27017/aaf'
    
    ADSTERRA_POSTBACK_URL = os.environ.get('ADSTERRA_POSTBACK_URL') or 'https://www.pbterra.com/name/your_username/at'
    ADSTERRA_SECRET = os.environ.get('ADSTERRA_SECRET') or 'your-secret'
    
    DEFAULT_TASK_EXPIRY_HOURS = 168
    AUTO_DISABLE_AFTER_SECONDS = 300
    IP_LIMIT_PER_HOUR = 5
    RATE_LIMIT_PER_MINUTE = 3
