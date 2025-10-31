import logging
import json
import uuid
import re
import random
import os
from collections import Counter
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from .health import get_random_tip, get_all_tips
from .models import HealthTipDelivery

logger = logging.getLogger(__name__)

# Import Gemini
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("Google Generative AI package not installed")

class GeminiHealthAssistant:
    def __init__(self):
        self.api_key = os.getenv('GEMINI_API_KEY')
        if self.api_key and GEMINI_AVAILABLE:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel('gemini-pro')
                self.available = True
                logger.info("Gemini AI initialized successfully")
            except Exception as e:
                logger.error(f"Gemini initialization failed: {e}")
                self.available = False
        else:
            self.available = False
            logger.warning("Gemini API key not found or package not available")
    
    def generate_health_response(self, user_message, health_tip):
        """Use Gemini to generate natural, contextual responses with health tips"""
        if not self.available or not user_message.strip():
            # Fallback to simple response if Gemini not available
            return f"Today, remember to {health_tip.lower().replace('.', '')}. Don't forget, if you have severe symptoms, ensure you book an appointment with the doctor today."
        
        try:
            prompt = f"""You are a friendly, engaging Health Tips Assistant. Your role is to:
1. Provide helpful health advice and wellness tips
2. Be conversational and natural
3. Incorporate this health tip naturally into your response: "{health_tip}"
4. Keep responses concise but engaging (1-2 sentences)
5. Encourage further health-related conversation

User message: {user_message}

Respond naturally as a health coach would:"""
            
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=150,
                    temperature=0.7
                )
            )
            
            return response.text.strip()
            
        except Exception as e:
            logger.error(f"Gemini response generation failed: {e}")
            # Fallback response
            return f"Today, remember to {health_tip.lower().replace('.', '')}. Don't forget, if you have severe symptoms, ensure you book an appointment with the doctor today."

# Keep your existing JSONErrorResponse class
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
        self.gemini_assistant = GeminiHealthAssistant()
    
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
        """Handle message/send with Gemini generating complete responses"""
        try:
            message = params.get("message", {})
            configuration = params.get("configuration", {})
            
            context_id = message.get("taskId") or str(uuid.uuid4())
            task_id = message.get("messageId") or str(uuid.uuid4())
            
            health_tip = get_random_tip()
            
            # Extract user message
            user_message = ""
            for part in message.get("parts", []):
                if part.get("kind") == "text":
                    user_message = part.get("text", "").strip()
                    break
            
            # Let Gemini generate the complete response
            response_text = self.gemini_assistant.generate_health_response(user_message, health_tip)
            
            # Log the delivery
            HealthTipDelivery.objects.create(
                tip_content=health_tip,
                context_id=context_id,
                task_id=task_id
            )
            
            logger.info(f"Gemini response generated for user message: {user_message}")
            
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
        """Handle execute method"""
        try:
            messages = params.get("messages", [])
            context_id = params.get("contextId") or str(uuid.uuid4())
            task_id = params.get("taskId") or str(uuid.uuid4())
            
            health_tip = get_random_tip()
            
            # Extract user message from messages if available
            user_message = ""
            if messages:
                for msg in messages:
                    for part in msg.get("parts", []):
                        if part.get("kind") == "text":
                            user_message = part.get("text", "").strip()
                            break
                    if user_message:
                        break
            
            if user_message:
                # Use Gemini to generate response
                response_text = self.gemini_assistant.generate_health_response(user_message, health_tip)
            else:
                # Default response
                response_text = f"Today, remember to {health_tip.lower().replace('.', '')}. Don't forget, if you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            
            HealthTipDelivery.objects.create(
                tip_content=health_tip,
                context_id=context_id,
                task_id=task_id
            )
            
            logger.info(f"Health tip executed - Context: {context_id}, Task: {task_id}")
            
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
                        "name": "health_tip",
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

@method_decorator(csrf_exempt, name='dispatch')
class DailyHealthTipView(View):
    
    def post(self, request):
        try:
            health_tip = get_random_tip()
            task_id = str(uuid.uuid4())
            context_id = f"daily_{timezone.now().strftime('%Y%m%d')}"
            
            time_of_day = request.GET.get('time', 'general').lower()
            
            if time_of_day == 'morning':
                daily_message = f"This morning, remember to {health_tip.lower().replace('.', '')}. Don't forget, if you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            elif time_of_day == 'afternoon':
                daily_message = f"This afternoon, remember to {health_tip.lower().replace('.', '')}. Don't forget, if you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            elif time_of_day == 'evening':
                daily_message = f"This night, remember to {health_tip.lower().replace('.', '')}. Don't forget, if have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            else:
                daily_message = f"Today, remember to {health_tip.lower().replace('.', '')}. Don't forget, if you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            
            HealthTipDelivery.objects.create(
                tip_content=health_tip,
                context_id=f"{context_id}_{time_of_day}",
                task_id=task_id
            )
            
            logger.info(f"Daily health tip delivered - Time: {time_of_day}, Context: {context_id}")
            
            return JsonResponse({
                "status": "success",
                "message": daily_message,
                "tip": health_tip,
                "time_of_day": time_of_day,
                "task_id": task_id,
                "context_id": context_id,
                "timestamp": timezone.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error in daily health tip: {str(e)}")
            return JsonResponse({
                "status": "error",
                "message": str(e)
            }, status=500)

class HealthCheckView(View):
    
    def get(self, request):
        return JsonResponse({
            "status": "healthy",
            "service": "health_tips_agent",
            "timestamp": timezone.now().isoformat()
        })