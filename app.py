import os
from flask import Flask, request, jsonify, render_template
from linebot import LineBotApi
from linebot.models import TextSendMessage
import Login

app = Flask(__name__)
app.secret_key = os.getenv('APPSECRET', '135e933ae3e4b0a3a0d2282804ff62b9')

LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'KhSmwJno9143P5bt4klOIOxcWM6bNEBXDGb2XO+vEP6z9yN4eSI6rp98MH2cM/AYRar2syaGbEzZHimXv5XFjErtIFk3isMgBd5AqecVxinW/S3JTB/vxqWC2BBHE/CbFRXXisJsy6xECx7RCkHoFAdB04t89/1O/w1cDnyilFU=')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/verify_login', methods=['POST'])
def verify_login():
    data = request.get_json()
    line_user_id = data.get('lineUserId')
    student_id = data.get('studentId')
    password = data.get('password')

    success = Login.main(student_id, password)

    if success:
        msg = "教務系統登入成功！您可以繼續查詢成績。"
    else:
        msg = "教務系統登入失敗，請確認帳號密碼後重試。"

    if line_user_id:
        try:
            line_bot_api.push_message(line_user_id, TextSendMessage(text=msg))
        except Exception as e:
            print(f"推播訊息失敗: {e}")

    return jsonify({"success": success, "message": msg})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
