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
from datetime import datetime

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.0-flash"
SYSTEM_PROMPT_TEXT = """You are Health Buddy, a health and wellness assistant.

CRITICAL RULES:
1. Answer ALL human health questions including: physical health, mental health, nutrition, exercise, sleep, pain, symptoms, wellness, and general health concerns.
2. Only refuse clearly non-health topics like movies, sports, politics, programming, etc.
3. For health topics, provide helpful wellness advice and general guidance.
4. Do not provide medical diagnoses; always advise consulting a healthcare professional for specific medical concerns.
5. Use this EXACT refusal message only for non-health topics:
"I specialize only in health and wellness topics. I can help with nutrition, exercise, mental health, sleep, or other health-related questions!"

EXAMPLES OF HEALTH TOPICS TO ANSWER:
- Pain (headache, stomachache, toothache, back pain, etc.)
- Symptoms (fever, cough, fatigue, etc.) 
- Nutrition and diet
- Exercise and fitness
- Mental health and stress
- Sleep issues
- General wellness and prevention
- Any health-related concerns
"""

REFUSAL_TEXT = "I specialize only in health and wellness topics. I can help with nutrition, exercise, mental health, sleep, or other health-related questions!"

GENAI_CLIENT_AVAILABLE = False
try:
    from google import genai
    GENAI_CLIENT_AVAILABLE = True
    logger.info("New google-genai client available")
except ImportError as e:
    logger.warning(f"New google-genai not available: {e}")
    GENAI_CLIENT_AVAILABLE = False

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
                logger.info("Google GenAI client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Google GenAI client: {e}")
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

    def chat(self, user_message: str, session_id: str = "default"):
        logger.info(f"Processing user message: '{user_message}' for session: {session_id}")
        
        user_lower = user_message.lower()
        clearly_off_topic = any(word in user_lower for word in ['movie', 'sport', 'game', 'music', 'stock', 'crypto', 'weather'])
        
        if clearly_off_topic:
            logger.info("Message detected as off-topic, sending refusal")
            return REFUSAL_TEXT
        
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
                
                text = ""
                if hasattr(response, 'text'):
                    text = response.text
                elif hasattr(response, 'candidates') and response.candidates:
                    text = response.candidates[0].content.parts[0].text
                else:
                    text = str(response)
                
                text = text.strip()
                logger.info(f"Gemini response received: '{text}'")
                
                history = self.get_conversation_history(session_id)
                history.append({"role": "user", "content": user_message})
                history.append({"role": "assistant", "content": text})
                self.conversation_history[session_id] = history
                
                return text
                
            else:
                logger.warning("Gemini client not available, using fallback response")
                return "Hello! I'm Health Buddy. I specialize in health and wellness topics. How can I assist you today?"
                
        except Exception as e:
            logger.error(f"Gemini API call failed: {str(e)}")
            # Simple fallback responses
            user_lower = user_message.lower()
            if any(word in user_lower for word in ['headache', 'migraine', 'head pain']):
                return "I understand you're dealing with head pain. General wellness tips include staying hydrated, resting in a quiet environment, and managing stress. For persistent issues, consulting a healthcare provider is recommended."
            elif any(word in user_lower for word in ['diet', 'nutrition', 'food']):
                return "Nutrition is key to overall health! A balanced diet with fruits, vegetables, and whole grains supports wellbeing."
            elif any(word in user_lower for word in ['exercise', 'workout', 'fitness']):
                return "Regular exercise benefits both physical and mental health! Finding activities you enjoy makes consistency easier."
            elif any(word in user_lower for word in ['sleep', 'tired', 'insomnia']):
                return "Quality sleep is essential! Consistent routines and comfortable environments can improve sleep."
            elif any(word in user_lower for word in ['stress', 'anxiety', 'mental']):
                return "Mental wellness matters! Techniques like deep breathing, mindfulness, and social connection can help manage stress."
            else:
                return "Hello! I'm Health Buddy, your wellness assistant. I'd love to help with health topics like nutrition, exercise, sleep, stress management, or general wellbeing. What would you like to discuss?"

