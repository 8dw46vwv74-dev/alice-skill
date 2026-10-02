import os

from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

@app.route("/", methods=["POST"])
def alice_webhook():
    data = request.get_json(silent=True) or {}

    session = data.get("session", {})
    request_data = data.get("request", {})

    text = (request_data.get("command") or "").strip()

    if not text:
        text = "Пользователь запустил навык."

    try:
        response = client.responses.create(
            model="gpt-5.6",
            instructions=(
                "Ты голосовой помощник Алисы. "
                "Отвечай по-русски, естественно и кратко, "
                "потому что твои ответы будут озвучиваться голосом."
            ),
            input=text
        )

        response_text = response.output_text.strip()

    except Exception as e:
        print(f"OpenAI error: {e}")
        response_text = "Извини, сейчас я не могу ответить."

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
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 3000))
    )
