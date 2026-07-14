import sys
import os

# app ফোল্ডারকে ইমপোর্ট করার আগে পাথ ঠিক করুন
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    application.run(host="0.0.0.0", port=port, debug=False)
