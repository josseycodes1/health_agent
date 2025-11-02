# views.py
import logging
import json
import uuid
import os
import re
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone

# Prefer the new google-genai client if available
try:
    from google import genai as genai_client_pkg
    GENAI_CLIENT_AVAILABLE = True
except Exception:
    GENAI_CLIENT_AVAILABLE = False

# For backwards compatibility if older package used
try:
    import google.generativeai as genai_old  # older name, kept for safe detection
    OLD_GENAI_AVAILABLE = True
except Exception:
    OLD_GENAI_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---- Configuration ----
MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "models/gemini-2.5-flash")
SYSTEM_PROMPT_TEXT = """You are Health Buddy, a strictly focused health and wellness virtual assistant.
CRITICAL RULES:
1. Only answer questions about human health, wellness, nutrition, exercise, mental health, and sleep.
2. Politely but firmly refuse any unrelated topics (pets, sports, entertainment, politics, recipes not about nutrition, etc.).
3. Keep refusals concise (1-2 sentences) and friendly.
4. Do not provide medical diagnoses. For concerning symptoms recommend seeking a qualified healthcare professional.
If a user asks something not health-related, respond exactly with: "I specialize only in health and wellness topics. I can help with nutrition, exercise, mental health, sleep, or other health-related questions!" and optionally offer a short health-related pivot question.
"""

# ---- Regex compiled sets (fast, reliable) ----
# Off-topic tokens (word-boundary matched)
OFF_TOPIC_WORDS = [
    'dog','dogs','cat','cats','pet','pets','animal','animals',
    'movie','movies','music','sport','sports','game','games',
    'stock','crypto','bitcoin','politics','weather','recipe',
    'recipes','car','cars','phone','computer','javascript','react',
    'programming','coding','book','books','celebrity','celebrities',
    'vacation','travel','restaurant','hobby','hobbies'
]
OFF_TOPIC_REGEX = re.compile(r'\b(' + r'|'.join(re.escape(w) for w in OFF_TOPIC_WORDS) + r')\b', re.IGNORECASE)

# Health keywords (if present -> allow)
HEALTH_KEYWORDS = [
    'health','wellness','nutrition','diet','exercise','fitness','mental','stress',
    'sleep','medical','doctor','hospital','pain','illness','symptom','treatment',
    'medicine','vitamin','weight','workout','yoga','meditation','therapy','healthy',
    'condition','diagnosis','recovery','cardio','calorie','protein','hydration',
    'depression','anxiety','insomnia','fatigue','blood pressure','cholesterol',
    'diabetes','heart','lung','brain','rehabilitation','prevention'
]
HEALTH_REGEX = re.compile(r'\b(' + r'|'.join(re.escape(w) for w in HEALTH_KEYWORDS) + r')\b', re.IGNORECASE)

# A helper to scan text for off-topic tokens (used for pre and post checks)
def contains_off_topic(text: str) -> bool:
    return bool(OFF_TOPIC_REGEX.search(text or ""))

def contains_health_keyword(text: str) -> bool:
    return bool(HEALTH_REGEX.search(text or ""))

# ---- Helper classes / functions ----

