
code = '''
import os
import requests
from collections import defaultdict, deque
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")

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
актуальные факты — используй инструмент поиска вместо того, чтобы
придумывать ответ.
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

TOOLS = [
    {
        "type": "function",
        "name": "web_search",
        "description": (
            "Поиск в интернете свежей информации: погода, цены, курсы валют, "
            "новости и любые актуальные факты, которые модель не может знать "
            "заранее."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос на русском или английском языке."
                }
            },
            "required": ["query"]
        }
    }
]


def web_search(query):
    """Делает реальный запрос к поисковику через SerpAPI и возвращает
    краткую выжимку результатов."""
    if not SERPAPI_KEY:
        return "Поиск недоступен: не настроен ключ поиска."
    try:
        resp = requests.get(
            "https://serpapi.com/search",
            params={
                "q": query,
                "hl": "ru",
                "gl": "ru",
                "api_key": SERPAPI_KEY
            },
            timeout=5
        )
        data = resp.json()
        pieces = []
        answer_box = data.get("answer_box")
        if answer_box:
            snippet = answer_box.get("answer") or answer_box.get("snippet")
            if snippet:
                pieces.append(snippet)
        for result in data.get("organic_results", [])[:3]:
            snippet = result.get("snippet")
            if snippet:
                pieces.append(snippet)
        if not pieces:
            return "Ничего конкретного не нашлось."
        return " / ".join(pieces[:4])
    except Exception as e:
        print(f"Search error: {e}")
        return "Поиск сейчас недоступен."


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
    """Запускает модель, при необходимости выполняет вызовы инструментов
    и возвращает финальный текстовый ответ."""
    input_items = list(history)

    response = client.responses.create(
        model="gpt-6-luna",
        instructions=SYSTEM_PROMPT,
        input=input_items,
        tools=TOOLS,
        timeout=4
    )

    # Обрабатываем возможные вызовы инструментов (может быть несколько раундов).
    for _ in range(3):
        tool_calls = [
            item for item in response.output
            if getattr(item, "type", None) == "function_call"
        ]
        if not tool_calls:
            break

        input_items += response.output
        for call in tool_calls:
            if call.name == "web_search":
                import json
                args = json.loads(call.arguments or "{}")
                result = web_search(args.get("query", ""))
            else:
                result = "Инструмент не найден."
            input_items.append({
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": result
            })

        response = client.responses.create(
            model="gpt-6-luna",
            instructions=SYSTEM_PROMPT,
            input=input_items,
            tools=TOOLS,
            timeout=4
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

