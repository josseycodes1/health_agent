# Project Overview of my Health Tips AI Agent

## Project Purpose
I built a Django-based AI agent that delivers health tips through the A2A protocol for Telex integration. This architecture delivers reliable health tip services through both user-initiated interactions and automated daily reminders.

## Core Agent Functions
This Ai agent performs 2 main functions below

### 1. On-Demand Health Tips
This AI agent provides immediate health tips when users interact with it in Telex. Users request tips through chat messages, and the agent responds with random health advice from our curated database.

### 2. Automated Daily Delivery
This agent automatically sends scheduled health tips three times daily at 9:00 AM, 3:00 PM, and 8:00 PM UTC. This system ensures consistent wellness reminders without user initiation.

## Project Architecture

### Backend Structure
- **Django Framework** powers the web application
- **PostgreSQL Database** stores tip delivery records
- **APScheduler** handles automated daily messaging
- **A2A Protocol** enables Telex platform integration

### Core Components
- **Health Tips Module** in my curated database contains several curated wellness recommendations
- **A2A Endpoint** processes Telex chat interactions
- **Scheduler Service** manages automated tip deliveries
- **Database Models** track delivery history and user contexts

### Integration Features
- **JSON-RPC 2.0 Compliance** ensures protocol standardization
- **Error Handling** provides clear JSON error responses
- **Logging System** monitors agent performance and issues
- **Health Monitoring** offers service status verification

## Technical Implementation

## Data Management
The system stores more than 50 health tips covering nutrition, exercise, mental health, sleep hygiene, and preventive care. Each tip delivery generates database records for tracking and analytics.

### Deployment Configuration
- **Railway Platform** hosts the production environment
- **Gunicorn Server** handles web requests
- **Whitenoise** manages static file serving
- **Environment Variables** secure sensitive configuration

### Automation System
The scheduler triggers three daily executions with time-appropriate messaging:
- Morning tips focus on daily preparation
- Afternoon tips address midday wellness
- Evening tips emphasize rest and recover

# Telex Integration Process - API Call Flow

## 1. User Initiates Interaction
A Telex user sends a message to my health tips ai agent within the Telex application.

## 2. Telex Processes User Request
Telex identifies my ai agent as the target and formats the user message into A2A protocol JSON-RPC format.

## 3. Telex Calls Your Django API
Telex sends an HTTP POST request to my Railway endpoint:
```
POST https://web-production-8b01c.up.railway.app/api/a2a/health
```

## 4. Request Payload Structure
Telex sends this JSON-RPC 2.0 formatted data:
```json
{
  "jsonrpc": "2.0",
  "id": "unique-request-id",
  "method": "message/send",
  "params": {
    "message": {
      "kind": "message",
      "role": "user",
      "parts": [
        {
          "kind": "text",
          "text": "User's actual message here"
        }
      ],
      "messageId": "msg-id",
      "taskId": "task-id"
    },
    "configuration": {
      "blocking": true
    }
  }
}
```

## 5. Django Receives and Processes Request
My `A2AHealthView` class in `views.py` handles the incoming request:

- **Validates JSON-RPC 2.0 format**
- **Extracts user message text** from the parts array
- **Selects random health tip** from my curated database
- **Formats response** according to A2A protocol standards
- **Logs the delivery** in PostgreSQL database

## 6. Response Generation Logic
The system analyzes the user message and applies response rules:

- **Name questions** trigger special workflow response
- **Greetings** return health tips with contextual formatting  
- **Direct requests** provide immediate health advice
- **All other messages** default to health tip delivery

## 7. Django Sends A2A Response
My application returns this structured JSON-RPC response:
```json
{
  "jsonrpc": "2.0",
  "id": "original-request-id",
  "result": {
    "id": "task-id",
    "contextId": "context-id",
    "status": {
      "state": "completed",
      "timestamp": "2025-10-31T13:19:02.013544Z",
      "message": {
        "messageId": "response-msg-id",
        "role": "agent",
        "parts": [
          {
            "kind": "text",
            "text": "Today, remember to practice good health persistence..."
          }
        ],
        "kind": "message",
        "taskId": "task-id"
      }
    },
    "artifacts": [...],
    "history": [...],
    "kind": "task"
  }
}
```

## 8. Telex Receives and Displays Response
Telex processes my A2A response and displays the health tip to the user in the chat interface.

## 9. Automated Daily Flow (Separate Process)
The APScheduler system independently triggers three times daily:

- **9:00 AM UTC** - Calls `/api/daily-tip?time=morning`
- **3:00 PM UTC** - Calls `/api/daily-tip?time=afternoon`  
- **8:00 PM UTC** - Calls `/api/daily-tip?time=evening`

Each call generates time-appropriate health tips without user interaction.

## 10. Database Tracking
Both user-initiated and automated deliveries create records in the `HealthTipDelivery` model for analytics and tracking.

## Key Integration Points

- **A2A Protocol Compliance** ensures Telex compatibility
- **JSON-RPC 2.0 Standard** maintains communication consistency  
- **Railway Deployment** provides reliable hosting infrastructure
- **PostgreSQL Storage** maintains delivery history
- **APScheduler Automation** enables scheduled messaging

This process creates a stress-free experience where Telex users receive health tips through both direct interaction and automated daily reminders.