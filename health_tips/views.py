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
    """
    A2A Protocol endpoint for health tips agent
    """
    
    def post(self, request):
        try:
            # Parse request body
            try:
                body = json.loads(request.body)
            except json.JSONDecodeError:
                logger.error("Invalid JSON in request body")
                return JSONErrorResponse.invalid_request(
                    None, 
                    "Invalid JSON format"
                )
            
            # Validate JSON-RPC request
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
        """Handle message/send method"""
        try:
            message = params.get("message", {})
            configuration = params.get("configuration", {})
            
            # Extract context and task IDs
            context_id = message.get("taskId") or str(uuid.uuid4())
            task_id = message.get("messageId") or str(uuid.uuid4())
            
            # Get random health tip
            health_tip = get_random_tip()
            
            # Log the delivery
            HealthTipDelivery.objects.create(
                tip_content=health_tip,
                context_id=context_id,
                task_id=task_id
            )
            
            logger.info(f"Health tip delivered - Context: {context_id}, Task: {task_id}")
            
            # Build A2A response
            response = self.build_success_response(
                request_id, 
                health_tip, 
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
            
            # Get random health tip
            health_tip = get_random_tip()
            
            # Log the delivery
            HealthTipDelivery.objects.create(
                tip_content=health_tip,
                context_id=context_id,
                task_id=task_id
            )
            
            logger.info(f"Health tip executed - Context: {context_id}, Task: {task_id}")
            
            # Build A2A response
            response = self.build_success_response(
                request_id, 
                health_tip, 
                context_id, 
                task_id
            )
            
            return JsonResponse(response)
            
        except Exception as e:
            logger.error(f"Error in handle_execute: {str(e)}")
            return JSONErrorResponse.internal_error(request_id, str(e))
    
    def build_success_response(self, request_id, health_tip, context_id, task_id):
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
                                "text": health_tip
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
                                "text": health_tip
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
                                "text": health_tip
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
    """
    Endpoint for daily automated health tips
    """
    
    def post(self, request):
        try:
            # Get random health tip
            health_tip = get_random_tip()
            task_id = str(uuid.uuid4())
            context_id = f"daily_{timezone.now().strftime('%Y%m%d')}"
            
            # Log the delivery
            HealthTipDelivery.objects.create(
                tip_content=health_tip,
                context_id=context_id,
                task_id=task_id
            )
            
            logger.info(f"Daily health tip delivered - Context: {context_id}")
            
            return JsonResponse({
                "status": "success",
                "tip": health_tip,
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
    """Health check endpoint"""
    
    def get(self, request):
        return JsonResponse({
            "status": "healthy",
            "service": "health_tips_agent",
            "timestamp": timezone.now().isoformat()
        })
