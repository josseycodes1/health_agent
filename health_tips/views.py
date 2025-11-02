# views.py
import logging
import json
import uuid
import os
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
# Set this to the model name that is printed by your list_models.py
# Example: "models/gemini-2.5-flash" (use exact string from list_models)
MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "models/gemini-2.5-flash")

SYSTEM_PROMPT_TEXT = """You are Health Buddy, a strictly focused health and wellness virtual assistant.
CRITICAL RULES:
1. Only answer questions about human health, wellness, nutrition, exercise, mental health, and sleep.
2. Politely but firmly refuse any unrelated topics (pets, sports, entertainment, politics, recipes not about nutrition, etc.).
3. Keep refusals concise (1-2 sentences) and friendly.
4. Do not provide medical diagnoses. For concerning symptoms recommend seeking a qualified healthcare professional.
If a user asks something not health-related, respond exactly with: "I specialize only in health and wellness topics. I can help with nutrition, exercise, mental health, sleep, or other health-related questions!" and optionally offer a short health-related pivot question.
"""

# ---- Helper classes / functions ----

class GeminiHealthChat:
    def __init__(self):
        self.available = False
        self.client = None
        self.conversation_history = {}

        # get API key from env
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("Gemini API key not found in env (GEMINI_API_KEY or GOOGLE_API_KEY)")
            return

        # Prefer modern client
        if GENAI_CLIENT_AVAILABLE:
            try:
                # create a client instance (explicitly pass api_key)
                self.client = genai_client_pkg.Client(api_key=self.api_key)
                self.available = True
                logger.info("Gemini Health Chat initialized (google-genai client).")
            except Exception as e:
                logger.error(f"Failed to init google-genai client: {e}")
                self.available = False
        elif OLD_GENAI_AVAILABLE:
            # fallback - older package naming compatibility (best-effort)
            try:
                genai_old.configure(api_key=self.api_key)
                self.client = genai_old  # store module reference (legacy usage)
                self.available = True
                logger.info("Gemini Health Chat initialized (legacy google.generativeai).")
            except Exception as e:
                logger.error(f"Failed to init legacy genai: {e}")
                self.available = False
        else:
            logger.warning("No generative AI client available (google-genai or google.generativeai).")

    def is_health_related(self, message: str) -> bool:
        """Return True only if message is clearly health-related.
        If message contains any off-topic strong tokens -> reject immediately.
        """
        if not message or not message.strip():
            return False

        m = message.lower()

        # Strong off-topic tokens: if present, always reject
        off_topic_tokens = {
            'dog', 'dogs', 'pet', 'pets', 'cat', 'cats', 'animal', 'animals',
            'movie', 'movies', 'music', 'sport', 'sports', 'game', 'games',
            'stock', 'crypto', 'bitcoin', 'politics', 'weather', 'recipe',
            'recipes', 'car', 'cars', 'phone', 'computer', 'javascript', 'react',
            'programming', 'coding', 'book', 'books', 'celebrity', 'celebrities',
            'vacation', 'travel', 'restaurant', 'hobby', 'hobbies'
        }
        for token in off_topic_tokens:
            if f" {token}" in (" " + m) or m.startswith(token + " ") or m == token:
                # found a distinct off-topic token
                return False

        # Health-related keywords (if at least one exists, allow)
        health_keywords = {
            'health','wellness','nutrition','diet','exercise','fitness','mental','stress',
            'sleep','medical','doctor','hospital','pain','illness','symptom','treatment',
            'medicine','vitamin','weight','workout','yoga','meditation','therapy','healthy',
            'condition','diagnosis','recovery','cardio','calorie','protein','hydration',
            'depression','anxiety','insomnia','fatigue','blood pressure','cholesterol',
            'diabetes','heart','lung','brain','rehabilitation','prevention'
        }
        has_health = any(kw in m for kw in health_keywords)

        # If clearly health-related, allow
        if has_health:
            return True

        # ambiguous (no health words and no off-topic tokens) -> treat as NOT health-related
        return False

    def get_refusal_reply(self):
        return "I specialize only in health and wellness topics. I can help with nutrition, exercise, mental health, sleep, or other health-related questions!"

    def get_clarifying_prompt(self):
        # used when ambiguous input arrives: ask a short health-focused clarifying question
        return "Are you asking about a health or wellness concern? If so, please tell me briefly (e.g., sleep, stress, diet)."

    def get_conversation_history(self, session_id):
        """Keep a short seed history for each session so the system prompt is always present."""
        if session_id not in self.conversation_history:
            # a minimal starting history: system + greeting example
            self.conversation_history[session_id] = [
                {"role": "system", "content": SYSTEM_PROMPT_TEXT},
                {"role": "assistant", "content": "Hello! I'm Health Buddy, your dedicated health and wellness assistant. How can I help you today?"}
            ]
        return self.conversation_history[session_id]

    def chat(self, user_message: str, session_id: str = "default"):
        if not self.available:
            return "I'm currently unavailable — please try again later. 💚"

        # 1) pre-check: off-topic/health detection
        if not self.is_health_related(user_message):
            # If the message contains a clear off-topic token, refuse
            # If ambiguous, ask a clarifying health-focused question
            # Determine if ambiguous (no off-topic token but no health words)
            # We already returned False for off-topic tokens; so it's ambiguous -> ask to clarify
            logger.info(f"Refusing or clarifying off-topic/ambiguous user input: {user_message}")
            # If the message contains any off-topic token (we already rejected), return refusal.
            # For ambiguous messages, return a clarifying prompt
            # Use simple heuristics: if it's short (<=3 words) or generic greeting -> clarify
            if len(user_message.split()) <= 4:
                return self.get_clarifying_prompt()
            return self.get_refusal_reply()

        # 2) Compose messages for the model call: seed history + user message
        history = self.get_conversation_history(session_id).copy()
        history.append({"role": "user", "content": user_message})

        # Limit the history length to avoid blowing up tokens
        if len(history) > 12:
            history = history[:2] + history[-10:]

        # 3) Call the generative API using the available client
        try:
            if GENAI_CLIENT_AVAILABLE and isinstance(self.client, genai_client_pkg.Client):
                # modern google-genai client: use models.generate_content
                # Build messages list in the new request format (role/content)
                response = self.client.models.generate_content(
                    model=MODEL_NAME,
                    messages=history,
                    temperature=0.7,
                    max_output_tokens=150
                )
                # response may contain .output[0].content[0].text or convenience attribute
                # pick common safe extraction
                text = None
                if hasattr(response, "output"):
                    # new SDK returns structured output; attempt to extract plain text
                    try:
                        # iterate output items to find text
                        outputs = response.output
                        if outputs and isinstance(outputs, list):
                            first = outputs[0]
                            # Some SDKs embed text under 'content' list with 'text' fields
                            content = getattr(first, "content", None)
                            if content and isinstance(content, list):
                                # join text parts
                                parts = []
                                for c in content:
                                    t = getattr(c, "text", None) or c.get("text") if isinstance(c, dict) else None
                                    if t:
                                        parts.append(t)
                                text = " ".join(parts).strip()
                    except Exception:
                        pass
                # fallback to str(response) if no text extracted
                if not text:
                    try:
                        text = getattr(response, "text", None) or str(response)
                    except Exception:
                        text = "Sorry — I couldn't generate a response right now."

                # Update stored conversation history with assistant reply
                self.conversation_history[session_id] = history + [{"role": "assistant", "content": text}]
                logger.info(f"Generated response (client.models) for session {session_id}")
                return text.strip()

            elif OLD_GENAI_AVAILABLE and self.client:
                # legacy usage for older google.generativeai package
                # try to call the older chat API (best-effort, keeps compatibility)
                try:
                    model = self.client.GenerativeModel(MODEL_NAME)
                    chat_session = model.start_chat(history=[
                        {"role": "system", "content": SYSTEM_PROMPT_TEXT},
                        {"role": "assistant", "content": "Hello! I'm Health Buddy, your dedicated health and wellness assistant."},
                    ])
                    response = chat_session.send_message(user_message)
                    text = getattr(response, "text", str(response))
                    self.conversation_history[session_id] = history + [{"role": "assistant", "content": text}]
                    logger.info(f"Generated response (legacy) for session {session_id}")
                    return text.strip()
                except Exception as e:
                    logger.error(f"Legacy client error: {e}")
                    return "I specialize in health and wellness topics. How can I help with your health questions today?"

            else:
                return "I’m unable to access the AI service right now."
        except Exception as e:
            logger.error(f"Gemini chat failed: {e}")
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
            logger.error(f"Unexpected error in A2A endpoint: {e}")
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

            # Use greeting for empty messages or generic greetings
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
            logger.error(f"Error in handle_message_send: {e}")
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
            logger.error(f"Error in handle_execute: {e}")
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




