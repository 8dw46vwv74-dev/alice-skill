import os
import time
import threading
from collections import defaultdict, deque

from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

MODEL = "gpt-6-luna"
MEMORY_SIZE = 30

# Алиса ждёт ответ максимум 3 секунды, берём запас
ALICE_WAIT_SECONDS = 2.4
# Сколько живёт незабранный результат
PENDING_TTL = 120

histories = defaultdict(lambda: deque(maxlen=MEMORY_SIZE))
pending = {}  # session_id -> {"done": bool, "text": str, "ts": float}
lock = threading.Lock()

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

SEARCH_TOOLS = [{"type": "web_search"}]

# Поиск подключаем только если запрос похож на «нужны свежие данные»
SEARCH_HINTS = (
    "погод", "температур", "дожд", "сколько стоит", "цена", "цены", "стоимост",
    "курс", "доллар", "евро", "биткоин", "новост", "сегодня", "сейчас",
    "вчера", "завтра", "последн", "найди", "поищи", "загугли", "в интернете",
    "кто выиграл", "счёт", "счет", "расписание", "пробк", "купить",
)

# Фразы, которыми пользователь забирает готовый ответ
FOLLOWUP_PHRASES = (
    "ну что", "ну как", "что там", "нашла", "нашёл", "нашел", "готово",
    "есть ответ", "ответ", "ну",
)

STOP_WORDS = {
    "хватит", "стоп", "заканчивай", "закончи разговор", "заверши разговор",
}
RESET_WORDS = {
    "забудь разговор", "забудь всё", "забудь все", "начни сначала",
    "очисти память",
}


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
    return " ".join(text.strip().split())


def needs_search(text):
    t = text.lower()
    return any(h in t for h in SEARCH_HINTS)


def is_followup(text):
    t = text.lower().strip(" ?!.,")
    return t in FOLLOWUP_PHRASES


def run_model(history, use_search):
    kwargs = dict(
        model=MODEL,
        instructions=SYSTEM_PROMPT,
        input=list(history),
        timeout=40 if use_search else 20,
    )
    if use_search:
        kwargs["tools"] = SEARCH_TOOLS
    response = client.responses.create(**kwargs)
    text = (response.output_text or "").strip()
    return text or "Я не смог сформировать ответ."


def worker(session_id, use_search, user_msg):
    """Работает в фоне: считает ответ и кладёт его в pending и историю."""
    history = histories[session_id]
    try:
        text = run_model(history, use_search)
        with lock:
            history.append({"role": "assistant", "content": text})
            pending[session_id] = {"done": True, "text": text, "ts": time.time()}
    except Exception as e:
        print(f"OpenAI error: {e}")
        with lock:
            # убираем вопрос из истории, чтобы он не застрял без ответа
            if history and history[-1] is user_msg:
                history.pop()
            pending[session_id] = {
                "done": True,
                "text": "Не получилось ответить. Попробуй сказать ещё раз.",
                "ts": time.time(),
            }


def cleanup_pending():
    now = time.time()
    with lock:
        for sid in [s for s, p in pending.items() if now - p["ts"] > PENDING_TTL]:
            pending.pop(sid, None)


def alice_response(session, text, end_session=False):
    return jsonify({
        "version": "1.0",
        "session": session,
        "response": {"text": text, "end_session": end_session},
    })


@app.route("/", methods=["POST"])
def alice_webhook():
    data = request.get_json(silent=True) or {}
    session = data.get("session", {})
    request_data = data.get("request", {})
    text = clean_text(request_data.get("command", ""))
    session_id = get_session_id(data)

    cleanup_pending()

    if not text:
        return alice_response(session, "Привет! Чем могу помочь?")

    low = text.lower()

    if low in STOP_WORDS:
        with lock:
            histories.pop(session_id, None)
            pending.pop(session_id, None)
        return alice_response(session, "Хорошо, заканчиваем.", end_session=True)

    if low in RESET_WORDS:
        with lock:
            histories.pop(session_id, None)
            pending.pop(session_id, None)
        return alice_response(session, "Хорошо, начинаем с чистого листа.")

    # Есть незабранный или ещё считающийся ответ
    with lock:
        p = pending.get(session_id)
        if p and p["done"]:
            pending.pop(session_id, None)
            return alice_response(session, p["text"])
    if p and not p["done"]:
        if is_followup(text):
            return alice_response(session, "Ещё ищу. Спроси через пару секунд.")
        # Пользователь начал новую тему, пока шёл старый запрос — ждём
        return alice_response(
            session, "Подожди немного, я ещё отвечаю на прошлый вопрос."
        )

    # Просто «ну что?» без активного запроса — это обычная реплика
    user_msg = {"role": "user", "content": text}
    with lock:
        histories[session_id].append(user_msg)
        pending[session_id] = {"done": False, "text": "", "ts": time.time()}

    use_search = needs_search(text)
    threading.Thread(
        target=worker, args=(session_id, use_search, user_msg), daemon=True
    ).start()

    # Ждём, вдруг ответ придёт быстро
    deadline = time.time() + ALICE_WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(0.1)
        with lock:
            p = pending.get(session_id)
            if p and p["done"]:
                pending.pop(session_id, None)
                return alice_response(session, p["text"])

    return alice_response(
        session, "Секунду, думаю. Спроси «ну что?» через пару секунд."
    )


@app.route("/", methods=["GET"])
def health():
    return "Навык Алисы работает"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
