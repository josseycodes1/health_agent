# Health Tips AI Agent

A Django-based AI agent that provides daily health tips and integrates with Telex app using A2A protocol.

## Features

- RESTful API endpoint to fetch random health tips
- Automated daily health tip delivery at random intervals
- JSON error handling
- Comprehensive logging
- A2A protocol integration ready

## API Endpoints

### GET /api/health-tip/
Returns a random health tip in JSON format.

**Response:**
```json
{
    "tip": "Stay hydrated by drinking at least 8 glasses of water daily.",
    "timestamp": "2024-01-15T10:30:00Z"
}