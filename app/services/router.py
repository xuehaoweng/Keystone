from app.models.request import ChatRequest, IntentResult
from app.services.intent_classifier import classify_intent
from app.services.load_balancer import ModelInstance, get_load_balancer
from app.services.rule_engine import evaluate_rules


async def resolve_route(request: ChatRequest) -> ModelInstance:
    lb = get_load_balancer()

    # 0. Direct model specification (highest priority)
    if request.model:
        all_status = await lb.get_all()
        if request.model in all_status:
            instance = lb._instances.get(request.model)
            if instance and instance.healthy:
                instance.current_connections += 1
                return instance
        # Model not in LB yet — create instance from config
        from app.config import get_models_config
        models_config = get_models_config()
        model_cfg = next((m for m in models_config.get("models", []) if m["name"] == request.model), None)
        if not model_cfg:
            raise RuntimeError(f"Model '{request.model}' not found in configuration")
        instance = ModelInstance(
            name=model_cfg["name"],
            provider=model_cfg["provider"],
            tier=model_cfg["tier"],
            weight=model_cfg.get("weight", 1),
        )
        instance.current_connections += 1
        return instance

    # 1. Check user's preferred model
    if request.preferred_model:
        all_status = await lb.get_all()
        if request.preferred_model in all_status:
            instance = lb._instances.get(request.preferred_model)
            if instance and instance.healthy:
                instance.current_connections += 1
                return instance

    # 2. Determine tier
    tier = request.model_tier
    if tier == "auto":
        tool_names = [t.name for t in request.tools] if request.tools else []
        rule_result = evaluate_rules(
            [m.model_dump() for m in request.messages],
            tools=tool_names,
        )
        if rule_result.matched:
            tier = rule_result.tier
        else:
            intent: IntentResult = await classify_intent(
                [m.model_dump() for m in request.messages]
            )
            tier = intent.tier

    # 3. Load balancer selects instance
    instance = await lb.select(tier)
    if not instance:
        fallback = "cheap" if tier == "expensive" else "expensive"
        instance = await lb.select(fallback)
    if not instance:
        raise RuntimeError("No available model instances")

    return instance