class GeminiHealthChat:
    def __init__(self):
        self.available = False
        self.client = None
        self.conversation_history = {}
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("Gemini API key not found in env (GEMINI_API_KEY or GOOGLE_API_KEY)")
            return

        if GENAI_CLIENT_AVAILABLE:
            try:
                self.client = genai_client_pkg.Client(api_key=self.api_key)
                self.available = True
                logger.info("Gemini Health Chat initialized (google-genai client).")
            except Exception as e:
                logger.error(f"Failed to init google-genai client: {e}")
                self.available = False
        elif OLD_GENAI_AVAILABLE:
            try:
                genai_old.configure(api_key=self.api_key)
                self.client = genai_old
                self.available = True
                logger.info("Gemini Health Chat initialized (legacy google.generativeai).")
            except Exception as e:
                logger.error(f"Failed to init legacy genai: {e}")
                self.available = False
        else:
            logger.warning("No generative AI client available (google-genai or google.generativeai).")

    def get_refusal_reply(self):
        return "I specialize only in health and wellness topics. I can help with nutrition, exercise, mental health, sleep, or other health-related questions!"

    def get_clarifying_prompt(self):
        return "Are you asking about a health or wellness concern? If so, please tell me briefly (e.g., sleep, stress, diet)."

    def get_conversation_history(self, session_id):
        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = [
                {"role": "system", "content": SYSTEM_PROMPT_TEXT},
                {"role": "assistant", "content": "Hello! I'm Health Buddy, your dedicated health and wellness assistant. How can I help you today?"}
            ]
        return self.conversation_history[session_id]

    def reset_history(self, session_id):
        if session_id in self.conversation_history:
            del self.conversation_history[session_id]

    def safe_post_filter(self, assistant_text: str) -> bool:
        """Return True if assistant_text is acceptable; False if it contains off-topic material."""
        if not assistant_text:
            return False
        # If any off-topic token appears in assistant text, reject it
        return not contains_off_topic(assistant_text)

    def is_health_related(self, message: str) -> bool:
        """Decide if the incoming user message is clearly health-related.
        Rules:
          - If it contains off-topic token => NOT health (immediate reject)
          - Else if it contains health keyword => YES
          - Else ambiguous => NO (ask clarify)
        """
        if not message or not message.strip():
            return False

        if contains_off_topic(message):
            return False
        if contains_health_keyword(message):
            return True
        # ambiguous -> treat as not health-related
        return False

    def chat(self, user_message: str, session_id: str = "default"):
        if not self.available:
            return "I'm currently unavailable — please try again later. 💚"

        # PRE-CHECK: immediate off-topic rejection
        if not self.is_health_related(user_message):
            logger.info("Pre-check rejected or ambiguous: %s", user_message)
            # If user message is short/generic ask to clarify; otherwise refuse
            if len(user_message.split()) <= 4:
                return self.get_clarifying_prompt()
            return self.get_refusal_reply()

        # Compose history (system seed + conversation) for model
        history = self.get_conversation_history(session_id).copy()
        history.append({"role": "user", "content": user_message})
        if len(history) > 12:
            history = history[:2] + history[-10:]

        # Call model (modern client preferred)
        try:
            if GENAI_CLIENT_AVAILABLE and isinstance(self.client, genai_client_pkg.Client):
                response = self.client.models.generate_content(
                    model=MODEL_NAME,
                    messages=history,
                    temperature=0.2,            # low temperature to reduce creative off-topic replies
                    max_output_tokens=250
                )
                # Extract text safely
                text = None
                try:
                    # try structured output extraction
                    if hasattr(response, "output"):
                        outputs = response.output
                        if outputs and isinstance(outputs, list):
                            first = outputs[0]
                            content = getattr(first, "content", None)
                            if content and isinstance(content, list):
                                parts = []
                                for c in content:
                                    t = getattr(c, "text", None) or (c.get("text") if isinstance(c, dict) else None)
                                    if t:
                                        parts.append(t)
                                text = " ".join(parts).strip()
                except Exception:
                    logger.exception("Error extracting structured response")

                if not text:
                    text = getattr(response, "text", None) or str(response)

                # POST-CHECK: ensure the assistant's reply doesn't contain off-topic tokens
                if not self.safe_post_filter(text):
                    logger.warning("Post-filter removed an off-topic assistant reply. User message: %s", user_message)
                    # Optionally reset history to avoid repeated drift
                    self.reset_history(session_id)
                    return self.get_refusal_reply()

                # store reply in history
                self.conversation_history[session_id] = history + [{"role": "assistant", "content": text}]
                return text.strip()

            elif OLD_GENAI_AVAILABLE and self.client:
                # legacy flow (best-effort)
                try:
                    model = self.client.GenerativeModel(MODEL_NAME)
                    chat_session = model.start_chat(history=[
                        {"role": "system", "content": SYSTEM_PROMPT_TEXT},
                        {"role": "assistant", "content": "Hello! I'm Health Buddy, your dedicated health and wellness assistant."},
                    ])
                    response = chat_session.send_message(user_message)
                    text = getattr(response, "text", str(response))
                    if not self.safe_post_filter(text):
                        logger.warning("Post-filter removed legacy off-topic reply.")
                        self.reset_history(session_id)
                        return self.get_refusal_reply()
                    self.conversation_history[session_id] = history + [{"role": "assistant", "content": text}]
                    return text.strip()
                except Exception as e:
                    logger.error("Legacy client error: %s", e)
                    return "I specialize in health and wellness topics. How can I help with your health questions today?"

            else:
                return "I’m unable to access the AI service right now."
        except Exception as e:
            logger.exception("Gemini chat failed")
            # Be conservative on any exception: respond with scope refusal/pivot
            return "I specialize in health and wellness topics. How can I help with your health questions today?"

# ---------------- JSON-RPC helper ----------------
class JSONErrorResponse:
    @staticmethod
    def error(request_id, code, message, data=None):
        return JsonResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
                "data": data or {}
            }
        })

    @staticmethod
    def internal_error(request_id, details=None):
        return JSONErrorResponse.error(
            request_id,
            -32603,
            "Internal error",
            {"details": details}
        )

    @staticmethod
    def invalid_params(request_id, details=None):
        return JSONErrorResponse.error(
            request_id,
            -32602,
            "Invalid params",
            {"details": details}
        )

    @staticmethod
    def invalid_request(request_id, details=None):
        return JSONErrorResponse.error(
            request_id,
            -32600,
            "Invalid Request",
            {"details": details}
        )

