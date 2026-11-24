"""FoodShare Smart Assistant: a zero-cost chatbot with an on-device model.

No external AI service, API key or network call is used. Keyword rules and a
small on-device text classifier (ml_intent.py, plain Python) work out WHAT the
user is asking; answers come from
  * knowledge_base.py  - verified facts about how FoodShare works, and
  * existing backend services - the user's OWN data, read through the same
    permission-checked functions the website uses.

    routes.py            HTTP endpoints (/api/v1/chatbot/...)
    service.py           validation, rate limiting, orchestration
    intent_handler.py    keyword rules: understands what the user is asking
    ml_intent.py         small on-device model for other wordings and typos
    training_data.py     example questions the model learns from
    knowledge_base.py    the verified facts (and which features exist)
    response_handler.py  builds answers, including answers from real data
"""
from .routes import bp

__all__ = ["bp"]