@method_decorator(csrf_exempt, name='dispatch')
class A2AHealthView(View):
    def __init__(self):
        super().__init__()
        logger.info("Initializing A2AHealthView...")
        self.gemini_chat = GeminiHealthChat()
        logger.info(f"Gemini chat available: {self.gemini_chat.available}")

    def post(self, request):
        logger.info("Received POST request to A2A endpoint")
        try:
            try:
                body = json.loads(request.body)
                logger.info(f"Request body parsed successfully, ID: {body.get('id', 'unknown')}")
            except json.JSONDecodeError:
                logger.error("Invalid JSON in request body")
                return self.build_error_response(None, -32700, "Parse error: Invalid JSON")

            # Validate JSON-RPC 2.0 basics
            if body.get("jsonrpc") != "2.0" or "id" not in body:
                logger.error("Invalid JSON-RPC request: missing jsonrpc or id")
                return self.build_error_response(
                    body.get("id"), 
                    -32600, 
                    "Invalid Request: jsonrpc must be '2.0' and id is required"
                )

            request_id = body.get("id", "")
            method = body.get("method")
            
            if not method:
                logger.error("No method specified in request")
                return self.build_error_response(request_id, -32601, "Method not found")

            params = body.get("params", {})
            logger.info(f"Processing A2A request: method={method}, ID={request_id}")

            if method == "message/send":
                return self.handle_message_send(request_id, params)
            elif method == "help":
                return self.handle_help(request_id, params)
            else:
                logger.error(f"Method not found: {method}")
                return self.build_error_response(request_id, -32601, f"Method not found: {method}")

        except Exception as e:
            logger.exception(f"Unexpected error in A2A endpoint: {str(e)}")
            return self.build_error_response(
                body.get("id") if 'body' in locals() else None, 
                -32603, 
                f"Internal error: {str(e)}"
            )

    def build_error_response(self, request_id, code, message):
        logger.info(f"Building error response: code={code}, message={message}")
        return JsonResponse({
            "jsonrpc": "2.0",
            "id": request_id or "",
            "error": {
                "code": code,
                "message": message,
                "data": {}
            }
        })

    def handle_message_send(self, request_id, params):
        logger.info(f"Processing message/send request: {request_id}")
        try:
            message = params.get("message", {})
            context_id = message.get("taskId") or str(uuid.uuid4())
            task_id = message.get("messageId") or str(uuid.uuid4())

            logger.info(f"Context ID: {context_id}, Task ID: {task_id}")
            
            user_message = ""
            parts = message.get("parts", [])
            
            logger.info(f"Found {len(parts)} parts in message")
            
            # Log all parts for debugging
            for i, part in enumerate(parts):
                part_kind = part.get('kind', 'unknown')
                part_text = part.get('text', '')[:100] if part.get('text') else 'NO_TEXT'
                logger.info(f"Part {i}: kind={part_kind}, text_preview='{part_text}'")
                
                # Also log data parts if they exist
                if part.get('data'):
                    logger.info(f"Part {i} data: {part.get('data')}")

            # STRATEGY: Look for user messages in DATA parts (conversation history)
            user_messages = []
            
            for part in parts:
                if part.get("kind") == "data" and part.get("data"):
                    data_items = part.get("data", [])
                    logger.info(f"Found data part with {len(data_items)} items")
                    
                    for item in data_items:
                        if (isinstance(item, dict) and 
                            item.get("kind") == "text" and 
                            item.get("text")):
                            
                            text = item.get("text", "").strip()
                            # Look for user messages (not bot responses)
                            if text and not self.is_bot_response(text):
                                user_messages.append(text)
                                logger.info(f"Found user message in data: '{text}'")
            
            # If we found user messages in data parts, take the MOST RECENT one
            if user_messages:
                user_message = user_messages[-1]  # Last one is most recent
                logger.info(f"Selected most recent user message from data: '{user_message}'")
            
            # FALLBACK: If no user messages found in data, check regular text parts
            # but be careful to avoid Telex's AI responses
            if not user_message:
                text_parts = []
                for part in parts:
                    if part.get("kind") == "text" and part.get("text"):
                        text = part.get("text", "").strip()
                        # Filter out bot responses
                        if text and not self.is_bot_response(text):
                            text_parts.append(text)
                            logger.info(f"Found text part (filtered): '{text}'")
                
                if text_parts:
                    user_message = text_parts[-1]
                    logger.info(f"Selected user message from text parts: '{user_message}'")
                else:
                    logger.warning("No user messages found in request")
                    user_message = ""

            session_id = context_id

            # Generate response
            if not user_message:
                response_text = "Hello! I'm Health Buddy, your dedicated health and wellness assistant! I'm here to help with nutrition, exercise, mental health, sleep, and all health-related questions. How can I support your wellness journey today?"
                logger.info("Sending default greeting (no user message)")
            elif user_message.lower() in ['hi', 'hello', 'how are you', 'hey', 'whats up', "what's up"]:
                response_text = "Hello! I'm Health Buddy, your dedicated health and wellness assistant! I'm here to help with nutrition, exercise, mental health, sleep, and all health-related questions. How can I support your wellness journey today?"
                logger.info("Sending greeting response")
            else:
                logger.info(f"Sending to Gemini: '{user_message}'")
                response_text = self.gemini_chat.chat(user_message, session_id)
                logger.info(f"Gemini response: '{response_text}'")

            response = self.build_success_response(request_id, response_text, context_id, task_id)
            logger.info(f"Successfully built response for request: {request_id}")
            
            return JsonResponse(response)

        except Exception as e:
            logger.exception(f"Error in handle_message_send: {str(e)}")
            return self.build_error_response(request_id, -32603, f"Internal error: {str(e)}")

