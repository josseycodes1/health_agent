import logging
import json
import uuid
from django.http import JsonResponse
from collections import Counter
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from .health import get_random_tip, get_all_tips
from .models import HealthTipDelivery
import re 
import random 

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

    def detect_intent_advanced(self, user_message):
        """More advanced intent detection using keyword weights"""
        if not user_message or not user_message.strip():
            return {'type': 'greeting', 'original_message': user_message}
            
        user_message_lower = user_message.lower()
        words = re.findall(r'\b\w+\b', user_message_lower)
        word_freq = Counter(words)
        
        # Define intent scores
        intent_scores = {
            'greeting': sum(word_freq[word] for word in ['hello', 'hi', 'hey', 'greetings'] if word in word_freq),
            'request_tip': sum(word_freq[word] for word in ['tip', 'advice', 'suggest', 'recommend', 'should'] if word in word_freq),
            'health_question': sum(word_freq[word] for word in ['how', 'what', 'why', 'when', 'where', 'can', 'could'] if word in word_freq),
            'gratitude': sum(word_freq[word] for word in ['thank', 'thanks', 'appreciate', 'grateful'] if word in word_freq),
            'identity': sum(word_freq[word] for word in ['who', 'name', 'you', 'your'] if word in word_freq),
            'capabilities': sum(word_freq[word] for word in ['what', 'can', 'do', 'help', 'purpose'] if word in word_freq),
            'affirmative': sum(word_freq[word] for word in ['yes', 'yeah', 'sure', 'ok', 'okay', 'please'] if word in word_freq),
            'negative': sum(word_freq[word] for word in ['no', 'not', "don't", 'stop', 'enough', 'never'] if word in word_freq),
        }
        
        # Get intent with highest score
        best_intent = max(intent_scores, key=intent_scores.get)
        
        # Only return specific intent if score is meaningful
        if intent_scores[best_intent] > 0:
            return {'type': best_intent, 'original_message': user_message}
        else:
            return {'type': 'general_inquiry', 'original_message': user_message}
    
    def generate_dynamic_response(self, intent, health_tip, user_message):
        """Generate response based on detected intent"""
        
        intent_type = intent.get('type')
        original_message = intent.get('original_message', '')
        
        response_templates = {
            'greeting': [
                f"Hello! I'm your Health Tips Assistant. {health_tip} Want to know more about staying healthy?",
                f"Hi there! Great to see you focusing on health. {health_tip} Need specific health advice?",
                f"Hey! Ready for some wellness tips? {health_tip} What health topics interest you?"
            ],
            
            'identity': [
                "I'm your Health Tips Assistant! I provide personalized health advice and daily wellness tips. Want me to share a valuable health tip?",
                "I'm here to help with health and wellness guidance. I can share tips on nutrition, exercise, mental health and more! Interested in a health tip?",
                "I'm your go-to for health advice! I specialize in providing practical wellness tips. Shall I share one with you?"
            ],
            
            'capabilities': [
                "I provide health tips, wellness advice, and prevention strategies! I can help with nutrition, exercise, mental health, and general wellness. Want to try a health tip?",
                "I'm your health coach! I share daily tips, answer health questions, and provide wellness guidance. Ready for your first tip?",
                "I offer personalized health advice and daily wellness tips. I can help you stay on track with your health goals. Interested in hearing a tip?"
            ],
            
            'request_tip': [
                f"Sure! Here's a health tip for you: {health_tip} Would you like another tip or is there a specific health area you're curious about?",
                f"Great idea! {health_tip} Want more tips or do you have specific health questions?",
                f"Absolutely! {health_tip} I can provide more tips or help with specific health topics. What would you prefer?"
            ],
            
            'health_question': [
                f"Good question! Here's some relevant advice: {health_tip} Would you like more specific information about this topic?",
                f"I can help with that! {health_tip} Need more details or want to explore other health areas?",
                f"Great question! {health_tip} I can provide more insights if you're interested!"
            ],
            
            'gratitude': [
                f"You're welcome! {health_tip} Feel free to ask for more health advice anytime!",
                f"Glad I could help! {health_tip} Let me know if you need more wellness tips!",
                f"Happy to assist! {health_tip} Don't hesitate to reach out for more health guidance!"
            ],
            
            'affirmative': [
                f"Great! {health_tip} Want another tip or shall we explore a specific health topic?",
                f"Excellent! {health_tip} Ready for more health advice or have specific questions?",
                f"Awesome! {health_tip} Should I continue with more tips or focus on particular health areas?"
            ],
            
            'negative': [
                "No problem! If you change your mind about health tips, I'm here to help. Stay healthy!",
                "Understood! I'll be here if you need health advice later. Take care!",
                "Alright! Remember I'm available whenever you want health tips or wellness guidance."
            ],
            
            'general_inquiry': [
                f"I specialize in health tips and wellness advice! {health_tip} Would you like to hear more tips or ask about specific health topics?",
                f"I'm here to help with health guidance! {health_tip} Want to explore wellness tips or do you have health questions?",
                f"I provide health and wellness advice! {health_tip} Interested in more tips or specific health information?"
            ]
        }
        
        # Select random template for the detected intent
        templates = response_templates.get(intent_type, response_templates['general_inquiry'])
        return random.choice(templates)
    
    def handle_message_send(self, request_id, params):
        """Handle message/send method with advanced intent detection"""
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
            
            # Use advanced intent detection
            intent = self.detect_intent_advanced(user_message)
            response_text = self.generate_dynamic_response(intent, health_tip, user_message)
            
            # Log the delivery
            HealthTipDelivery.objects.create(
                tip_content=health_tip,
                context_id=context_id,
                task_id=task_id
            )
            
            logger.info(f"Health tip delivered - Context: {context_id}, Task: {task_id}, Intent: {intent.get('type')}")
            
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
        """Handle execute method - you can apply the same pattern here if needed"""
        try:
            messages = params.get("messages", [])
            context_id = params.get("contextId") or str(uuid.uuid4())
            task_id = params.get("taskId") or str(uuid.uuid4())
            
            health_tip = get_random_tip()
            
            # For execute method, you can extract text from messages if needed
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
                # Use intent detection for execute method too
                intent = self.detect_intent_advanced(user_message)
                response_text = self.generate_dynamic_response(intent, health_tip, user_message)
            else:
                # Default response if no user message
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