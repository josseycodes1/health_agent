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

logger = logging.getLogger(__name__)

# Config
MODEL_NAME = "gemini-2.0-flash"
SYSTEM_PROMPT_TEXT = """You are Health Buddy, a strictly focused health and wellness virtual assistant.
CRITICAL RULES:
1. Only answer human health, wellness, nutrition, exercise, mental health, and sleep.
2. Refuse any unrelated topics with the exact message:
"I specialize only in health and wellness topics. I can help with nutrition, exercise, mental health, sleep, or other health-related questions!"
3. Do not provide medical diagnoses; always advise consulting a professional for concerning symptoms.
"""

# Regex tokens
OFF_TOPIC_WORDS = [
    'movie','movies','music','sport','sports','game','games','gaming',
    'stock','stocks','crypto','bitcoin','ethereum','politics','political',
    'weather','recipe','recipes','cooking','baking',
    'car','cars','vehicle','phone','computer','javascript','react','python',
    'programming','coding','software','book','books','novel',
    'celebrity','celebrities','actor','actress','vacation','travel',
    'restaurant','hobby','hobbies','craft','shopping'
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

# ---- Try to import google-genai (new library) ----
GENAI_CLIENT_AVAILABLE = False
try:
    from google import genai
    GENAI_CLIENT_AVAILABLE = True
    logger.info("✅ New google-genai client available")
except ImportError as e:
    logger.warning(f"New google-genai not available: {e}")
    GENAI_CLIENT_AVAILABLE = False

# Disable old library
OLD_GENAI_AVAILABLE = False

# --------------------------------------------
class GeminiHealthChat:
    def __init__(self):
        self.available = False
        self.client = None
        self.conversation_history = {}
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        
        logger.info(f"API Key available: {bool(self.api_key)}")
        
        if not self.api_key:
            logger.warning("Gemini API key not found in env (GEMINI_API_KEY or GOOGLE_API_KEY)")
            return

        if GENAI_CLIENT_AVAILABLE:
            try:
                self.client = genai.Client(api_key=self.api_key)
                self.available = True
                logger.info("✅ Google GenAI client initialized successfully")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Google GenAI client: {e}")
                self.available = False
        else:
            logger.warning("No generative AI library available.")

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

    # Fallback conservative flow if guardrails not available
    def fallback_chat(self, user_message: str, session_id: str = "default"):
        # Only block clearly off-topic messages
        user_lower = user_message.lower()
        clearly_off_topic = any(word in user_lower for word in ['movie', 'sport', 'game', 'music', 'stock', 'crypto', 'weather'])
        
        if clearly_off_topic:
            return REFUSAL_TEXT
        
        # SIMPLE GEMINI 2.0 FLASH CALL
        try:
            if GENAI_CLIENT_AVAILABLE and self.client:
                logger.info(f"Calling Gemini 2.0 Flash with: '{user_message}'")
                
                response = self.client.models.generate_content(
                    model=MODEL_NAME,
                    contents=[user_message],
                    config={
                        "system_instruction": SYSTEM_PROMPT_TEXT,
                        "temperature": 0.2,
                        "max_output_tokens": 500,
                    }
                )
                
                # Extract text - new library format
                text = ""
                if hasattr(response, 'text'):
                    text = response.text
                elif hasattr(response, 'candidates') and response.candidates:
                    text = response.candidates[0].content.parts[0].text
                else:
                    text = str(response)
                
                text = text.strip()
                logger.info(f"Gemini response: '{text}'")
                
                # Update conversation history
                history = self.get_conversation_history(session_id)
                history.append({"role": "user", "content": user_message})
                history.append({"role": "assistant", "content": text})
                self.conversation_history[session_id] = history
                
                return text
                
            else:
                logger.warning("Gemini client not available")
                return "Hello! I'm Health Buddy. I specialize in health and wellness topics. How can I assist you today?"
                
        except Exception as e:
            logger.error(f"Gemini API call failed: {str(e)}")
            # Return conversational fallback instead of refusal
            return self.get_conversational_fallback(user_message)

    def get_conversational_fallback(self, user_message: str) -> str:
        """Provide conversational fallback when Gemini fails"""
        user_lower = user_message.lower()
        
        if any(word in user_lower for word in ['migraine', 'headache', 'head', 'pain']):
            return "I understand you're dealing with head pain. Migraines can be challenging. General wellness tips include staying hydrated, resting in a quiet environment, and managing stress. For persistent issues, consulting a healthcare provider is recommended."
        
        elif any(word in user_lower for word in ['diet', 'nutrition', 'food', 'eat']):
            return "Nutrition is key to overall health! A balanced diet with fruits, vegetables, and whole grains supports wellbeing. Are you interested in specific nutrition topics?"
        
        elif any(word in user_lower for word in ['exercise', 'workout', 'fitness']):
            return "Regular exercise benefits both physical and mental health! Finding activities you enjoy makes consistency easier. What type of movement interests you?"
        
        elif any(word in user_lower for word in ['sleep', 'tired', 'insomnia']):
            return "Quality sleep is essential! Consistent routines and comfortable environments can improve sleep. Are you having trouble with sleep patterns?"
        
        elif any(word in user_lower for word in ['stress', 'anxiety', 'mental']):
            return "Mental wellness matters! Techniques like deep breathing, mindfulness, and social connection can help manage stress. Would you like to explore wellness strategies?"
        
        else:
            return "Hello! I'm Health Buddy, your wellness assistant. I'd love to help with health topics like nutrition, exercise, sleep, stress management, or general wellbeing. What would you like to discuss?"

    # Guardrails flow (simplified)
    def guardrails_chat(self, user_message: str, session_id: str = "default"):
        # If guard not loaded, fallback
        return self.fallback_chat(user_message, session_id)

    def chat(self, user_message: str, session_id: str = "default"):
        # Use fallback chat (guardrails disabled for now)
        return self.fallback_chat(user_message, session_id)

# ---------------- JSON-RPC helper & Views ----------------

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

            # Handle empty object case
            if not body:
                return self.build_method_error_response(None, "Unknown method. Use 'message/send' or 'execute'.")

            request_id = body.get("id", "")
            method = body.get("method")
            
            # Check for required JSON-RPC fields but be more permissive
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
        # Test Gemini availability
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