# import logging
# import json
# import uuid
# import os
# from django.http import JsonResponse
# from django.views import View
# from django.views.decorators.csrf import csrf_exempt
# from django.utils.decorators import method_decorator
# from django.utils import timezone
# from google import genai


# logger = logging.getLogger(__name__)

# try:
#     import google.generativeai as genai
#     GEMINI_AVAILABLE = True
# except ImportError:
#     GEMINI_AVAILABLE = False
#     logger.warning("Google Generative AI package not installed")

# class GeminiHealthChat:
#     def __init__(self):
#         self.api_key = os.getenv('GEMINI_API_KEY')
#         if self.api_key and GEMINI_AVAILABLE:
#             try:
#                 genai.configure(api_key=self.api_key)
#                 self.model = genai.GenerativeModel('gemini-2.0-flash')
#                 self.available = True
#                 self.conversation_history = {}
#                 logger.info("Gemini Health Chat initialized successfully")
#             except Exception as e:
#                 logger.error(f"Gemini initialization failed: {e}")
#                 self.available = False
#         else:
#             self.available = False
#             logger.warning("Gemini API key not found or package not available")
    
#     def is_health_related(self, message):
#         """Check if message is health-related before processing"""
#         if not message or not message.strip():
#             return False
            
#         message_lower = message.lower().strip()
        
