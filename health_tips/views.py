import logging
import json
import uuid
import os
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from google import genai


logger = logging.getLogger(__name__)

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("Google Generative AI package not installed")

class GeminiHealthChat:
    def __init__(self):
        self.api_key = os.getenv('GEMINI_API_KEY')
        if self.api_key and GEMINI_AVAILABLE:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel('gemini-2.0-flash')
                self.available = True
                self.conversation_history = {}
                logger.info("Gemini Health Chat initialized successfully")
            except Exception as e:
                logger.error(f"Gemini initialization failed: {e}")
                self.available = False
        else:
            self.available = False
            logger.warning("Gemini API key not found or package not available")
    
    def get_conversation_history(self, session_id):
        """Get or create conversation history for a session"""
        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = [
                {
                    "role": "user",
                    "parts": [{
                        "text": """You are HealthAI, a friendly and expert health assistant. Your role is to:

1. Provide engaging, conversational health advice and wellness tips
2. Be warm, empathetic, and supportive like a health coach
3. Answer all health-related questions naturally
4. Keep responses concise but helpful (2-4 sentences)
5. Use emojis occasionally to be friendly 😊
6. Ask follow-up questions to understand user needs better
7. If non-health topics come up, gently steer back to health/wellness

Remember: Be conversational like ChatGPT, not robotic. Respond naturally to whatever the user says."""
                    }]
                },
                {
                    "role": "model",
                    "parts": [{
                        "text": "Hello! I'm HealthAI, your friendly health assistant! 😊 I'm here to help with any health questions, wellness tips, or lifestyle advice. How can I support your health journey today?"
                    }]
                }
            ]
        return self.conversation_history[session_id]
    
    def chat(self, user_message, session_id="default"):
        """Pure conversational chat with Gemini - no health tip database"""
        if not self.available:
            return "I'm currently unavailable, but I'd love to chat about health tips soon! Please try again in a moment. 💚"
        
        try:
            # Get conversation history
            history = self.get_conversation_history(session_id)
            
            # Add user's new message to history
            history.append({
                "role": "user",
                "parts": [{"text": user_message}]
            })
            
            # Generate response using full conversation history
            chat_session = self.model.start_chat(history=history[:-1])
            response = chat_session.send_message(
                user_message,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=150,
                    temperature=0.8,
                )
            )
            
            # Add model response to history
            history.append({
                "role": "model", 
                "parts": [{"text": response.text}]
            })
            
            # Keep history manageable (last 10 exchanges)
            if len(history) > 20:
                history = [history[0], history[1]] + history[-18:]
            
            self.conversation_history[session_id] = history
            
            logger.info(f"Gemini response generated for session: {session_id}")
            return response.text.strip()
            
        except Exception as e:
            logger.error(f"Gemini chat failed: {str(e)}")
            return f"I'd love to help with health tips, but I'm having a moment: {str(e)}. Could you try again? 💚"

# JSONErrorResponse class
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
                return JSONErrorResponse.invalid_request(
                    None, 
                    "Invalid JSON format"
                )
            
            if body.get("jsonrpc") != "2.0" or "id" not in body:
                logger.error("Invalid JSON-RPC request format")
                return JSONErrorResponse.invalid_request(
                    body.get("id"),
                    "jsonrpc must be '2.0' and id is required"
                )
            
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
                return JSONErrorResponse.error(
                    request_id, 
                    -32601, 
                    "Method not found"
                )
                
        except Exception as e:
            logger.error(f"Unexpected error in A2A endpoint: {str(e)}")
            return JSONErrorResponse.internal_error(
                body.get("id") if 'body' in locals() else None,
                str(e)
            )
    
    def handle_message_send(self, request_id, params):
        """Pure conversational handling - no health tip database"""
        try:
            message = params.get("message", {})
            configuration = params.get("configuration", {})
            
            context_id = message.get("taskId") or str(uuid.uuid4())
            task_id = message.get("messageId") or str(uuid.uuid4())
            
            # Extract user message
            user_message = ""
            for part in message.get("parts", []):
                if part.get("kind") == "text":
                    user_message = part.get("text", "").strip()
                    break
            
            # Use session ID for conversation continuity
            session_id = context_id  # Use context_id as session identifier
            
            # Get pure AI response
            response_text = self.gemini_chat.chat(user_message, session_id)
            
            logger.info(f"Conversational response for: {user_message}")
            
            # Build response
            response = self.build_success_response(
                request_id, 
                response_text,
                context_id, 
                task_id
            )
            
            return JsonResponse(response)
            
        except Exception as e:
            logger.error(f"Error in handle_message_send: {str(e)}")
            return JSONErrorResponse.internal_error(request_id, str(e))
    
    def handle_execute(self, request_id, params):
        """Handle execute method with conversation"""
        try:
            messages = params.get("messages", [])
            context_id = params.get("contextId") or str(uuid.uuid4())
            task_id = params.get("taskId") or str(uuid.uuid4())
            
            # Extract user message
            user_message = ""
            if messages:
                for msg in messages:
                    for part in msg.get("parts", []):
                        if part.get("kind") == "text":
                            user_message = part.get("text", "").strip()
                            break
                    if user_message:
                        break
            
            # Use session ID for conversation continuity
            session_id = context_id
            
            if user_message:
                response_text = self.gemini_chat.chat(user_message, session_id)
            else:
                response_text = "Hello! I'm HealthAI, your friendly health assistant! 😊 How can I help with your health and wellness today?"
            
            logger.info(f"Execute conversation - Context: {context_id}")
            
            response = self.build_success_response(
                request_id, 
                response_text,
                context_id, 
                task_id
            )
            
            return JsonResponse(response)
            
        except Exception as e:
            logger.error(f"Error in handle_execute: {str(e)}")
            return JSONErrorResponse.internal_error(request_id, str(e))
    
    def build_success_response(self, request_id, response_text, context_id, task_id):
        """Build successful A2A response"""
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