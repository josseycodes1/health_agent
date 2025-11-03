
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

logger = logging.getLogger(__name__)


MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "models/gemini-2.5-flash")
SYSTEM_PROMPT_TEXT = """You are Health Buddy, a strictly focused health and wellness virtual assistant.
CRITICAL RULES:
1. Only answer human health, wellness, nutrition, exercise, mental health, and sleep.
2. Refuse any unrelated topics with the exact message:
"I specialize only in health and wellness topics. I can help with nutrition, exercise, mental health, sleep, or other health-related questions!"
3. Do not provide medical diagnoses; always advise consulting a professional for concerning symptoms.
"""


OFF_TOPIC_WORDS = [
    # Keep only clearly non-health topics
    'movie','movies','music','sport','sports','game','games','gaming',
    'stock','stocks','crypto','bitcoin','ethereum','politics','political',
    'weather','recipe','recipes','cooking','baking',
    'car','cars','vehicle','phone','computer','javascript','react','python',
    'programming','coding','software','book','books','novel',
    'celebrity','celebrities','actor','actress','vacation','travel',
    'restaurant','hobby','hobbies','craft','shopping'
    # Remove animal/pet words since they could be therapy/service animals
]
OFF_TOPIC_REGEX = re.compile(r'\b(' + r'|'.join(re.escape(w) for w in OFF_TOPIC_WORDS) + r')\b', re.IGNORECASE)

HEALTH_KEYWORDS = [
    'health','wellness','nutrition','diet','exercise','fitness','mental','stress',
    'sleep','medical','doctor','hospital','pain','illness','symptom','treatment',
    'medicine','vitamin','weight','workout','yoga','meditation','therapy','healthy',
    'condition','diagnosis','recovery','cardio','calorie','protein','hydration',
    'depression','anxiety','insomnia','fatigue','blood pressure','cholesterol',
    'diabetes','heart','lung','brain','rehabilitation','prevention'
]
HEALTH_REGEX = re.compile(r'\b(' + r'|'.join(re.escape(w) for w in HEALTH_KEYWORDS) + r')\b', re.IGNORECASE)

REFUSAL_TEXT = "I specialize only in health and wellness topics. I can help with nutrition, exercise, mental health, sleep, or other health-related questions!"

def contains_off_topic(text: str) -> bool:
    return bool(OFF_TOPIC_REGEX.search(text or ""))

def contains_health_keyword(text: str) -> bool:
    return bool(HEALTH_REGEX.search(text or ""))


GUARDRAILS_AVAILABLE = False
GUARD = None
try:
   
    from guardrails import Guard
    GUARDRAILS_AVAILABLE = True
    logger.info("Guardrails available and will be used for policy enforcement.")
except Exception as e:
    logger.warning("Guardrails not available: %s", e)
    GUARDRAILS_AVAILABLE = False

GENAI_CLIENT_AVAILABLE = False
try:
    from google import genai as genai_client_pkg
    GENAI_CLIENT_AVAILABLE = True
except Exception:
    GENAI_CLIENT_AVAILABLE = False

OLD_GENAI_AVAILABLE = False
try:
    import google.generativeai as genai_old
    OLD_GENAI_AVAILABLE = True