#         # Health-related keywords
#         health_keywords = [
#             'health', 'wellness', 'nutrition', 'diet', 'exercise', 'fitness',
#             'mental', 'stress', 'sleep', 'medical', 'doctor', 'hospital',
#             'pain', 'illness', 'symptom', 'treatment', 'medicine', 'vitamin',
#             'weight', 'food', 'eat', 'workout', 'yoga', 'meditation', 'therapy',
#             'healthy', 'unhealthy', 'condition', 'diagnosis', 'recovery',
#             'fitness', 'muscle', 'cardio', 'strength', 'flexibility', 'endurance',
#             'calorie', 'protein', 'carb', 'fat', 'fiber', 'mineral', 'supplement',
#             'anxiety', 'depression', 'mindfulness', 'counseling', 'psychology',
#             'insomnia', 'rest', 'energy', 'fatigue', 'hydration', 'water',
#             'blood pressure', 'cholesterol', 'diabetes', 'heart', 'lung', 'brain',
#             'physical', 'therapy', 'rehabilitation', 'prevention', 'wellbeing'
#         ]
        
#         # Off-topic keywords to reject
#         off_topic_keywords = [
#             'dog', 'dogs', 'pet', 'pets', 'cat', 'cats', 'animal', 'animals',
#             'sport', 'sports', 'game', 'games', 'movie', 'movies', 'music',
#             'weather', 'news', 'politics', 'car', 'cars', 'computer', 'phone',
#             'tv', 'television', 'book', 'books', 'celebrity', 'celebrities',
#             'travel', 'vacation', 'holiday', 'shopping', 'buy', 'purchase',
#             'school', 'work', 'job', 'career', 'money', 'finance', 'stock',
#             'house', 'home', 'garden', 'plant', 'plants', 'cooking', 'recipe',
#             'restaurant', 'movie', 'film', 'entertainment', 'hobby', 'hobbies'
#         ]
        
