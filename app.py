from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/", methods=["POST"])
def alice_webhook():
    data = request.get_json(silent=True) or {}
    session = data.get("session", {})
    request_data = data.get("request", {})

    text = (request_data.get("command") or "").strip().lower()

    if text in ("", "запусти навык", "запусти"):
        response_text = "Привет! Я готов. Что хочешь спросить?"
    elif text in ("привет", "здравствуй", "здравствуйте"):
        response_text = "Привет! Рад тебя слышать."
    else:
        response_text = f"Ты сказал: {text}"

    return jsonify({
        "version": "1.0",
        "session": session,
        "response": {
            "text": response_text,
            "end_session": False
        }
    })

@app.route("/", methods=["GET"])
def health():
    return "Навык Алисы работает"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
