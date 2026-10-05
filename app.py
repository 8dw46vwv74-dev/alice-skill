import os
from collections import defaultdict, deque
from flask import Flask, request, jsonify
from openai import OpenAI
app = Flask(__name__)
# Ключ берём только из переменной Render.
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)
# Память диалогов.
# Для каждой сессии Алисы храним последние 30 сообщений.
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
def get_session_id(data):
    session = data.get("session", {})
    return (
        session.get("session_id")
        or session.get("user_id")
        or "default"
    )
def clean_text(text):
    if not text:
        return ""
    text = text.strip()
    # Алиса иногда может передавать лишние пробелы.
    return " ".join(text.split())
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
        text = "Пользователь запустил навык."
    # Команды завершения.
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
    # Команда очистки текущей памяти.
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
    # Добавляем сообщение пользователя в историю.
    history = histories[session_id]
    history.append({
        "role": "user",
        "content": text
    })
    try:
        # Передаём модели системные инструкции + историю разговора.
        response = client.responses.create(
            model="gpt-6-luna",
            instructions=SYSTEM_PROMPT,
            input=list(history)
        )
        response_text = (
            response.output_text.strip()
            if response.output_text
            else "Я не смог сформировать ответ."
        )
        # Сохраняем ответ в память.
        history.append({
            "role": "assistant",
            "content": response_text
        })
    except Exception as e:
        print(f"OpenAI error: {e}")
        # Если произошла ошибка, не ломаем навык.
        # Пользователю отдаём нормальный ответ.
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