def is_bot_response(self, text: str) -> bool:
    """Check if text is a bot/AI response (not a user message)"""
    text_lower = text.lower()
    
    # Indicators that this is a bot/AI response, not a user message
    bot_indicators = [
        'here are some', 'steps you can take', 'suggestions to help',
        'advice for', 'tips that might help', 'consider taking',
        'you can use', 'it\'s essential to', 'contact a healthcare',
        'rinse with warm salt water', 'over-the-counter', 'cold compress',
        'avoid irritating foods', 'maintain oral hygiene', 'topical anesthetics',
        'stay hydrated', 'see a dentist'
    ]
    
    # If the text starts with any of these patterns, it's likely a bot response
    return any(text_lower.startswith(indicator) for indicator in bot_indicators) or any(indicator in text_lower for indicator in bot_indicators)

    def handle_help(self, request_id, params):
        logger.info(f"Processing help request: {request_id}")
        help_text = "Available methods: 'message/send' for sending messages, 'help' for this information."
        
        return JsonResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "id": str(uuid.uuid4()),
                "contextId": str(uuid.uuid4()),
                "status": {
                    "state": "completed",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "message": {
                        "kind": "message",
                        "role": "agent",
                        "parts": [
                            {
                                "kind": "text",
                                "text": help_text
                            }
                        ],
                        "messageId": str(uuid.uuid4()),
                        "taskId": str(uuid.uuid4())
                    }
                },
                "artifacts": [
                    {
                        "artifactId": str(uuid.uuid4()),
                        "name": "assistantResponse",
                        "parts": [
                            {
                                "kind": "text",
                                "text": help_text
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
                                "text": help_text
                            }
                        ],
                        "messageId": str(uuid.uuid4()),
                        "taskId": str(uuid.uuid4())
                    }
                ],
                "kind": "task"
            }
        })

    def build_success_response(self, request_id, response_text, context_id, task_id):
        logger.info(f"Building success response for request: {request_id}")
        message_id = str(uuid.uuid4())
        artifact_id = str(uuid.uuid4())
        
        # Create response following documentation structure
        response_message = {
            "kind": "message",
            "role": "agent",
            "parts": [
                {
                    "kind": "text",
                    "text": response_text
                }
            ],
            "messageId": message_id,
            "taskId": task_id
        }

        response_data = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "id": task_id,  # Use the incoming task_id
                "contextId": context_id,  # Use the incoming context_id
                "status": {
                    "state": "completed",
                    "timestamp": datetime.utcnow().isoformat() + "Z",  # With Z like documentation
                    "message": response_message  # Message inside status like documentation
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
                "history": [response_message],
                "kind": "task"
            }
        }
        
        logger.info(f"Success response built with context_id: {context_id}, task_id: {task_id}")
        return response_data

class HealthCheckView(View):
    def __init__(self):
        super().__init__()
        logger.info("Initializing HealthCheckView...")
        self.gemini_chat = GeminiHealthChat()
        logger.info(f"Gemini chat available: {self.gemini_chat.available}")

    def get(self, request):
        logger.info("Health check requested")
        test_response = "Not tested"
        if self.gemini_chat.available:
            try:
                logger.info("Testing Gemini connection...")
                test_response = self.gemini_chat.chat("test health question")
                logger.info(f"Gemini test successful: {test_response}")
            except Exception as e:
                logger.error(f"Gemini test failed: {str(e)}")
                test_response = f"Error: {str(e)}"
        else:
            logger.warning("Gemini not available")
        
        health_data = {
            "status": "healthy",
            "service": "health_conversation_agent",
            "timestamp": timezone.now().isoformat(),
            "gemini_available": self.gemini_chat.available,
            "test_response": test_response
        }
        
        logger.info(f"Health check response: {health_data}")
        return JsonResponse(health_data)