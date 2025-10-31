"""
Health tips data module
"""

HEALTH_TIPS = [
    "Drink at least 8 glasses of water daily to stay hydrated and support bodily functions.",
    "Aim for 7-9 hours of quality sleep each night for optimal physical and mental health.",
    "Incorporate 30 minutes of moderate exercise into your daily routine.",
    "Eat a balanced diet rich in fruits, vegetables, and whole grains.",
    "Practice mindfulness meditation for 10-15 minutes daily to reduce stress.",
    "Take regular breaks from screens to protect your eye health.",
    "Wash your hands frequently to prevent the spread of germs and illnesses.",
    "Maintain good posture while sitting to prevent back and neck pain.",
    "Get regular health check-ups and screenings as recommended for your age.",
    "Limit processed foods and opt for whole, natural foods instead.",
    "Practice deep breathing exercises to manage stress and improve lung capacity.",
    "Stay socially connected with friends and family for mental well-being.",
    "Protect your skin from sun exposure by using sunscreen daily.",
    "Stretch regularly to maintain flexibility and prevent muscle stiffness.",
    "Limit alcohol consumption and avoid smoking for better long-term health.",
    "Practice good dental hygiene by brushing twice daily and flossing.",
    "Take the stairs instead of the elevator when possible for extra activity.",
    "Stay mentally active by reading, puzzles, or learning new skills.",
    "Maintain a healthy weight through balanced nutrition and regular exercise.",
    "Practice gratitude daily to improve mental health and perspective.",
    "Stay hydrated with water instead of sugary drinks.",
    "Get some sunlight exposure daily for vitamin D, but avoid peak hours.",
    "Practice proper lifting techniques to prevent back injuries.",
    "Limit caffeine intake, especially in the afternoon and evening.",
    "Cook meals at home to control ingredients and portion sizes.",
    "Stay up to date with recommended vaccinations.",
    "Practice safe food handling and preparation techniques.",
    "Wear appropriate protective gear during sports and physical activities.",
    "Manage your time effectively to reduce stress and improve work-life balance.",
    "Listen to your body and rest when you feel tired or unwell."
]

def get_random_tip():
    """Return a random health tip"""
    import random
    return random.choice(HEALTH_TIPS)

def get_all_tips():
    """Return all health tips"""
    return HEALTH_TIPS.copy()