except Exception:
    OLD_GENAI_AVAILABLE = False


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
                logger.info("google-genai client initialized.")
            except Exception as e:
                logger.error("Failed to initialize google-genai client: %s", e)
                self.available = False
        elif OLD_GENAI_AVAILABLE:
            try:
                genai_old.configure(api_key=self.api_key)
                self.client = genai_old
                self.available = True
                logger.info("Legacy google.generativeai client initialized.")
            except Exception as e:
                logger.error("Failed to init legacy genai: %s", e)
                self.available = False
        else:
            logger.warning("No generative AI library available.")

   
        if GUARDRAILS_AVAILABLE:
            try:
            
                try:
                 
                    GUARD = Guard.from_rail("health_rails.yaml")
                except Exception:
                    GUARD = Guard("health_rails.yaml")
             
                self.guard = GUARD
                logger.info("Loaded Guardrails spec health_rails.yaml")
            except Exception as e:
                self.guard = None
                logger.warning("Failed to load Guardrails spec: %s", e)
        else:
            self.guard = None

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

 
    def fallback_chat(self, user_message: str, session_id: str = "default"):
        logger.info(f"Processing message: '{user_message}'")
        
        # Debug: Check off-topic detection
        is_off_topic = contains_off_topic(user_message)
        logger.info(f"Off-topic check: {is_off_topic}")
        
        # Only block clearly off-topic messages
        if is_off_topic:
            logger.info("Blocking as off-topic")
            return REFUSAL_TEXT
        
        # Build history and let Gemini handle the conversation
        history = self.get_conversation_history(session_id).copy()
        history.append({"role":"user","content":user_message})
        
        logger.info(f"History length: {len(history)}")
        
        if not self.available:
            logger.warning("Gemini not available")
            return "I'm currently unavailable — please try again later."

        try:
            if GENAI_CLIENT_AVAILABLE and isinstance(self.client, genai_client_pkg.Client):
                logger.info("Using new genai client")
                response = self.client.models.generate_content(
                    model=MODEL_NAME,
                    messages=history,
                    temperature=0.2,
                    max_output_tokens=250
                )
            
                text = None
                if hasattr(response, "output"):
                    try:
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
                        logger.exception("Failed structured parse")
                if not text:
                    text = getattr(response, "text", None) or str(response)

                logger.info(f"Gemini raw response: '{text}'")
                
                # Only block if Gemini goes off-topic in response
                if contains_off_topic(text):
                    logger.info("Blocking Gemini response as off-topic")
                    self.reset_history(session_id)
                    return REFUSAL_TEXT

                self.conversation_history[session_id] = history + [{"role":"assistant","content":text}]
                return text.strip()

            elif OLD_GENAI_AVAILABLE and self.client:
                logger.info("Using legacy genai client")
                try:
                    model = self.client.GenerativeModel(MODEL_NAME)
                    chat_session = model.start_chat(history=[
                        {"role":"system","content":SYSTEM_PROMPT_TEXT},
                        {"role":"assistant","content":"Hello! I'm Health Buddy, your dedicated health and wellness assistant."},
                    ])
                    response = chat_session.send_message(user_message)
                    text = getattr(response,"text",str(response))
                    logger.info(f"Legacy Gemini response: '{text}'")
                    
                    if contains_off_topic(text):
                        self.reset_history(session_id)
                        return REFUSAL_TEXT
                    self.conversation_history[session_id] = history + [{"role":"assistant","content":text}]
                    return text.strip()
                except Exception as e:
                    logger.error("Legacy client error: %s", e)
                    return REFUSAL_TEXT
            else:
                logger.warning("No genai client available")
                return "I'm unable to access the AI service right now."
        except Exception as e:
            logger.exception("Model call failed")
            return REFUSAL_TEXT

   
    def guardrails_chat(self, user_message: str, session_id: str = "default"):
       
        if not self.guard:
            return self.fallback_chat(user_message, session_id)

       
        try:
            
            try:
                out = self.guard.run({"user_message": user_message})
            except TypeError:
                
                out = self.guard.execute({"user_message": user_message})

            
            assistant_reply = None
            if isinstance(out, dict):
                assistant_reply = out.get("assistant_reply") or out.get("output", {}).get("assistant_reply")
         
            if not assistant_reply:
               
                assistant_reply = str(out)

            
            if contains_off_topic(assistant_reply):
                return REFUSAL_TEXT
            return assistant_reply
        except Exception as e:
            logger.exception("Guardrails execution failed, falling back: %s", e)
            
            return self.fallback_chat(user_message, session_id)

    def chat(self, user_message: str, session_id: str = "default"):
       
        if self.guard:
            return self.guardrails_chat(user_message, session_id)
        
        return self.fallback_chat(user_message, session_id)



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
               
                return self.build_method_error_response(None, "Invalid JSON format")

            
            if not body:
                return self.build_method_error_response(None, "Unknown method. Use 'message/send' or 'execute'.")

            request_id = body.get("id", "")
            method = body.get("method")
            
          
            if not method:
                return self.build_method_error_response(request_id, "Unknown method. Use 'message/send' or 'execute'.")

            params = body.get("params", {})

            logger.info(f"Processing A2A request: {method}, ID: {request_id}")

            if method == "message/send":
                return self.handle_message_send(request_id, params)
            elif method == "execute":
                return self.handle_execute(request_id, params)
            else:
                logger.error(f"Method not found: {method}")
                return self.build_method_error_response(request_id, f"Unknown method. Use 'message/send' or 'execute'.")

        except Exception as e:
            logger.exception("Unexpected error in A2A endpoint")
            return self.build_method_error_response(body.get("id") if 'body' in locals() else None, "Internal server error")

    def build_method_error_response(self, request_id, message):
        """Build error response matching the expected format"""
        from datetime import datetime
        error_task_id = str(uuid.uuid4())
        error_context_id = str(uuid.uuid4())
        error_message_id = str(uuid.uuid4())
        artifact_id = str(uuid.uuid4())
        
        return JsonResponse({
            "jsonrpc": "2.0",
            "id": request_id or "",
            "result": {
                "id": error_task_id,
                "contextId": error_context_id,
                "status": {
                    "state": "failed",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "message": {
                        "kind": "message",
                        "role": "agent", 
                        "parts": [
                            {
                                "kind": "text",
                                "text": message
                            }
                        ],
                        "messageId": error_message_id,
                        "taskId": None,
                        "metadata": None
                    }
                },
                "artifacts": [
                    {
                        "artifactId": artifact_id,
                        "name": "assistantResponse",
                        "parts": [
                            {
                                "kind": "text", 
                                "text": message
                            }
                        ]
                    }
                ],
                "history": [],
                "kind": "task"
            }
        })

    def handle_message_send(self, request_id, params):
        try:
            message = params.get("message", {})
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
        message_id = str(uuid.uuid4())
        artifact_id = str(uuid.uuid4())
        
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
                        "kind": "message",
                        "role": "agent",
                        "parts": [
                            {
                                "kind": "text",
                                "text": response_text
                            }
                        ],
                        "messageId": message_id,
                        "taskId": task_id,
                        "metadata": None
                    }
                },
                "artifacts": [
                    {
                        "artifactId": artifact_id,
                        "name": "assistantResponse",
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
                        "kind": "message",
                        "role": "agent",
                        "parts": [
                            {
                                "kind": "text",
                                "text": response_text
                            }
                        ],
                        "messageId": message_id,
                        "taskId": task_id,
                        "metadata": None
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
        # Test if Gemini can actually respond
        test_response = "Not tested"
        if self.gemini_chat.available:
            try:
                test_response = self.gemini_chat.chat("test health question")
            except Exception as e:
                test_response = f"Error: {str(e)}"
        
        return JsonResponse({
            "status": "healthy",
            "service": "health_conversation_agent", 
            "timestamp": timezone.now().isoformat(),
            "gemini_available": self.gemini_chat.available,
            "test_response": test_response
        })