# ---------------- Views ----------------
@method_decorator(csrf_exempt, name='dispatch')
class A2AHealthView(View):
    def __init__(self):
        super().__init__()
        self.gemini_chat = GeminiHealthChat()

    def post(self, request):
        try:
            try:
                body = json.loads(request.body)
            except json.JSONDecodeError:
                logger.error("Invalid JSON in request body")
                return JSONErrorResponse.invalid_request(None, "Invalid JSON format")

            if body.get("jsonrpc") != "2.0" or "id" not in body:
                logger.error("Invalid JSON-RPC request format")
                return JSONErrorResponse.invalid_request(body.get("id"), "jsonrpc must be '2.0' and id is required")

            request_id = body.get("id")
            method = body.get("method")
            params = body.get("params", {})

            logger.info(f"Processing A2A request: {method}, ID: {request_id}")

            if method == "message/send":
                return self.handle_message_send(request_id, params)
            elif method == "execute":
                return self.handle_execute(request_id, params)
            else:
                logger.error(f"Method not found: {method}")
                return JSONErrorResponse.error(request_id, -32601, "Method not found")

        except Exception as e:
            logger.exception("Unexpected error in A2A endpoint")
            return JSONErrorResponse.internal_error(body.get("id") if 'body' in locals() else None, str(e))

    def handle_message_send(self, request_id, params):
        try:
            message = params.get("message", {})
            configuration = params.get("configuration", {})

            context_id = message.get("taskId") or str(uuid.uuid4())
            task_id = message.get("messageId") or str(uuid.uuid4())

            user_message = ""
            for part in message.get("parts", []):
                if part.get("kind") == "text":
                    user_message = part.get("text", "").strip()
                    break

            session_id = context_id

            if not user_message:
                response_text = "Hello! I'm Health Buddy, your dedicated health and wellness assistant! 😊 I'm here to help with nutrition, exercise, mental health, sleep, and all health-related questions. How can I support your wellness journey today?"
            elif user_message.lower() in ['hi', 'hello', 'how are you', 'hey', 'whats up', "what's up"]:
                response_text = "Hello! I'm Health Buddy, your dedicated health and wellness assistant! 😊 I'm here to help with nutrition, exercise, mental health, sleep, and all health-related questions. How can I support your wellness journey today?"
            else:
                response_text = self.gemini_chat.chat(user_message, session_id)

            logger.info(f"Conversational response for: {user_message}")

            response = self.build_success_response(request_id, response_text, context_id, task_id)
            return JsonResponse(response)

        except Exception as e:
            logger.exception("Error in handle_message_send")
            return JSONErrorResponse.internal_error(request_id, str(e))

    def handle_execute(self, request_id, params):
        try:
            messages = params.get("messages", [])
            context_id = params.get("contextId") or str(uuid.uuid4())
            task_id = params.get("taskId") or str(uuid.uuid4())

            user_message = ""
            if messages:
                for msg in messages:
                    for part in msg.get("parts", []):
                        if part.get("kind") == "text":
                            user_message = part.get("text", "").strip()
                            break
                    if user_message:
                        break

            session_id = context_id

            if not user_message:
                response_text = "Hello! I'm Health Buddy, your friendly health assistant! 😊 How can I help with your health and wellness today?"
            elif user_message.lower() in ['hi', 'hello', 'how are you', 'hey', 'whats up', "what's up"]:
                response_text = "Hello! I'm Health Buddy, your friendly health assistant! 😊 How can I help with your health and wellness today?"
            else:
                response_text = self.gemini_chat.chat(user_message, session_id)

            logger.info(f"Execute conversation - Context: {context_id}")

            response = self.build_success_response(request_id, response_text, context_id, task_id)
            return JsonResponse(response)

        except Exception as e:
            logger.exception("Error in handle_execute")
            return JSONErrorResponse.internal_error(request_id, str(e))

    def build_success_response(self, request_id, response_text, context_id, task_id):
        from datetime import datetime
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "id": task_id,
                "contextId": context_id,
                "status": {
                    "state": "completed",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "message": {
                        "messageId": str(uuid.uuid4()),
                        "role": "agent",
                        "parts": [
                            {
                                "kind": "text",
                                "text": response_text
                            }
                        ],
                        "kind": "message",
                        "taskId": task_id
                    }
                },
                "artifacts": [
                    {
                        "artifactId": str(uuid.uuid4()),
                        "name": "health_response",
                        "parts": [
                            {
                                "kind": "text",
                                "text": response_text
                            }
                        ]
                    }
                ],
                "history": [
                    {
                        "messageId": str(uuid.uuid4()),
                        "role": "agent",
                        "parts": [
                            {
                                "kind": "text",
                                "text": response_text
                            }
                        ],
                        "kind": "message",
                        "taskId": task_id
                    }
                ],
                "kind": "task"
            }
        }

class HealthCheckView(View):
    def __init__(self):
        super().__init__()
        self.gemini_chat = GeminiHealthChat()

    def get(self, request):
        return JsonResponse({
            "status": "healthy",
            "service": "health_conversation_agent",
            "timestamp": timezone.now().isoformat(),
            "gemini_available": self.gemini_chat.available
        })
