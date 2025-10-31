import logging
import json
import uuid
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from .health import get_random_tip, get_all_tips
from .models import HealthTipDelivery

logger = logging.getLogger(__name__)

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
        
        try:
            message = params.get("message", {})
            configuration = params.get("configuration", {})
            
            
            context_id = message.get("taskId") or str(uuid.uuid4())
            task_id = message.get("messageId") or str(uuid.uuid4())
            
           
            health_tip = get_random_tip()
            
           
            user_message = ""
            for part in message.get("parts", []):
                if part.get("kind") == "text":
                    user_message = part.get("text", "").lower()
                    break
            
            
            if "name" in user_message and ("what" in user_message or "who" in user_message):
                response_text = "Your question is about my name, which doesn't require a health tip workflow. Do you want me to provide you with a million dollar worth of health tip that would help you keep the doctor away?"
            
            elif "hello" in user_message or "hi" in user_message or "hey" in user_message:
                response_text = f"Today, remember to {health_tip.lower().replace('.', '')}. Don't forget, in case you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            
            elif "tip" in user_message or "advice" in user_message or "suggestion" in user_message:
                response_text = f"Today, remember to {health_tip.lower().replace('.', '')}. Don't forget, in case you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            
            elif "thank" in user_message:
                response_text = f"You're welcome! Today, remember to {health_tip.lower().replace('.', '')}. Don't forget, in case you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            
            else:
                
                response_text = f"Today, remember to {health_tip.lower().replace('.', '')}. Don't forget, in case you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            
           
            HealthTipDelivery.objects.create(
                tip_content=health_tip,
                context_id=context_id,
                task_id=task_id
            )
            
            logger.info(f"Health tip delivered - Context: {context_id}, Task: {task_id}")
            
          
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
        
        try:
            messages = params.get("messages", [])
            context_id = params.get("contextId") or str(uuid.uuid4())
            task_id = params.get("taskId") or str(uuid.uuid4())
            
           
            health_tip = get_random_tip()
            
            
            response_text = f"Today, remember to {health_tip.lower().replace('.', '')}. Don't forget, in case you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            
           
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
                daily_message = f"This morning, keep in mind that {health_tip.lower().replace('.', '')}. Don't forget, in case you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            elif time_of_day == 'afternoon':
                daily_message = f"This afternoon, keep in mind that {health_tip.lower().replace('.', '')}. Don't forget, in case you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            elif time_of_day == 'evening':
                daily_message = f"This night, keep in mind that {health_tip.lower().replace('.', '')}. Don't forget, in case you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            else:
                
                daily_message = f"Today, remember to {health_tip.lower().replace('.', '')}. Don't forget, in case you have severe symptoms of discomfort that has refused to go away, ensure you book an appointment with the doctor today."
            
           
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