#         # Check if message contains health keywords
#         has_health_content = any(keyword in message_lower for keyword in health_keywords)
        
#         # Check if message is clearly off-topic
#         is_off_topic = any(keyword in message_lower for keyword in off_topic_keywords)
        
#         # Also reject very generic messages that aren't health-focused
#         generic_messages = ['how are you', 'hello', 'hi', 'hey', 'what can you do', 'whats up', "what's up"]
#         is_generic = any(msg in message_lower for msg in generic_messages)
        
#         # Special case: if it's a greeting but mentions health, allow it
#         if is_generic and has_health_content:
#             return True
            
#         return has_health_content and not is_off_topic
    
#     def get_redirect_response(self):
#         """Standard response for off-topic questions"""
#         return "I specialize only in health and wellness topics. I can help with nutrition, exercise, mental health, sleep, or other health-related questions! 💪😊"
    
#     def get_conversation_history(self, session_id):
#         if session_id not in self.conversation_history:
#             self.conversation_history[session_id] = [
#                 {
#                     "role": "user",
#                     "parts": [{
#                         "text": """You are HealthAI, a STRICT health and wellness assistant. Your role is:

# CRITICAL RULES - NEVER BREAK THESE:
# 1. ONLY discuss health, wellness, nutrition, exercise, mental health, sleep, and medical topics
# 2. FIRMLY but politely decline ANY non-health related questions immediately
# 3. If users ask about pets, sports, weather, food, animals, or other off-topic subjects, respond EXACTLY: "I specialize only in health and wellness topics. I can help with nutrition, exercise, mental health, sleep, or other health-related questions!"
# 4. NEVER provide information about dogs, pets, animals, or any non-health topics
# 5. Immediately redirect back to health topics without engaging in off-topic discussions
# 6. If someone asks "do you know about X" where X is not health-related, say you only know health topics
# 7. Keep responses concise (1-2 sentences)
# 8. Be friendly but firm about your scope
# 9. Use simple emojis occasionally

# HEALTH TOPICS ONLY:
# - Nutrition and diet for HUMANS
# - Exercise and fitness for HUMANS  
# - Mental health and stress
# - Sleep and rest
# - Medical conditions (general advice only)
# - Healthy habits
# - Wellness tips
# - Preventive care

# OFF-TOPIC SUBJECTS TO REJECT:
# - Pets, dogs, animals
# - Sports, games, entertainment
# - Weather, news, politics
# - Food recipes (unless nutrition/health focused)
# - General chit-chat like "how are you"

# Remember: You are a health specialist, not a general AI. Stay strictly in your lane. If you break these rules, you could give dangerous medical advice about topics you're not qualified for."""
#                     }]
#                 },
#                 {
#                     "role": "model", 
#                     "parts": [{
#                         "text": "Hello! I'm HealthAI, your dedicated health and wellness assistant! 😊 I'm here to help with nutrition, exercise, mental health, sleep, and all health-related questions. How can I support your wellness journey today?"
#                     }]
#                 }
#             ]
#         return self.conversation_history[session_id]
    
#     def chat(self, user_message, session_id="default"):
#         if not self.available:
#             return "I'm currently unavailable, but I'd love to chat about health tips soon! Please try again in a moment. 💚"
        
#         # Pre-filter non-health topics
#         if not self.is_health_related(user_message):
#             logger.info(f"Redirected off-topic question: {user_message}")
#             return self.get_redirect_response()
        
#         try:
#             history = self.get_conversation_history(session_id)
            
#             history.append({
#                 "role": "user",
#                 "parts": [{"text": user_message}]
#             })
            
