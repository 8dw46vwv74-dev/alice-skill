
code = '''
import os
from collections import defaultdict, deque
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

MEMORY_SIZE = 30
histories = defaultdict(lambda: deque(maxlen=MEMORY_SIZE))

SYSTEM_PROMPT = """
Ты — голосовой помощник пользователя.
Разговаривай естественно, по-человечески, как обычный умный собеседник.
Не говори сухо и шаблонно.
Не повторяй постоянно одни и те же фразы вроде «Конечно», «Хорошо»,
«Я вас понял».
Пользователь может говорить быстро, сбивчиво, обрывать фразы,
исправлять себя и менять тему. Старайся понять смысл из контекста.
Если предыдущая реплика помогает понять текущую — обязательно используй её.
Не выдумывай факты.
Если нужны свежие данные — погода, цены, новости, курсы валют, любые
актуальные факты — используй веб-поиск вместо того, чтобы придумывать ответ.
Если информации недостаточно — нормально скажи, чего именно не хватает,
или задай короткий уточняющий вопрос.
Отвечай на русском языке.
Пользователь предпочитает обычную разговорную речь, без лишней официальности.
Не называй себя «колонкой».
Не объясняй пользователю техническую сторону работы сервера,
если он сам об этом не спрашивает.
Ответы должны быть достаточно подробными, когда вопрос требует объяснения,
но не превращай каждый ответ в длинную лекцию.
Если пользователь просто разговаривает — разговаривай с ним нормально.
Если пользователь говорит «хватит», «стоп» или просит закончить разговор,
ответь коротко и заверши сессию.
"""

# Встроенный инструмент веб-поиска OpenAI — отдельный ключ не нужен,
# используется тот же OPENAI_API_KEY.
TOOLS = [
    {"type": "web_search"}
]


def get_session_id(data):
    session = data.get("session", {})
    return (
        session.get("session_id")
        or (session.get("user") or {}).get("user_id")
        or "default"
    )


def clean_text(text):
    if not text:
        return ""
    text = text.strip()
    return " ".join(text.split())


def run_model(history):
    response = client.responses.create(
        model="gpt-6-luna",
        instructions=SYSTEM_PROMPT,
        input=list(history),
        tools=TOOLS,
        timeout=6
    )
    return response.output_text.strip() if response.output_text else "Я не смог сформировать ответ."


@app.route("/", methods=["POST"])
def alice_webhook():
    data = request.get_json(silent=True) or {}
    session = data.get("session", {})
    request_data = data.get("request", {})
    text = clean_text(
        request_data.get("command", "")
    )
    session_id = get_session_id(data)

    if not text:
        return jsonify({
            "version": "1.0",
            "session": session,
            "response": {
                "text": "Привет! Чем могу помочь?",
                "end_session": False
            }
        })

    stop_words = {
        "хватит",
        "стоп",
        "заканчивай",
        "закончи разговор",
        "заверши разговор"
    }
    if text.lower() in stop_words:
        histories.pop(session_id, None)
        return jsonify({
            "version": "1.0",
            "session": session,
            "response": {
                "text": "Хорошо, заканчиваем.",
                "end_session": True
            }
        })

    reset_words = {
        "забудь разговор",
        "забудь всё",
        "начни сначала",
        "очисти память"
    }
    if text.lower() in reset_words:
        histories.pop(session_id, None)
        return jsonify({
            "version": "1.0",
            "session": session,
            "response": {
                "text": "Хорошо, начинаем с чистого листа.",
                "end_session": False
            }
        })

    history = histories[session_id]
    history.append({
        "role": "user",
        "content": text
    })

    try:
        response_text = run_model(history)
        history.append({
            "role": "assistant",
            "content": response_text
        })
    except Exception as e:
        print(f"OpenAI error: {e}")
        history.pop()
        response_text = (
            "Что-то пошло не так. "
            "Попробуй сказать ещё раз."
        )

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
'''
print(len(code))