#             chat_session = self.model.start_chat(history=history[:-1])
#             response = chat_session.send_message(
#                 user_message,
#                 generation_config=genai.types.GenerationConfig(
#                     max_output_tokens=100, 
#                     temperature=0.7,
#                 )
#             )
            
#             history.append({
#                 "role": "model", 
#                 "parts": [{"text": response.text}]
#             })
            
#             if len(history) > 20:
#                 history = [history[0], history[1]] + history[-18:]
            
#             self.conversation_history[session_id] = history
            
#             logger.info(f"Gemini response generated for session: {session_id}")
#             return response.text.strip()
            
#         except Exception as e:
#             logger.error(f"Gemini chat failed: {str(e)}")
#             return "I specialize in health and wellness topics. How can I help with your health questions today?"


# class JSONErrorResponse:
#     @staticmethod
#     def error(request_id, code, message, data=None):
#         return JsonResponse({
#             "jsonrpc": "2.0",
#             "id": request_id,
#             "error": {
#                 "code": code,
#                 "message": message,
#                 "data": data or {}
#             }
#         })
    
#     @staticmethod
#     def internal_error(request_id, details=None):
#         return JSONErrorResponse.error(
#             request_id, 
#             -32603, 
#             "Internal error", 
#             {"details": details}
#         )
    
#     @staticmethod
#     def invalid_params(request_id, details=None):
#         return JSONErrorResponse.error(
#             request_id, 
#             -32602, 
#             "Invalid params", 
#             {"details": details}
#         )
    
#     @staticmethod
#     def invalid_request(request_id, details=None):
#         return JSONErrorResponse.error(
#             request_id, 
#             -32600, 
#             "Invalid Request", 
#             {"details": details}
#         )

# @method_decorator(csrf_exempt, name='dispatch')
# class A2AHealthView(View):
    
#     def __init__(self):
#         super().__init__()
#         self.gemini_chat = GeminiHealthChat()
    
#     def post(self, request):
#         try:
#             try:
#                 body = json.loads(request.body)
#             except json.JSONDecodeError:
#                 logger.error("Invalid JSON in request body")
#                 return JSONErrorResponse.invalid_request(
#                     None, 
#                     "Invalid JSON format"
#                 )
            
#             if body.get("jsonrpc") != "2.0" or "id" not in body:
#                 logger.error("Invalid JSON-RPC request format")
#                 return JSONErrorResponse.invalid_request(
#                     body.get("id"),
#                     "jsonrpc must be '2.0' and id is required"
#                 )
            
#             request_id = body.get("id")
#             method = body.get("method")
#             params = body.get("params", {})
            
#             logger.info(f"Processing A2A request: {method}, ID: {request_id}")
            
#             if method == "message/send":
#                 return self.handle_message_send(request_id, params)
#             elif method == "execute":
#                 return self.handle_execute(request_id, params)
#             else:
#                 logger.error(f"Method not found: {method}")
#                 return JSONErrorResponse.error(
#                     request_id, 
#                     -32601, 
#                     "Method not found"
#                 )
                
#         except Exception as e:
#             logger.error(f"Unexpected error in A2A endpoint: {str(e)}")
#             return JSONErrorResponse.internal_error(
#                 body.get("id") if 'body' in locals() else None,
#                 str(e)
#             )
    
#     def handle_message_send(self, request_id, params):
#         try:
#             message = params.get("message", {})
#             configuration = params.get("configuration", {})
            
#             context_id = message.get("taskId") or str(uuid.uuid4())
#             task_id = message.get("messageId") or str(uuid.uuid4())
            
#             user_message = ""
#             for part in message.get("parts", []):
#                 if part.get("kind") == "text":
#                     user_message = part.get("text", "").strip()
#                     break
            
#             session_id = context_id  
            
#             # Use greeting for empty messages or generic greetings
#             if not user_message:
#                 response_text = "Hello! I'm HealthAI, your dedicated health and wellness assistant! 😊 I'm here to help with nutrition, exercise, mental health, sleep, and all health-related questions. How can I support your wellness journey today?"
#             elif user_message.lower() in ['hi', 'hello', 'how are you', 'hey', 'whats up', "what's up"]:
#                 response_text = "Hello! I'm HealthAI, your dedicated health and wellness assistant! 😊 I'm here to help with nutrition, exercise, mental health, sleep, and all health-related questions. How can I support your wellness journey today?"
#             else:
#                 response_text = self.gemini_chat.chat(user_message, session_id)
            
#             logger.info(f"Conversational response for: {user_message}")
            
#             response = self.build_success_response(
#                 request_id, 
#                 response_text,
#                 context_id, 
#                 task_id
#             )
            
#             return JsonResponse(response)
            
#         except Exception as e:
#             logger.error(f"Error in handle_message_send: {str(e)}")
#             return JSONErrorResponse.internal_error(request_id, str(e))
    
#     def handle_execute(self, request_id, params):
#         try:
#             messages = params.get("messages", [])
#             context_id = params.get("contextId") or str(uuid.uuid4())
#             task_id = params.get("taskId") or str(uuid.uuid4())
            
#             user_message = ""
#             if messages:
#                 for msg in messages:
#                     for part in msg.get("parts", []):
#                         if part.get("kind") == "text":
#                             user_message = part.get("text", "").strip()
#                             break
#                     if user_message:
#                         break
            
#             session_id = context_id
            
#             if not user_message:
#                 response_text = "Hello! I'm HealthAI, your friendly health assistant! 😊 How can I help with your health and wellness today?"
#             elif user_message.lower() in ['hi', 'hello', 'how are you', 'hey', 'whats up', "what's up"]:
#                 response_text = "Hello! I'm HealthAI, your friendly health assistant! 😊 How can I help with your health and wellness today?"
#             else:
#                 response_text = self.gemini_chat.chat(user_message, session_id)
            
#             logger.info(f"Execute conversation - Context: {context_id}")
            
#             response = self.build_success_response(
#                 request_id, 
#                 response_text,
#                 context_id, 
#                 task_id
#             )
            
#             return JsonResponse(response)
            
#         except Exception as e:
#             logger.error(f"Error in handle_execute: {str(e)}")
#             return JSONErrorResponse.internal_error(request_id, str(e))
    
#     def build_success_response(self, request_id, response_text, context_id, task_id):
#         from datetime import datetime
        
#         return {
#             "jsonrpc": "2.0",
#             "id": request_id,
#             "result": {
#                 "id": task_id,
#                 "contextId": context_id,
#                 "status": {
#                     "state": "completed",
#                     "timestamp": datetime.utcnow().isoformat() + "Z",
#                     "message": {
#                         "messageId": str(uuid.uuid4()),
#                         "role": "agent",
#                         "parts": [
#                             {
#                                 "kind": "text",
#                                 "text": response_text
#                             }
#                         ],
#                         "kind": "message",
#                         "taskId": task_id
#                     }
#                 },
#                 "artifacts": [
#                     {
#                         "artifactId": str(uuid.uuid4()),
#                         "name": "health_response",
#                         "parts": [
#                             {
#                                 "kind": "text",
#                                 "text": response_text
#                             }
#                         ]
#                     }
#                 ],
#                 "history": [
#                     {
#                         "messageId": str(uuid.uuid4()),
#                         "role": "agent",
#                         "parts": [
#                             {
#                                 "kind": "text",
#                                 "text": response_text
#                             }
#                         ],
#                         "kind": "message",
#                         "taskId": task_id
#                     }
#                 ],
#                 "kind": "task"
#             }
#         }

# class HealthCheckView(View):
#     def __init__(self):
#         super().__init__()
#         self.gemini_chat = GeminiHealthChat()
    
#     def get(self, request):
#         return JsonResponse({
#             "status": "healthy",
#             "service": "health_conversation_agent",
#             "timestamp": timezone.now().isoformat(),
#             "gemini_available": self.gemini_chat.available
#         })